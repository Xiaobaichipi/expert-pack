from __future__ import annotations

import random
import unittest

from expert_pack.contracts import Candidate, Neighbor
from expert_pack.jitrl.advantage import (
    AdvantageConfig,
    adaptive_exploration,
    episode_weight,
    estimate,
    normalize,
)
from tests.helpers import make_transition


def candidate(action: str, base: float = 0.0) -> Candidate:
    return Candidate(
        action_id=action,
        kind="tool",
        name=action.split("/")[-1],
        base_score=base,
    )


def neighbors(*specs: tuple[str, float]) -> list[Neighbor]:
    return [Neighbor(1.0, make_transition(action=action, ret=ret)) for action, ret in specs]


class AdvantageTest(unittest.TestCase):
    def test_no_neighbors_means_no_shaping(self) -> None:
        estimate_ = estimate([], [candidate("tool:a")], rng=random.Random(1))
        self.assertIsNone(estimate_.state_value)
        self.assertEqual(estimate_.normalized, {})
        self.assertEqual(estimate_.exploration_prob, 0.0)

    def test_known_action_uses_mean_return(self) -> None:
        near = neighbors(("tool:a", 0.4), ("tool:a", 0.6), ("tool:b", 0.0))
        estimate_ = estimate(near, [candidate("tool:a"), candidate("tool:b")], rng=random.Random(1))
        self.assertAlmostEqual(estimate_.state_value, (0.4 + 0.6 + 0.0) / 3)
        self.assertAlmostEqual(estimate_.q_values["tool:a"], 0.5)
        self.assertAlmostEqual(estimate_.raw["tool:a"], 0.5 - estimate_.state_value)
        self.assertEqual(estimate_.action_counts, {"tool:a": 2, "tool:b": 1})

    def test_unseen_action_gets_optimistic_bonus_when_lambda_is_one(self) -> None:
        near = neighbors(("tool:a", 0.2))
        config = AdvantageConfig(lambda_explore=1.0, adaptive_exploration=False, alpha=1.0)
        estimate_ = estimate(
            near, [candidate("tool:a"), candidate("tool:new")], rng=random.Random(1), config=config
        )
        self.assertAlmostEqual(estimate_.q_values["tool:new"], 0.2 + 1.0 / 1)
        self.assertGreater(estimate_.raw["tool:new"], estimate_.raw["tool:a"])

    def test_unseen_action_is_neutral_when_lambda_is_zero(self) -> None:
        near = neighbors(("tool:a", 0.2))
        config = AdvantageConfig(lambda_explore=0.0, adaptive_exploration=False)
        estimate_ = estimate(
            near, [candidate("tool:new")], rng=random.Random(1), config=config
        )
        self.assertEqual(estimate_.q_values["tool:new"], 0.0)

    def test_signed_normalization_matches_reference(self) -> None:
        values = {"a": 2.0, "b": -4.0}
        self.assertEqual(normalize(values, "signed"), {"a": 1.0, "b": -2.0})
        self.assertEqual(normalize(values, "max_abs"), {"a": 0.5, "b": -1.0})

    def test_adaptive_exploration_bounds(self) -> None:
        lam, _ = adaptive_exploration({}, AdvantageConfig())
        self.assertEqual(lam, 0.8)
        # One action, four identical returns: perfectly stable, confidence 1.
        lam_stable, reason = adaptive_exploration({"a": [1.0, 1.0, 1.0, 1.0]}, AdvantageConfig())
        self.assertAlmostEqual(lam_stable, 0.5)
        self.assertIn("confidence", reason)
        # Unstable action (high CV) explores more than a stable one.
        lam_unstable, _ = adaptive_exploration({"a": [0.1, 2.0]}, AdvantageConfig())
        self.assertGreater(lam_unstable, lam_stable)

    def test_adaptive_exploration_is_clamped(self) -> None:
        lam_high, _ = adaptive_exploration({"a": [10.0, 10.0, 10.0]}, AdvantageConfig())
        self.assertGreaterEqual(lam_high, 0.05)
        self.assertLessEqual(lam_high, 0.8)

    def test_episode_weight_ramps_to_one_and_a_half(self) -> None:
        self.assertAlmostEqual(episode_weight(1, True), 1.01)
        self.assertEqual(episode_weight(50, True), 1.5)
        self.assertEqual(episode_weight(120, True), 1.5)
        self.assertEqual(episode_weight(1, False), 1.0)

    def test_estimate_is_deterministic_with_seed(self) -> None:
        near = neighbors(("tool:a", 1.0))
        config = AdvantageConfig(lambda_explore=0.5, adaptive_exploration=False)
        first = estimate(
            near, [candidate("tool:a"), candidate("tool:b")], rng=random.Random(5), config=config
        )
        second = estimate(
            near, [candidate("tool:a"), candidate("tool:b")], rng=random.Random(5), config=config
        )
        self.assertEqual(first.q_values, second.q_values)


if __name__ == "__main__":
    unittest.main()
