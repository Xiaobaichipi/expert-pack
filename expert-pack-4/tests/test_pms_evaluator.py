#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PMS 确定性评测器测试。"""

from __future__ import annotations

import unittest

from expert_pack.contracts import Candidate, Observation, State, Task, StepRecord, Trajectory
from expert_pack.extensions.pms.evaluator import PmsEvaluator, PmsEvaluatorConfig


def _step(index: int, action_id: str, kind: str, arguments: dict, text: str, ok: bool = True) -> StepRecord:
    selected = Candidate(
        action_id=action_id,
        kind=kind,
        name=action_id.split("/")[-1],
        arguments=arguments,
    )
    observation = Observation("answer" if kind == "answer" else "tool", text, ok)
    return StepRecord(
        index=index,
        state=State(key=f"k{index}", text=""),
        candidates=[selected],
        selected=selected,
        observation=observation,
    )


class PmsEvaluatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.evaluator = PmsEvaluator()
        self.task = Task(id="t", goal="查型号", family="ledger_model", context={"expect": "SSZ11-180000/220"})

    def test_correct_answer_scores_positive(self) -> None:
        trajectory = Trajectory(
            task=self.task,
            steps=[
                _step(0, "tool:pms/get_asset_by_id", "tool", {"assetId": "AST-102-0001"}, "ok"),
                _step(1, "answer", "answer", {"answer": "SSZ11-180000/220"}, "SSZ11-180000/220"),
            ],
            answer="SSZ11-180000/220",
            success_hint=True,
        )
        result = self.evaluator.evaluate(trajectory)
        self.assertTrue(result.success)
        self.assertEqual(len(result.step_rewards), 2)
        self.assertGreater(result.step_rewards[-1], 0.0)
        self.assertEqual(result.score, 1.0)

    def test_wrong_answer_scores_negative(self) -> None:
        trajectory = Trajectory(
            task=self.task,
            steps=[
                _step(0, "tool:pms/get_psr_by_id", "tool", {"psrId": "PSR-220-0001"}, "ok"),
                _step(1, "answer", "answer", {"answer": "unknown"}, "unknown"),
            ],
            answer="unknown",
            success_hint=False,
        )
        result = self.evaluator.evaluate(trajectory)
        self.assertFalse(result.success)
        self.assertLess(result.step_rewards[-1], 0.0)
        self.assertEqual(result.score, 0.0)

    def test_failed_tool_gets_error_penalty(self) -> None:
        trajectory = Trajectory(
            task=self.task,
            steps=[
                _step(0, "tool:pms/get_asset_by_id", "tool", {"assetId": "AST-102-0001"}, "fail", ok=False),
            ],
            answer=None,
            success_hint=False,
        )
        result = self.evaluator.evaluate(trajectory)
        self.assertFalse(result.success)
        self.assertLess(result.step_rewards[0], -0.3)

    def test_hallucinated_id_gets_extra_penalty(self) -> None:
        evaluator = PmsEvaluator(PmsEvaluatorConfig(max_step_reward=10.0))
        trajectory = Trajectory(
            task=self.task,
            steps=[
                _step(0, "tool:pms/get_asset_by_id", "tool", {"assetId": "AST-102-0001"}, "ok"),
                _step(1, "answer", "answer", {"answer": "AST-999-0001"}, "AST-999-0001"),
            ],
            answer="AST-999-0001",
            success_hint=False,
        )
        result = evaluator.evaluate(trajectory)
        self.assertFalse(result.success)
        self.assertLess(result.step_rewards[-1], -1.0)
        self.assertIn("AST-999-0001", result.rationale)


if __name__ == "__main__":
    unittest.main()
