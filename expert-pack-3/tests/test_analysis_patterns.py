"""substation-analysis-mcp 缺陷模式识别测试。

覆盖：同部位重复缺陷簇、家族性缺陷簇、时间窗口过滤、family_min_count 阈值、
device_meta 回退、空数据、参数校验与确定性。
"""

from __future__ import annotations

import json
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

_PACK = Path(__file__).resolve().parents[1]
_SKILL = _PACK / "skills" / "substation-analysis-mcp"
_SCRIPTS = _SKILL / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from analysis.config import BundleError  # noqa: E402
from analysis.patterns import detect_defect_patterns  # noqa: E402

DEMO_PATH = _SKILL / "assets" / "demo_bundle.json"
AS_OF = "2026-06-30"


def demo_bundle() -> dict:
    return json.loads(DEMO_PATH.read_text(encoding="utf-8"))


def days_before(day: int) -> str:
    return (date.fromisoformat(AS_OF) - timedelta(days=day)).isoformat()


def defect(index: int, **overrides) -> dict:
    item = {
        "defectId": f"D-{index:03d}",
        "level": "一般",
        "status": "已消除",
        "discoverTime": days_before(30 + index),
        "part": "本体",
        "desc": "测试缺陷",
    }
    item.update(overrides)
    return item


class DemoPatternTest(unittest.TestCase):
    def setUp(self) -> None:
        bundle = demo_bundle()
        self.result = detect_defect_patterns(
            bundle["defects"], bundle["device"], as_of=bundle["timeWindow"]["end"]
        )

    def test_duplicate_cluster(self) -> None:
        clusters = self.result["duplicateClusters"]
        self.assertEqual(len(clusters), 1)
        cluster = clusters[0]
        self.assertEqual(cluster["part"], "套管")
        self.assertEqual(cluster["count"], 2)
        self.assertEqual(cluster["clusterId"], "DUP-1")
        self.assertEqual(len(cluster["defects"]), 2)
        self.assertIn("严重", cluster["levels"])

    def test_no_family_cluster_for_single_device(self) -> None:
        self.assertEqual(self.result["familyClusters"], [])
        self.assertEqual(self.result["summary"]["familyClusterCount"], 0)

    def test_summary_counts(self) -> None:
        summary = self.result["summary"]
        self.assertEqual(summary["defectCount"], 3)
        self.assertEqual(summary["duplicateClusterCount"], 1)
        self.assertEqual(summary["familyClusterCount"], 0)
        self.assertEqual(summary["asOf"], "2026-09-30")
        self.assertEqual(summary["windowDays"], 365)

    def test_determinism(self) -> None:
        bundle = demo_bundle()
        again = detect_defect_patterns(
            bundle["defects"], bundle["device"], as_of=bundle["timeWindow"]["end"]
        )
        self.assertEqual(self.result, again)


class FamilyClusterTest(unittest.TestCase):
    def _family_defects(self, device_names, part="套管") -> list[dict]:
        defects = []
        for index, name in enumerate(device_names, start=1):
            defects.append(
                defect(
                    index,
                    deviceName=name,
                    model="SSZ11-180000/220",
                    manufacturer="特变电工",
                    part=part,
                    desc="套管渗油",
                )
            )
        return defects

    def test_family_cluster_requires_three_devices(self) -> None:
        defects = self._family_defects(["1号主变", "2号主变", "3号主变"])
        result = detect_defect_patterns(defects, None, as_of=AS_OF)
        self.assertEqual(len(result["familyClusters"]), 1)
        cluster = result["familyClusters"][0]
        self.assertEqual(cluster["deviceCount"], 3)
        self.assertEqual(cluster["deviceNames"], ["1号主变", "2号主变", "3号主变"])
        self.assertEqual(cluster["part"], "套管")
        self.assertEqual(cluster["clusterId"], "FAM-1")

    def test_family_min_count_parameter(self) -> None:
        defects = self._family_defects(["1号主变", "2号主变"])
        two = detect_defect_patterns(defects, None, family_min_count=2, as_of=AS_OF)
        self.assertEqual(len(two["familyClusters"]), 1)
        three = detect_defect_patterns(defects, None, family_min_count=3, as_of=AS_OF)
        self.assertEqual(three["familyClusters"], [])

    def test_device_meta_fallback(self) -> None:
        defects = [defect(1), defect(2)]
        result = detect_defect_patterns(
            defects,
            {"name": "1号主变", "model": "SSZ11", "manufacturer": "特变电工"},
            as_of=AS_OF,
        )
        cluster = result["duplicateClusters"][0]
        self.assertEqual(cluster["deviceName"], "1号主变")
        self.assertEqual(cluster["part"], "本体")

    def test_family_cluster_needs_model_and_manufacturer(self) -> None:
        defects = self._family_defects(["1号主变", "2号主变", "3号主变"])
        for item in defects:
            item.pop("model")
            item.pop("manufacturer")
        result = detect_defect_patterns(defects, None, as_of=AS_OF)
        self.assertEqual(result["familyClusters"], [])
        self.assertTrue(result["dataGaps"])


class WindowAndValidationTest(unittest.TestCase):
    def test_window_excludes_old_defects(self) -> None:
        defects = [
            defect(1, discoverTime=days_before(10)),
            defect(2, discoverTime=days_before(400)),
        ]
        short = detect_defect_patterns(defects, None, window_days=365, as_of=AS_OF)
        self.assertEqual(short["duplicateClusters"], [])
        long = detect_defect_patterns(defects, None, window_days=500, as_of=AS_OF)
        self.assertEqual(len(long["duplicateClusters"]), 1)
        self.assertEqual(long["summary"]["evaluatedCount"], 2)

    def test_as_of_defaults_to_latest_defect_time(self) -> None:
        defects = [defect(1), defect(2)]
        result = detect_defect_patterns(defects, None)
        self.assertEqual(result["summary"]["asOf"], max(item["discoverTime"] for item in defects))

    def test_no_cluster_below_threshold(self) -> None:
        result = detect_defect_patterns([defect(1)], None, as_of=AS_OF)
        self.assertEqual(result["duplicateClusters"], [])
        self.assertEqual(result["familyClusters"], [])

    def test_empty_defects(self) -> None:
        result = detect_defect_patterns([], {"name": "空数据主变", "model": "M", "manufacturer": "F"}, as_of=AS_OF)
        self.assertEqual(result["duplicateClusters"], [])
        self.assertEqual(result["familyClusters"], [])
        self.assertEqual(result["summary"]["defectCount"], 0)
        self.assertTrue(result["dataGaps"])

    def test_invalid_defects_type_raises(self) -> None:
        with self.assertRaises(BundleError):
            detect_defect_patterns({"not": "a list"})  # type: ignore[arg-type]

    def test_defect_without_part_grouped_as_unknown(self) -> None:
        defects = [
            defect(1, part=""),
            defect(2, part=""),
        ]
        result = detect_defect_patterns(defects, None, as_of=AS_OF)
        self.assertEqual(len(result["duplicateClusters"]), 1)
        self.assertEqual(result["duplicateClusters"][0]["part"], "未标注部位")
        self.assertTrue(any("part" in item.get("field", "") for item in result["dataGaps"]))


if __name__ == "__main__":
    unittest.main()
