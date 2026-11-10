"""substation-analysis-mcp 诊断规则库与证据链测试。

覆盖：规则库契约（≥10 条/字段完整）、演示 bundle 假设排序、各规则触发条件、
家族/重复缺陷、缺失证据与 dataGaps、max_hypotheses、确定性。
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

from analysis.config import BundleError, load_diagnosis_rules  # noqa: E402
from analysis.diagnosis import diagnose_equipment  # noqa: E402

DEMO_PATH = _SKILL / "assets" / "demo_bundle.json"
AS_OF = "2026-06-30"


def demo_bundle() -> dict:
    return json.loads(DEMO_PATH.read_text(encoding="utf-8"))


def base_bundle(**overrides) -> dict:
    bundle = {
        "device": {
            "psrId": "PSR-TEST-0002",
            "assetId": "AST-TEST-0002",
            "name": "诊断测试主变",
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
        "hazards": [],
        "faults": [],
        "tests": [],
        "load": {"ratedCapacityMVA": 100, "currentLoadMVA": 50, "openCapacityMVA": 20, "loadRate": 50.0},
        "patrolRecords": [],
    }
    bundle.update(overrides)
    return bundle


def days_before(day: int) -> str:
    return (date.fromisoformat(AS_OF) - timedelta(days=day)).isoformat()


def rule_ids(result: dict) -> list[str]:
    return [item["ruleId"] for item in result["hypotheses"]]


class RuleLibraryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.library = load_diagnosis_rules()

    def test_at_least_ten_rules(self) -> None:
        rules = self.library["rules"]
        self.assertGreaterEqual(len(rules), 10)

    def test_rule_fields_complete(self) -> None:
        ids = set()
        for rule in self.library["rules"]:
            with self.subTest(rule=rule.get("ruleId")):
                self.assertTrue(rule.get("ruleId"))
                self.assertNotIn(rule["ruleId"], ids)
                ids.add(rule["ruleId"])
                self.assertTrue(rule.get("name"))
                self.assertGreaterEqual(float(rule["score"]), 0.0)
                self.assertLessEqual(float(rule["score"]), 1.0)
                self.assertTrue(rule.get("conditions"))
                self.assertTrue(rule.get("suggestions"))
                self.assertTrue(rule.get("knowledgeQueries"))
                self.assertTrue(rule.get("missingEvidence"))

    def test_required_rule_topics_present(self) -> None:
        names = "".join(rule["name"] for rule in self.library["rules"])
        for keyword in ("套管", "机构箱", "分接开关", "冷却", "家族", "重复", "安装", "保护", "接头", "老化"):
            self.assertIn(keyword, names)


class DemoDiagnosisTest(unittest.TestCase):
    def setUp(self) -> None:
        self.result = diagnose_equipment(demo_bundle())

    def test_top_hypothesis_is_bushing_moisture(self) -> None:
        hypotheses = self.result["hypotheses"]
        self.assertTrue(hypotheses)
        self.assertEqual(hypotheses[0]["ruleId"], "DIAG-BUSHING-MOISTURE")
        self.assertIn("套管", hypotheses[0]["name"])

    def test_hypotheses_sorted_by_score(self) -> None:
        scores = [item["score"] for item in self.result["hypotheses"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_demo_hypotheses_include_repeat_and_protection(self) -> None:
        ids = rule_ids(self.result)
        self.assertIn("DIAG-REPEAT-DEFECT", ids)
        self.assertIn("DIAG-PROTECTION-MISOP", ids)

    def test_hypothesis_shape(self) -> None:
        for hypothesis in self.result["hypotheses"]:
            self.assertTrue(hypothesis["ruleId"])
            self.assertGreaterEqual(hypothesis["score"], 0.0)
            self.assertLessEqual(hypothesis["score"], 1.0)
            self.assertGreaterEqual(hypothesis["confidence"], 0.30)
            self.assertLessEqual(hypothesis["confidence"], 0.95)
            self.assertTrue(hypothesis["evidence"])
            for evidence in hypothesis["evidence"]:
                self.assertEqual(
                    set(evidence), {"ruleId", "dimension", "reason", "source", "data"}
                )
                self.assertTrue(evidence["source"])
                self.assertRegex(evidence["source"][0], r"^pgp-\d{3}-\d{4}-\d{5}$")
            self.assertTrue(hypothesis["suggestions"])
            self.assertTrue(hypothesis["knowledgeQueries"])
            self.assertIn("missingEvidence", hypothesis)

    def test_evidence_deduped_by_record(self) -> None:
        evidence = self.result["hypotheses"][0]["evidence"]
        keys = [
            (item["data"].get("scope"), item["data"].get("recordId"))
            for item in evidence
            if item["data"].get("recordId") is not None
        ]
        self.assertEqual(len(keys), len(set(keys)), "同一记录被重复计入证据链")

    def test_patterns_attached(self) -> None:
        patterns = self.result["patterns"]
        self.assertEqual(patterns["summary"]["duplicateClusterCount"], 1)
        self.assertEqual(patterns["summary"]["familyClusterCount"], 0)
        self.assertTrue(patterns["duplicateClusters"])

    def test_missing_evidence_and_data_gaps(self) -> None:
        self.assertTrue(self.result["missingEvidence"])
        self.assertIn("套管", "".join(self.result["missingEvidence"]))
        self.assertIsInstance(self.result["dataGaps"], list)

    def test_max_hypotheses_respected(self) -> None:
        limited = diagnose_equipment(demo_bundle(), max_hypotheses=1)
        self.assertEqual(len(limited["hypotheses"]), 1)
        self.assertEqual(limited["hypotheses"][0]["ruleId"], "DIAG-BUSHING-MOISTURE")

    def test_determinism(self) -> None:
        self.assertEqual(self.result, diagnose_equipment(demo_bundle()))


class RuleTriggerTest(unittest.TestCase):
    def test_mech_box_moisture(self) -> None:
        bundle = base_bundle(
            defects=[
                {
                    "defectId": "M1",
                    "level": "严重",
                    "status": "待处理",
                    "discoverTime": days_before(3),
                    "part": "机构箱",
                    "desc": "机构箱内受潮凝露，二次回路端子锈蚀",
                }
            ]
        )
        self.assertIn("DIAG-MECH-BOX-MOISTURE", rule_ids(diagnose_equipment(bundle, as_of=AS_OF)))

    def test_oltc_abnormal(self) -> None:
        bundle = base_bundle(
            tests=[
                {
                    "recordId": "T-OLTC",
                    "testType": "有载分接开关检查",
                    "testDate": days_before(30),
                    "result": "异常",
                    "dataSummary": "有载分接开关切换卡涩，油质异常",
                }
            ]
        )
        self.assertIn("DIAG-OLTC", rule_ids(diagnose_equipment(bundle, as_of=AS_OF)))

    def test_cooling_overload(self) -> None:
        bundle = base_bundle(
            load={"ratedCapacityMVA": 100, "currentLoadMVA": 95, "openCapacityMVA": 2, "loadRate": 95.0},
            defects=[
                {
                    "defectId": "L1",
                    "level": "一般",
                    "status": "待处理",
                    "discoverTime": days_before(2),
                    "part": "冷却器",
                    "desc": "冷却器风扇异响，油温偏高",
                }
            ],
        )
        self.assertIn("DIAG-COOLING-OVERLOAD", rule_ids(diagnose_equipment(bundle, as_of=AS_OF)))

    def test_insulation_aging(self) -> None:
        bundle = base_bundle(
            device={**base_bundle()["device"], "commissioningDate": "2000-01-01"},
            tests=[
                {
                    "recordId": "T-AGE",
                    "testDate": days_before(100),
                    "result": "异常",
                    "dataSummary": "绝缘电阻下降，介损超标",
                }
            ],
        )
        self.assertIn("DIAG-INSULATION-AGING", rule_ids(diagnose_equipment(bundle, as_of=AS_OF)))

    def test_install_quality(self) -> None:
        bundle = base_bundle(
            device={**base_bundle()["device"], "commissioningDate": "2026-03-01"},
            defects=[
                {"defectId": "I1", "level": "一般", "status": "待处理", "discoverTime": days_before(5), "part": "本体"}
            ],
        )
        self.assertIn("DIAG-INSTALL-QUALITY", rule_ids(diagnose_equipment(bundle, as_of=AS_OF)))

    def test_joint_overheat(self) -> None:
        bundle = base_bundle(
            patrolRecords=[
                {
                    "recordId": "P1",
                    "patrolTime": days_before(10),
                    "result": "发现异常",
                    "abnormalities": ["引线接头红外测温过热"],
                }
            ]
        )
        self.assertIn("DIAG-JOINT-OVERHEAT", rule_ids(diagnose_equipment(bundle, as_of=AS_OF)))

    def test_protection_action(self) -> None:
        bundle = base_bundle(
            faults=[
                {
                    "faultId": "F1",
                    "time": days_before(20),
                    "protectionAction": "差动保护动作",
                    "cause": "区外故障",
                }
            ],
            tests=[
                {"recordId": "T1", "testDate": days_before(15), "result": "不合格", "dataSummary": "保护装置校验不合格"}
            ],
        )
        self.assertIn("DIAG-PROTECTION-MISOP", rule_ids(diagnose_equipment(bundle, as_of=AS_OF)))

    def test_repeat_defect(self) -> None:
        bundle = base_bundle(
            defects=[
                {"defectId": "R1", "level": "一般", "status": "已消除", "discoverTime": days_before(100), "part": "本体"},
                {"defectId": "R2", "level": "一般", "status": "待处理", "discoverTime": days_before(10), "part": "本体"},
            ]
        )
        self.assertIn("DIAG-REPEAT-DEFECT", rule_ids(diagnose_equipment(bundle, as_of=AS_OF)))

    def test_family_defect(self) -> None:
        defects = []
        for index, name in enumerate(("1号主变", "2号主变", "3号主变"), start=1):
            defects.append(
                {
                    "defectId": f"FAM-{index}",
                    "deviceName": name,
                    "model": "SSZ11-180000/220",
                    "manufacturer": "特变电工",
                    "level": "一般",
                    "status": "已消除",
                    "discoverTime": days_before(30 + index),
                    "part": "套管",
                    "desc": "套管渗油",
                }
            )
        bundle = base_bundle(defects=defects)
        result = diagnose_equipment(bundle, as_of=AS_OF)
        self.assertIn("DIAG-FAMILY-DEFECT", rule_ids(result))
        self.assertEqual(result["patterns"]["summary"]["familyClusterCount"], 1)
        self.assertEqual(result["patterns"]["familyClusters"][0]["deviceCount"], 3)

    def test_ledger_incomplete(self) -> None:
        bundle = base_bundle(device={"name": "缺台账主变"})
        self.assertIn("DIAG-LEDGER-INCOMPLETE", rule_ids(diagnose_equipment(bundle, as_of=AS_OF)))

    def test_test_gap(self) -> None:
        bundle = base_bundle(tests=[])
        self.assertIn("DIAG-TEST-GAP", rule_ids(diagnose_equipment(bundle, as_of=AS_OF)))


class DiagnosisGapTest(unittest.TestCase):
    def test_no_evidence_returns_empty_hypotheses_and_gap(self) -> None:
        # 数据齐全但无任何风险信号：不应命中规则，并给出「证据不足」缺口
        bundle = base_bundle(
            tests=[{"recordId": "T-OK", "testDate": days_before(60), "result": "合格"}]
        )
        result = diagnose_equipment(bundle, as_of=AS_OF)
        self.assertEqual(result["hypotheses"], [])
        reasons = "".join(item["reason"] for item in result["dataGaps"])
        self.assertIn("证据不足", reasons)

    def test_missing_sections_marked_in_missing_evidence(self) -> None:
        bundle = {"device": {"name": "仅台账主变"}}
        result = diagnose_equipment(bundle)
        joined = "".join(result["missingEvidence"])
        for section in ("defects", "faults", "tests", "load"):
            self.assertIn(section, joined)

    def test_invalid_bundle_raises(self) -> None:
        with self.assertRaises(BundleError):
            diagnose_equipment({"device": {}})


if __name__ == "__main__":
    unittest.main()
