"""substation-analysis-mcp 健康度评分卡测试。

覆盖：评分维度权重、缺陷/故障/修试/负载/台账扣分规则、单维上限、等级映射、
置信度与完备度公式、证据链结构、站级画像、参数校验与确定性。
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
for _path in (str(_SCRIPTS),):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from analysis.config import ConfigError, load_scorecard  # noqa: E402
from analysis.health import (  # noqa: E402
    _grade_for,
    assess_device_health,
    assess_station_health,
)
from analysis.config import BundleError  # noqa: E402

DEMO_PATH = _SKILL / "assets" / "demo_bundle.json"
AS_OF = "2026-06-30"


def demo_bundle() -> dict:
    return json.loads(DEMO_PATH.read_text(encoding="utf-8"))


def make_bundle(**overrides) -> dict:
    """构造干净的 220kV 主变数据包（默认满分 100 分）。"""
    bundle = {
        "device": {
            "psrId": "PSR-TEST-0001",
            "assetId": "AST-TEST-0001",
            "name": "测试1号主变",
            "stationId": "STA-TEST-01",
            "stationName": "测试变电站",
            "voltageLevel": "220kV",
            "deviceType": "变压器",
            "model": "SSZ11-180000/220",
            "manufacturer": "测试厂家",
            "commissioningDate": "2015-01-01",
        },
        "timeWindow": {"start": "2025-07-01", "end": AS_OF},
        "defects": [],
        "faults": [],
        "tests": [{"recordId": "RT-0001", "testDate": "2026-01-10", "result": "合格"}],
        "load": {
            "ratedCapacityMVA": 100,
            "currentLoadMVA": 50,
            "openCapacityMVA": 20,
            "loadRate": 50.0,
        },
        "reliability": {"availabilityRate": 99.9},
    }
    bundle.update(overrides)
    return bundle


def days_before(day: int) -> str:
    return (date.fromisoformat(AS_OF) - timedelta(days=day)).isoformat()


class DemoScoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.bundle = demo_bundle()
        self.result = assess_device_health(self.bundle)

    def test_demo_score_grade_and_risk(self) -> None:
        self.assertEqual(self.result["score"], 75.8)
        self.assertEqual(self.result["grade"], "C")
        self.assertEqual(self.result["gradeLabel"], "注意")
        self.assertEqual(self.result["risk"], "中")
        self.assertEqual(self.result["asOf"], "2026-09-30")

    def test_dimensions_weights_sum_to_one(self) -> None:
        dimensions = self.result["dimensions"]
        self.assertEqual([item["id"] for item in dimensions], ["defects", "faults", "tests", "load", "ledger"])
        self.assertEqual([item["weight"] for item in dimensions], [0.30, 0.25, 0.20, 0.15, 0.10])
        self.assertAlmostEqual(sum(item["weight"] for item in dimensions), 1.0)

    def test_demo_dimension_deductions(self) -> None:
        by_id = {item["id"]: item for item in self.result["dimensions"]}
        self.assertEqual(by_id["defects"]["deduction"], 40)
        self.assertEqual(by_id["defects"]["score"], 60)
        self.assertEqual(by_id["faults"]["deduction"], 25)
        self.assertEqual(by_id["tests"]["deduction"], 30)
        self.assertEqual(by_id["load"]["deduction"], 0)
        self.assertEqual(by_id["ledger"]["deduction"], 0)

    def test_deductions_are_weighted_to_total(self) -> None:
        expected = sum(
            item["weight"] * item["score"] for item in self.result["dimensions"]
        )
        self.assertEqual(self.result["score"], round(expected + 0.0, 1))

    def test_evidence_shape_and_source_codes(self) -> None:
        self.assertTrue(self.result["deductions"])
        for item in self.result["deductions"]:
            self.assertEqual(
                set(item), {"ruleId", "dimension", "delta", "reason", "source", "data"}
            )
            self.assertLess(item["delta"], 0)
            self.assertIsInstance(item["reason"], str)
            self.assertTrue(item["reason"])
            self.assertEqual(len(item["source"]), 1)
            self.assertRegex(item["source"][0], r"^pgp-\d{3}-\d{4}-\d{5}$")

    def test_demo_knowledge_queries(self) -> None:
        self.assertTrue(self.result["knowledgeQueries"])
        joined = "".join(self.result["knowledgeQueries"])
        self.assertIn("危急缺陷", joined)
        self.assertIn("试验", joined)

    def test_demo_completeness_and_confidence(self) -> None:
        completeness = self.result["completeness"]
        self.assertEqual(completeness["present"], 4)
        self.assertEqual(completeness["total"], 4)
        self.assertEqual(completeness["ratio"], 1.0)
        self.assertEqual(self.result["confidence"], 0.9)
        self.assertEqual(self.result["dataGaps"], [])

    def test_summary_contains_score_and_grade(self) -> None:
        summary = self.result["summary"]
        self.assertIn("1号主变", summary)
        self.assertIn("75.8", summary)
        self.assertIn("C·注意", summary)
        self.assertIn("置信度 0.9", summary)

    def test_determinism(self) -> None:
        self.assertEqual(self.result, assess_device_health(demo_bundle()))


class DimensionRuleTest(unittest.TestCase):
    def test_clean_bundle_scores_full_marks(self) -> None:
        result = assess_device_health(make_bundle(), as_of=AS_OF)
        self.assertEqual(result["score"], 100.0)
        self.assertEqual(result["grade"], "A")
        self.assertEqual(result["deductions"], [])

    def test_defect_levels_and_closed_excluded(self) -> None:
        bundle = make_bundle(
            defects=[
                {"defectId": "D1", "level": "危急", "status": "待处理", "discoverTime": AS_OF},
                {"defectId": "D2", "level": "严重", "status": "处理中", "discoverTime": AS_OF},
                {"defectId": "D3", "level": "一般", "status": "待处理", "discoverTime": AS_OF},
                {"defectId": "D4", "level": "严重", "status": "已消除", "discoverTime": AS_OF},
            ]
        )
        result = assess_device_health(bundle, as_of=AS_OF)
        deltas = sorted(item["delta"] for item in result["deductions"])
        # -30(危急) -15(严重) -5(一般)；已消除不计；当日不超期
        self.assertEqual(deltas, [-30, -15, -5])
        self.assertNotIn("D4", json.dumps(result["deductions"], ensure_ascii=False))

    def test_overdue_thresholds(self) -> None:
        bundle = make_bundle(
            defects=[
                {"defectId": "C1", "level": "危急", "status": "待处理", "discoverTime": days_before(2)},
                {"defectId": "S1", "level": "严重", "status": "待处理", "discoverTime": days_before(8)},
                {"defectId": "N1", "level": "一般", "status": "待处理", "discoverTime": days_before(31)},
                {"defectId": "N2", "level": "一般", "status": "待处理", "discoverTime": days_before(30)},
            ]
        )
        result = assess_device_health(bundle, as_of=AS_OF)
        overdue = [item for item in result["deductions"] if item["ruleId"] == "DEF-OVERDUE"]
        self.assertEqual(len(overdue), 3)
        self.assertEqual({item["data"]["defectId"] for item in overdue}, {"C1", "S1", "N1"})
        by_defect = {item["data"]["defectId"]: item["data"]["openDays"] for item in overdue}
        self.assertEqual(by_defect, {"C1": 2, "S1": 8, "N1": 31})

    def test_defect_dimension_capped_at_100(self) -> None:
        defects = [
            {"defectId": f"X{i}", "level": "危急", "status": "待处理", "discoverTime": AS_OF}
            for i in range(10)
        ]
        result = assess_device_health(make_bundle(defects=defects, tests=[]), as_of=AS_OF)
        defects_dim = result["dimensions"][0]
        self.assertEqual(defects_dim["deduction"], 100)
        self.assertEqual(defects_dim["score"], 0)

    def test_fault_time_windows(self) -> None:
        bundle = make_bundle(
            faults=[
                {"faultId": "F1", "time": days_before(365)},
                {"faultId": "F2", "time": days_before(366)},
                {"faultId": "F3", "time": days_before(1095)},
                {"faultId": "F4", "time": days_before(1096)},
            ]
        )
        result = assess_device_health(bundle, as_of=AS_OF)
        faults = [item for item in result["deductions"] if item["dimension"] == "faults"]
        deltas = {item["data"]["faultId"]: item["delta"] for item in faults}
        self.assertEqual(deltas, {"F1": -25, "F2": -10, "F3": -10})

    def test_tests_no_record(self) -> None:
        result = assess_device_health(make_bundle(tests=[]), as_of=AS_OF)
        tests_dim = {item["id"]: item for item in result["dimensions"]}["tests"]
        self.assertEqual(tests_dim["deduction"], 20)
        self.assertTrue(any(item["ruleId"] == "TEST-NO-RECORD" for item in result["deductions"]))

    def test_tests_stale_and_unqualified(self) -> None:
        bundle = make_bundle(
            tests=[
                {"recordId": "OLD1", "testDate": "2019-01-01", "result": "不合格"},
                {"recordId": "OLD2", "testDate": "2019-06-01", "result": "异常"},
            ]
        )
        result = assess_device_health(bundle, as_of=AS_OF)
        rules = [item["ruleId"] for item in result["deductions"]]
        self.assertEqual(rules.count("TEST-UNQUALIFIED"), 2)
        self.assertIn("TEST-STALE", rules)
        tests_dim = {item["id"]: item for item in result["dimensions"]}["tests"]
        self.assertEqual(tests_dim["deduction"], 80)

    def test_load_rules(self) -> None:
        result = assess_device_health(
            make_bundle(load={"ratedCapacityMVA": 100, "currentLoadMVA": 95, "openCapacityMVA": 2, "loadRate": 95}),
            as_of=AS_OF,
        )
        rules = [item["ruleId"] for item in result["deductions"] if item["dimension"] == "load"]
        self.assertIn("LOAD-OVERLOAD", rules)
        self.assertIn("LOAD-LOW-OPEN-CAPACITY", rules)
        load_dim = {item["id"]: item for item in result["dimensions"]}["load"]
        self.assertEqual(load_dim["deduction"], 30)

        heavy = assess_device_health(
            make_bundle(load={"ratedCapacityMVA": 100, "currentLoadMVA": 85, "openCapacityMVA": 20, "loadRate": 85}),
            as_of=AS_OF,
        )
        rules_heavy = [item["ruleId"] for item in heavy["deductions"] if item["dimension"] == "load"]
        self.assertEqual(rules_heavy, ["LOAD-HEAVY"])

    def test_load_rate_derived_from_capacity(self) -> None:
        bundle = make_bundle(
            load={"ratedCapacityMVA": 100, "currentLoadMVA": 92, "openCapacityMVA": 20}
        )
        result = assess_device_health(bundle, as_of=AS_OF)
        self.assertIn(
            "LOAD-OVERLOAD",
            [item["ruleId"] for item in result["deductions"] if item["dimension"] == "load"],
        )

    def test_ledger_missing_fields(self) -> None:
        bundle = make_bundle(device={"name": "仅名称主变"})
        result = assess_device_health(bundle, as_of=AS_OF)
        ledger = {item["id"]: item for item in result["dimensions"]}["ledger"]
        # 4 个关键字段各 -10，assetId/psrId 均缺失再 -20
        self.assertEqual(ledger["deduction"], 60)
        self.assertEqual(ledger["score"], 40)
        rules = [item["ruleId"] for item in result["deductions"] if item["dimension"] == "ledger"]
        self.assertIn("LEDGER-MISSING-IDS", rules)
        self.assertEqual(sum(1 for rule in rules if rule.startswith("LEDGER-MISSING-")), 5)


class ConfidenceAndCompletenessTest(unittest.TestCase):
    def test_missing_sections_reduce_confidence(self) -> None:
        bundle = {"device": {"name": "无数据主变"}}
        result = assess_device_health(bundle)
        self.assertEqual(result["completeness"]["present"], 0)
        self.assertEqual(result["completeness"]["total"], 4)
        self.assertEqual(result["completeness"]["missing"], ["defects", "faults", "tests", "load"])
        self.assertEqual(result["confidence"], 0.7)
        self.assertTrue(result["dataGaps"])
        self.assertIsNone(result["asOf"])

    def test_single_missing_section_penalty(self) -> None:
        bundle = make_bundle()
        bundle.pop("load")
        result = assess_device_health(bundle, as_of=AS_OF)
        self.assertEqual(result["confidence"], 0.85)
        self.assertEqual(result["completeness"]["present"], 3)

    def test_stale_time_window_penalty(self) -> None:
        bundle = make_bundle(timeWindow={"start": "2023-01-01", "end": "2024-01-01"})
        result = assess_device_health(bundle, as_of="2026-06-30")
        self.assertEqual(result["confidence"], 0.8)
        self.assertEqual(result["deductions"], [])

    def test_confidence_never_exceeds_cap(self) -> None:
        result = assess_device_health(make_bundle(), as_of=AS_OF)
        self.assertLessEqual(result["confidence"], 0.95)
        self.assertEqual(result["confidence"], 0.9)

    def test_grade_boundaries(self) -> None:
        card = load_scorecard()
        self.assertEqual(_grade_for(90, card)["grade"], "A")
        self.assertEqual(_grade_for(89.9, card)["grade"], "B")
        self.assertEqual(_grade_for(80, card)["grade"], "B")
        self.assertEqual(_grade_for(70, card)["grade"], "C")
        self.assertEqual(_grade_for(60, card)["grade"], "D")
        self.assertEqual(_grade_for(59.9, card)["grade"], "E")
        self.assertEqual(_grade_for(59.9, card)["risk"], "高")

    def test_as_of_override_changes_time_based_rules(self) -> None:
        bundle = make_bundle(
            tests=[{"recordId": "RT1", "testDate": "2024-01-01", "result": "合格"}],
            timeWindow={"start": "2025-07-01", "end": "2026-06-30"},
        )
        near = assess_device_health(bundle, as_of="2025-01-01")
        far = assess_device_health(bundle, as_of="2028-01-01")
        self.assertNotIn("TEST-STALE", [item["ruleId"] for item in near["deductions"]])
        self.assertIn("TEST-STALE", [item["ruleId"] for item in far["deductions"]])

    def test_unknown_scorecard_profile(self) -> None:
        with self.assertRaises(ConfigError):
            assess_device_health(make_bundle(), scorecard_profile="no_such_profile")


class ValidationTest(unittest.TestCase):
    def test_bundle_must_be_object(self) -> None:
        with self.assertRaises(BundleError):
            assess_device_health([])  # type: ignore[arg-type]

    def test_device_name_required(self) -> None:
        with self.assertRaises(BundleError):
            assess_device_health({"device": {}})
        with self.assertRaises(BundleError):
            assess_device_health({})

    def test_station_health_requires_devices(self) -> None:
        with self.assertRaises(BundleError):
            assess_station_health([])


class StationHealthTest(unittest.TestCase):
    def setUp(self) -> None:
        self.bundles = [
            make_bundle(),
            make_bundle(
                device={**make_bundle()["device"], "name": "测试2号主变"},
                defects=[
                    {"defectId": "S1", "level": "严重", "status": "待处理", "discoverTime": AS_OF}
                ],
            ),
            make_bundle(
                device={**make_bundle()["device"], "name": "测试3号主变"},
                defects=[
                    {"defectId": "C1", "level": "危急", "status": "待处理", "discoverTime": days_before(3)},
                    {"defectId": "C2", "level": "危急", "status": "待处理", "discoverTime": days_before(3)},
                ],
            ),
        ]
        self.result = assess_station_health(
            self.bundles,
            {"stationId": "STA-TEST-01", "stationName": "测试变电站", "voltageLevel": "220kV"},
            top_n=2,
            as_of=AS_OF,
        )

    def test_station_meta_and_device_count(self) -> None:
        self.assertEqual(self.result["station"]["stationName"], "测试变电站")
        self.assertEqual(self.result["station"]["deviceCount"], 3)
        self.assertEqual(len(self.result["devices"]), 3)

    def test_aggregate(self) -> None:
        aggregate = self.result["aggregate"]
        scores = [item["score"] for item in self.result["devices"]]
        self.assertEqual(aggregate["avgScore"], round(sum(scores) / len(scores), 1))
        self.assertEqual(sum(aggregate["gradeDistribution"].values()), 3)
        self.assertEqual(len(aggregate["riskTop"]), 2)
        self.assertEqual(
            [item["score"] for item in aggregate["riskTop"]],
            sorted(item["score"] for item in aggregate["riskTop"]),
        )
        self.assertEqual(
            aggregate["criticalCount"],
            sum(1 for item in self.result["devices"] if item["grade"] in ("D", "E")),
        )

    def test_station_knowledge_queries(self) -> None:
        self.assertTrue(self.result["knowledgeQueries"])
        self.assertTrue(any("站级" in item for item in self.result["knowledgeQueries"]))


if __name__ == "__main__":
    unittest.main()
