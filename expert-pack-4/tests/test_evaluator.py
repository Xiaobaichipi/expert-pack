from __future__ import annotations

import unittest

from expert_pack.adapters.model_scripted import ScriptedModel
from expert_pack.contracts import Candidate, Evaluation, Observation, StepRecord, State, Task, Trajectory
from expert_pack.jitrl.evaluator import (
    FallbackEvaluator,
    HeuristicConfig,
    HeuristicEvaluator,
    LlmEvaluator,
)


def trajectory(
    *observation_ok: bool,
    answer: str | None = "42",
    expect: str | None = "42",
) -> Trajectory:
    steps = [
        StepRecord(
            index=index,
            state=State(key=str(index), text=""),
            candidates=[],
            selected=Candidate(action_id="tool:x/a", kind="tool", name="a"),
            observation=Observation("tool", "", ok),
        )
        for index, ok in enumerate(observation_ok)
    ]
    context = {} if expect is None else {"expect": expect}
    return Trajectory(task=Task(id="t", goal="g", context=context), steps=steps, answer=answer)


class HeuristicTest(unittest.TestCase):
    def setUp(self) -> None:
        self.evaluator = HeuristicEvaluator()

    def test_success_from_expected_answer(self) -> None:
        result = self.evaluator.evaluate(trajectory(True, True))
        self.assertTrue(result.success)
        self.assertEqual(result.step_rewards[0], -0.03)

    def test_wrong_answer_fails_and_punishes_last_step(self) -> None:
        steps = [
            StepRecord(
                index=0,
                state=State(key="0", text=""),
                candidates=[],
                selected=Candidate(action_id="tool:x/a", kind="tool", name="a"),
                observation=Observation("tool", ""),
            ),
            StepRecord(
                index=1,
                state=State(key="1", text=""),
                candidates=[],
                selected=Candidate(
                    action_id="answer", kind="answer", name="answer", arguments={"answer": "7"}
                ),
                observation=Observation("answer", "7"),
            ),
        ]
        trajectory_ = Trajectory(
            task=Task(id="t", goal="g", context={"expect": "42"}), steps=steps, answer="7"
        )
        result = self.evaluator.evaluate(trajectory_)
        self.assertFalse(result.success)
        # -0.03 step penalty -1.0 failure penalty, clamped to the [-1, 1] range.
        self.assertAlmostEqual(result.step_rewards[-1], -1.0)

    def test_failed_observation_is_penalized(self) -> None:
        result = self.evaluator.evaluate(trajectory(False, True))
        self.assertAlmostEqual(result.step_rewards[0], -0.53)

    def test_repeated_action_is_penalized(self) -> None:
        steps = [
            StepRecord(
                index=0,
                state=State(key="0", text=""),
                candidates=[],
                selected=Candidate(action_id="tool:x/a", kind="tool", name="a", arguments={"k": 1}),
                observation=Observation("tool", ""),
            ),
            StepRecord(
                index=1,
                state=State(key="1", text=""),
                candidates=[],
                selected=Candidate(action_id="tool:x/a", kind="tool", name="a", arguments={"k": 1}),
                observation=Observation("tool", ""),
            ),
        ]
        result = self.evaluator.evaluate(Trajectory(task=Task(id="t", goal="g"), steps=steps))
        self.assertAlmostEqual(result.step_rewards[0], -0.03)
        self.assertAlmostEqual(result.step_rewards[1], -0.13)

    def test_rewards_are_clamped(self) -> None:
        config = HeuristicConfig(step_penalty=-5, error_penalty=-5)
        evaluator = HeuristicEvaluator(config)
        result = evaluator.evaluate(trajectory(False, False, answer=None))
        for reward in result.step_rewards:
            self.assertGreaterEqual(reward, -1.0)
            self.assertLessEqual(reward, 1.0)


class LlmEvaluatorTest(unittest.TestCase):
    def test_valid_response(self) -> None:
        model = ScriptedModel(
            ['{"success": true, "step_rewards": [0.2, 0.8], "rationale": "good path"}']
        )
        evaluator = LlmEvaluator(model)
        result = evaluator.evaluate(trajectory(True, True))
        self.assertEqual(result.step_rewards, [0.2, 0.8])
        self.assertEqual(result.evaluator, "llm")

    def test_wrong_length_is_an_error(self) -> None:
        model = ScriptedModel(['{"success": true, "step_rewards": [1.0]}'])
        with self.assertRaises(ValueError):
            LlmEvaluator(model).evaluate(trajectory(True, True))

    def test_non_numeric_reward_is_an_error(self) -> None:
        model = ScriptedModel(['{"success": true, "step_rewards": ["bad", "bad"]}'])
        with self.assertRaises(ValueError):
            LlmEvaluator(model).evaluate(trajectory(True, True))

    def test_non_json_is_an_error(self) -> None:
        model = ScriptedModel(["I think it went well"])
        with self.assertRaises(ValueError):
            LlmEvaluator(model).evaluate(trajectory(True, True))

    def test_fallback_uses_heuristic_after_llm_failure(self) -> None:
        evaluator = FallbackEvaluator(
            LlmEvaluator(ScriptedModel(["not json at all"])), HeuristicEvaluator()
        )
        result = evaluator.evaluate(trajectory(True, True))
        self.assertTrue(result.success)
        self.assertIn("fallback", result.rationale)
        self.assertEqual(result.evaluator, "llm->heuristic")

    def test_expected_answer_wins_over_llm_success_flag(self) -> None:
        model = ScriptedModel(['{"success": true, "step_rewards": [0.5, 0.5]}'])
        result = LlmEvaluator(model).evaluate(trajectory(True, True, answer="7", expect="42"))
        self.assertFalse(result.success)


if __name__ == "__main__":
    unittest.main()
