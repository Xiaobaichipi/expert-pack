"""substation-analysis-mcp 报告渲染测试。

覆盖：3 类模板清单与必需 payload 键、占位符渲染无残留、citations 引用列表、
缺键「数据未提供」+ dataGaps、自定义标题、非法参数、generatedAt、确定性。
"""

from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime
from pathlib import Path

_PACK = Path(__file__).resolve().parents[1]
_SKILL = _PACK / "skills" / "substation-analysis-mcp"
_SCRIPTS = _SKILL / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from analysis import (  # noqa: E402
    assess_device_health,
    assess_station_health,
    compute_device_metrics,
    diagnose_equipment,
)
from analysis.config import ReportError, TEMPLATES_DIR  # noqa: E402
from analysis.report import (  # noqa: E402
    MISSING_TEXT,
    REPORT_TYPES,
    generate_report,
    list_report_types,
)

DEMO_PATH = _SKILL / "assets" / "demo_bundle.json"
AS_OF = "2026-06-30"


def demo_bundle() -> dict:
    return json.loads(DEMO_PATH.read_text(encoding="utf-8"))


def device_payload() -> dict:
    bundle = demo_bundle()
    health = assess_device_health(bundle)
    diagnosis = diagnose_equipment(bundle)
    metrics = compute_device_metrics(bundle)
    return {
        "device": bundle["device"],
        "health": health,
        "diagnosis": diagnosis,
        "metrics": metrics,
        "defects": bundle["defects"],
        "tests": bundle["tests"],
        "timeWindow": bundle["timeWindow"],
        "asOf": health["asOf"],
        "dataGaps": health["dataGaps"] + diagnosis["dataGaps"] + metrics["dataGaps"],
    }


def station_payload() -> dict:
    bundle = demo_bundle()
    result = assess_station_health([bundle, bundle], as_of=AS_OF)
    result["period"] = "2026-06-01 至 2026-06-30"
    return result


def fault_payload() -> dict:
    payload = device_payload()
    payload["fault"] = demo_bundle()["faults"][0]
    return payload


def _strip_timestamps(markdown: str, generated_at: str) -> str:
    return markdown.replace(generated_at, "<generatedAt>")


class ListReportTypesTest(unittest.TestCase):
    def test_three_report_types(self) -> None:
        result = list_report_types()
        self.assertEqual(len(result["reportTypes"]), 3)
        self.assertEqual(
            [item["type"] for item in result["reportTypes"]],
            ["device_profile", "station_monthly", "fault_review"],
        )

    def test_required_payload_keys(self) -> None:
        result = {item["type"]: item for item in list_report_types()["reportTypes"]}
        self.assertEqual(result["device_profile"]["requiredPayloadKeys"], ["device", "health"])
        self.assertEqual(result["station_monthly"]["requiredPayloadKeys"], ["station", "aggregate"])
        self.assertEqual(result["fault_review"]["requiredPayloadKeys"], ["fault"])
        for item in result.values():
            self.assertTrue(item["name"])

    def test_code_and_config_templates_consistent(self) -> None:
        self.assertEqual(len(REPORT_TYPES), 3)
        types = {item["type"] for item in REPORT_TYPES}
        self.assertEqual(types, {"device_profile", "station_monthly", "fault_review"})
        for item in REPORT_TYPES:
            self.assertTrue((TEMPLATES_DIR / item["template"]).is_file())


class DeviceProfileTest(unittest.TestCase):
    def setUp(self) -> None:
        self.report = generate_report("device_profile", device_payload())

    def test_result_shape(self) -> None:
        self.assertEqual(self.report["reportType"], "device_profile")
        self.assertEqual(self.report["title"], "设备画像报告")
        self.assertIn("markdown", self.report)
        self.assertTrue(self.report["sections"])
        self.assertTrue(self.report["generatedAt"])

    def test_no_placeholder_residue(self) -> None:
        self.assertNotIn("{{", self.report["markdown"])
        self.assertNotIn("}}", self.report["markdown"])

    def test_content_rendered(self) -> None:
        markdown = self.report["markdown"]
        self.assertIn("1号主变", markdown)
        self.assertIn("75.8", markdown)
        self.assertIn("C（注意）", markdown)
        self.assertIn("套管", markdown)
        self.assertIn("缺陷率", markdown)
        self.assertIn("知识库未检索到相关条款", markdown)

    def test_sections_contain_expected_titles(self) -> None:
        titles = [item["title"] for item in self.report["sections"]]
        self.assertIn("二、健康度评估", titles)
        self.assertIn("三、跨域根因诊断", titles)
        for section in self.report["sections"]:
            self.assertTrue(section["id"])
            self.assertTrue(section["title"])

    def test_custom_title(self) -> None:
        report = generate_report("device_profile", device_payload(), title="1号主变专项画像")
        self.assertEqual(report["title"], "1号主变专项画像")
        self.assertIn("# 1号主变专项画像", report["markdown"])

    def test_citations_rendered(self) -> None:
        citations = [
            {
                "title": "变压器运行规程",
                "source": "DL/T 572",
                "snippet": "套管介损超过规定值时应进行复核试验。",
                "kbId": "KB-001",
            },
            {
                "title": "缺陷管理规定",
                "source": "国网运检",
                "snippet": "严重缺陷应在 7 天内消除。",
                "kbId": "KB-002",
            },
        ]
        report = generate_report("device_profile", device_payload(), citations=citations)
        markdown = report["markdown"]
        self.assertIn("变压器运行规程", markdown)
        self.assertIn("DL/T 572", markdown)
        self.assertIn("KB-002", markdown)
        self.assertNotIn("{{", markdown)

    def test_generated_at_is_iso(self) -> None:
        parsed = datetime.fromisoformat(self.report["generatedAt"])
        self.assertIsNotNone(parsed.tzinfo)

    def test_determinism_except_generated_at(self) -> None:
        again = generate_report("device_profile", device_payload())
        first_md = _strip_timestamps(self.report["markdown"], self.report["generatedAt"])
        second_md = _strip_timestamps(again["markdown"], again["generatedAt"])
        self.assertEqual(first_md, second_md)
        first = dict(self.report, generatedAt=None, markdown=None)
        second = dict(again, generatedAt=None, markdown=None)
        self.assertEqual(first, second)


class MissingPayloadTest(unittest.TestCase):
    def test_missing_keys_render_placeholder_and_gaps(self) -> None:
        for report_type in ("device_profile", "station_monthly", "fault_review"):
            with self.subTest(report_type=report_type):
                report = generate_report(report_type, {})
                self.assertIn(MISSING_TEXT, report["markdown"])
                self.assertNotIn("{{", report["markdown"])
                self.assertTrue(report["dataGaps"])
                fields = {item.get("field") for item in report["dataGaps"]}
                required = set(
                    {item["type"]: item for item in REPORT_TYPES}[report_type]["requiredPayloadKeys"]
                )
                self.assertTrue(required.issubset(fields))

    def test_payload_gaps_propagated(self) -> None:
        payload = device_payload()
        payload["dataGaps"] = [
            {"section": "load", "field": "loadRate", "reason": "缺少负载率"}
        ]
        report = generate_report("device_profile", payload)
        self.assertTrue(any(item.get("reason") == "缺少负载率" for item in report["dataGaps"]))
        self.assertIn("缺少负载率", report["markdown"])


class StationAndFaultReportTest(unittest.TestCase):
    def test_station_monthly_render(self) -> None:
        report = generate_report("station_monthly", station_payload())
        markdown = report["markdown"]
        self.assertNotIn("{{", markdown)
        self.assertIn("220kV 郑州变电站", markdown)
        self.assertIn("平均健康分", markdown)
        self.assertIn("等级分布", markdown)
        titles = [item["title"] for item in report["sections"]]
        self.assertIn("一、站级概况", titles)

    def test_fault_review_render(self) -> None:
        report = generate_report("fault_review", fault_payload())
        markdown = report["markdown"]
        self.assertNotIn("{{", markdown)
        self.assertIn("差动保护动作", markdown)
        self.assertIn("根因假设排序", markdown)

    def test_fault_review_without_fault_data(self) -> None:
        report = generate_report("fault_review", {"device": {"name": "无故障主变"}})
        self.assertIn(MISSING_TEXT, report["markdown"])
        self.assertNotIn("{{", report["markdown"])
        self.assertTrue(report["dataGaps"])


class InvalidArgumentTest(unittest.TestCase):
    def test_unknown_report_type(self) -> None:
        with self.assertRaises(ReportError):
            generate_report("monthly", {})

    def test_payload_must_be_object(self) -> None:
        with self.assertRaises(ReportError):
            generate_report("device_profile", [])  # type: ignore[arg-type]

    def test_citations_must_be_list(self) -> None:
        with self.assertRaises(ReportError):
            generate_report("device_profile", {}, citations={"title": "x"})  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
