#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PMS 状态抽象测试：中文、意图族、跨实例起始状态。"""

from __future__ import annotations

import unittest

from expert_pack.contracts import Observation, Task
from expert_pack.extensions.pms.state import PmsAbstractor


class PmsStateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.abstractor = PmsAbstractor()

    def test_same_intent_start_states_collide(self) -> None:
        one = self.abstractor.abstract(
            Task(id="t1", goal="查询资产 AST-102-0001 的型号", family="ledger_model"),
            Observation("start", "Task received. No action has run yet.", True),
            0,
        )
        two = self.abstractor.abstract(
            Task(id="t2", goal="查询资产 AST-102-0003 的型号", family="ledger_model"),
            Observation("start", "Task received. No action has run yet.", True),
            0,
        )
        self.assertEqual(one.key, two.key, "同一意图族的起始状态应完全一致")
        self.assertEqual(one.facets["family"], "ledger_model")

    def test_different_intent_does_not_collide(self) -> None:
        ledger = self.abstractor.abstract(
            Task(id="t1", goal="查询型号", family="ledger_model"),
            Observation("start", "Task received.", True),
            0,
        )
        defect = self.abstractor.abstract(
            Task(id="t2", goal="查询缺陷", family="defect_level"),
            Observation("start", "Task received.", True),
            0,
        )
        self.assertNotEqual(ledger.key, defect.key)

    def test_chinese_observation_yields_tokens(self) -> None:
        state = self.abstractor.abstract(
            Task(id="t", goal="查询缺陷", family="defect_level"),
            Observation(
                "tool",
                '{"code":0,"data":{"deviceName":"1号主变","defectLevel":"严重","part":"套管"}}',
                True,
            ),
            1,
        )
        self.assertTrue(state.tokens)
        self.assertTrue(any("主变" in token for token in state.tokens))
        self.assertIn("严重", state.tokens)
        self.assertIn("套管", state.tokens)

    def test_facets_include_intent_and_device_type(self) -> None:
        state = self.abstractor.abstract(
            Task(
                id="t",
                goal="查询型号",
                family="ledger_model",
                context={"intent": "ledger_model", "deviceType": "变压器", "voltageLevel": "220kV"},
            ),
            Observation("start", "Task received.", True),
            0,
        )
        self.assertEqual(state.facets["intent"], "ledger_model")
        self.assertEqual(state.facets["deviceType"], "变压器")
        self.assertEqual(state.facets["voltageLevel"], "220kv")


if __name__ == "__main__":
    unittest.main()
