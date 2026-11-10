"""substation-analysis-mcp 命令行测试。

覆盖：health/station-health/diagnose/patterns/metrics/report/list-report-types/demo 子命令、
JSON 输出（ensure_ascii=False）、退出码（0/1/2）、--as-of、--compact、演示确定性与报告占位符。
"""

from __future__ import annotations

import io
import json
import re
import sys
import unittest
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Iterator

_PACK = Path(__file__).resolve().parents[1]
_SKILL = _PACK / "skills" / "substation-analysis-mcp"
_SCRIPTS = _SKILL / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import analysis_cli  # noqa: E402

DEMO_PATH = str(_SKILL / "assets" / "demo_bundle.json")
AS_OF = "2026-06-30"


@contextmanager
def stdin_text(text: str) -> Iterator[None]:
    """把 stdin 替换为文本（CLI 支持 --bundle - / --payload - / --citations -）。"""
    original = sys.stdin
    sys.stdin = io.StringIO(text)
    try:
        yield
    finally:
        sys.stdin = original


def run_cli(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = analysis_cli.main(argv)
    return code, out.getvalue(), err.getvalue()


def parse_cli(argv: list[str]) -> tuple[int, dict, str]:
    code, out, err = run_cli(argv)
    return code, json.loads(out) if out.strip() else {}, err


class ReadCommandTest(unittest.TestCase):
    def test_health(self) -> None:
        code, payload, _ = parse_cli(["health", "--bundle", DEMO_PATH])
        self.assertEqual(code, 0)
        self.assertEqual(payload["score"], 75.8)
        self.assertEqual(payload["grade"], "C")

    def test_health_as_of_override(self) -> None:
        code, payload, _ = parse_cli(["health", "--bundle", DEMO_PATH, "--as-of", "2030-01-01"])
        self.assertEqual(code, 0)
        self.assertIn("TEST-STALE", [item["ruleId"] for item in payload["deductions"]])

    def test_diagnose(self) -> None:
        code, payload, _ = parse_cli(["diagnose", "--bundle", DEMO_PATH, "--max-hypotheses", "2"])
        self.assertEqual(code, 0)
        self.assertLessEqual(len(payload["hypotheses"]), 2)
        self.assertEqual(payload["hypotheses"][0]["ruleId"], "DIAG-BUSHING-MOISTURE")

    def test_metrics(self) -> None:
        code, payload, _ = parse_cli(["metrics", "--bundle", DEMO_PATH])
        self.assertEqual(code, 0)
        self.assertEqual(payload["metrics"]["loadRate"], 70.0)
        self.assertEqual(payload["metrics"]["overdueOpen"], 2)

    def test_patterns(self) -> None:
        code, payload, _ = parse_cli(["patterns", "--bundle", DEMO_PATH, "--window-days", "365"])
        self.assertEqual(code, 0)
        self.assertEqual(payload["summary"]["duplicateClusterCount"], 1)
        self.assertEqual(payload["summary"]["asOf"], "2026-09-30")

    def test_station_health(self) -> None:
        bundle = json.loads(Path(DEMO_PATH).read_text(encoding="utf-8"))
        second = json.loads(json.dumps(bundle, ensure_ascii=False))
        second["device"]["name"] = "2号主变"
        data = {"station": {"stationName": "220kV 郑州变电站"}, "bundles": [bundle, second]}
        with stdin_text(json.dumps(data, ensure_ascii=False)):
            code, payload, _ = parse_cli(["station-health", "--bundle", "-", "--top-n", "1"])
        self.assertEqual(code, 0)
        self.assertEqual(payload["station"]["deviceCount"], 2)
        self.assertEqual(len(payload["aggregate"]["riskTop"]), 1)

    def test_list_report_types(self) -> None:
        code, payload, _ = parse_cli(["list-report-types"])
        self.assertEqual(code, 0)
        self.assertEqual(len(payload["reportTypes"]), 3)
        self.assertEqual(payload["reportTypes"][0]["type"], "device_profile")


class ReportCommandTest(unittest.TestCase):
    def test_report_from_bundle(self) -> None:
        code, payload, _ = parse_cli(
            ["report", "--type", "device_profile", "--bundle", DEMO_PATH]
        )
        self.assertEqual(code, 0)
        self.assertEqual(payload["reportType"], "device_profile")
        self.assertNotIn("{{", payload["markdown"])
        self.assertIn("1号主变", payload["markdown"])
        self.assertTrue(payload["sections"])

    def test_report_with_payload_file_and_missing_keys(self) -> None:
        with stdin_text(json.dumps({"device": {"name": "缺数据主变"}}, ensure_ascii=False)):
            code, payload, _ = parse_cli(
                ["report", "--type", "device_profile", "--payload", "-"]
            )
        self.assertEqual(code, 0)
        self.assertIn("数据未提供", payload["markdown"])
        self.assertNotIn("{{", payload["markdown"])
        self.assertTrue(payload["dataGaps"])

    def test_report_with_citations_file(self) -> None:
        citations = [
            {"title": "变压器运行规程", "source": "DL/T 572", "snippet": "套管介损要求", "kbId": "KB-1"}
        ]
        with stdin_text(json.dumps(citations, ensure_ascii=False)):
            code, payload, _ = parse_cli(
                [
                    "report",
                    "--type",
                    "device_profile",
                    "--bundle",
                    DEMO_PATH,
                    "--citations",
                    "-",
                    "--title",
                    "自定义标题",
                ]
            )
        self.assertEqual(code, 0)
        self.assertEqual(payload["title"], "自定义标题")
        self.assertIn("变压器运行规程", payload["markdown"])

    def test_report_fault_review(self) -> None:
        code, payload, _ = parse_cli(
            ["report", "--type", "fault_review", "--bundle", DEMO_PATH]
        )
        self.assertEqual(code, 0)
        self.assertIn("差动保护动作", payload["markdown"])


class DemoCommandTest(unittest.TestCase):
    def setUp(self) -> None:
        self.code, self.out, self.err = run_cli(["demo"])
        self.payload = json.loads(self.out)

    def test_demo_runs_full_pipeline(self) -> None:
        self.assertEqual(self.code, 0)
        for key in ("summary", "health", "diagnosis", "patterns", "metrics", "report"):
            self.assertIn(key, self.payload)
        self.assertTrue(self.payload["demo"])
        self.assertEqual(self.payload["summary"]["device"], "1号主变")
        self.assertEqual(self.payload["summary"]["score"], 75.8)
        self.assertEqual(self.payload["summary"]["grade"], "C")

    def test_demo_summary(self) -> None:
        summary = self.payload["summary"]
        self.assertTrue(summary["topHypotheses"])
        self.assertEqual(summary["report"]["reportType"], "device_profile")
        self.assertEqual(summary["reportTypes"], 3)
        self.assertEqual(summary["patternSummary"]["duplicateClusterCount"], 1)
        self.assertEqual(summary["metrics"]["loadRate"], 70.0)
        self.assertGreater(summary["report"]["markdownChars"], 500)

    def test_demo_report_no_placeholder(self) -> None:
        markdown = self.payload["report"]["markdown"]
        self.assertNotIn("{{", markdown)
        self.assertNotIn("}}", markdown)

    def test_demo_utf8_chinese(self) -> None:
        self.assertIn("健康度", self.out)
        self.assertNotIn("\\u5065", self.out)

    def test_demo_deterministic_except_generated_at(self) -> None:
        code2, out2, _ = run_cli(["demo"])
        self.assertEqual(code2, 0)
        second = json.loads(out2)
        first_generated = self.payload["report"].pop("generatedAt")
        second_generated = second["report"].pop("generatedAt")
        pattern = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+\-]\d{2}:\d{2}")
        first_markdown = pattern.sub("<generatedAt>", self.payload["report"]["markdown"])
        second_markdown = pattern.sub("<generatedAt>", second["report"]["markdown"])
        self.payload["report"]["markdown"] = first_markdown
        second["report"]["markdown"] = second_markdown
        self.assertNotEqual(first_generated, "")
        self.assertNotEqual(second_generated, "")
        self.assertEqual(self.payload, second)

    def test_demo_compact_single_line(self) -> None:
        code, out, _ = run_cli(["demo", "--compact"])
        self.assertEqual(code, 0)
        lines = [line for line in out.splitlines() if line.strip()]
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("{"))


class CliErrorTest(unittest.TestCase):
    def test_missing_bundle_file(self) -> None:
        code, out, err = run_cli(["health", "--bundle", "no_such_bundle.json"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("DATA_ERROR", err)

    def test_invalid_json_bundle(self) -> None:
        with stdin_text("{not json"):
            code, _, err = run_cli(["health", "--bundle", "-"])
        self.assertEqual(code, 1)
        self.assertIn("DATA_ERROR", err)

    def test_bundle_without_device(self) -> None:
        with stdin_text(json.dumps({"defects": []})):
            code, _, err = run_cli(["health", "--bundle", "-"])
        self.assertEqual(code, 1)
        self.assertIn("DATA_ERROR", err)

    def test_invalid_as_of(self) -> None:
        code, _, err = run_cli(["health", "--bundle", DEMO_PATH, "--as-of", "2026/01/01"])
        self.assertEqual(code, 2)
        self.assertIn("USAGE_ERROR", err)

    def test_missing_bundle_argument(self) -> None:
        code, out, err = run_cli(["health"])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("USAGE_ERROR", err)
        self.assertIn("--bundle", err)

    def test_invalid_report_type(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                analysis_cli.main(["report", "--type", "weekly", "--bundle", DEMO_PATH])
        self.assertEqual(ctx.exception.code, 2)

    def test_no_command_prints_usage(self) -> None:
        code, _, err = run_cli([])
        self.assertEqual(code, 2)
        self.assertIn("usage", err.lower())


if __name__ == "__main__":
    unittest.main()
