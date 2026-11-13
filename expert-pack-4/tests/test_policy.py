from __future__ import annotations

import unittest

from expert_pack.contracts import Candidate, Neighbor
from expert_pack.jitrl.advantage import AdvantageConfig
from expert_pack.jitrl.policy import JitrlPolicy
from tests.helpers import make_transition


def candidate(action: str, base: float, kind: str = "tool") -> Candidate:
    return Candidate(action_id=action, kind=kind, name=action.split("/")[-1], base_score=base)


def neighbor(action: str, ret: float, similarity: float = 1.0) -> Neighbor:
    return Neighbor(similarity, make_transition(action=action, ret=ret))


class PolicyTest(unittest.TestCase):
    def test_prior_only_picks_best_base(self) -> None:
        policy = JitrlPolicy(AdvantageConfig())
        decision = policy.decide(
            candidates=[candidate("tool:a", -0.1), candidate("tool:b", -0.9)],
            neighbors=[],
        )
        self.assertEqual(decision.selected.action_id, "tool:a")
        self.assertIsNone(decision.state_value)

    def test_advantage_flips_a_strong_prior(self) -> None:
        # The model strongly prefers calc (base -0.105) over lookup (base -0.92),
        # but memory says lookup returned +0.47 and calc -0.53 at this state.
        policy = JitrlPolicy(AdvantageConfig(min_similarity=0.0, beta=1.0), seed=1)
        near = [neighbor("tool:x/calc", -0.53), neighbor("tool:x/lookup", 0.47)]
        decision = policy.decide(
            candidates=[candidate("tool:x/calc", -0.105), candidate("tool:x/lookup", -0.92)],
            neighbors=near,
        )
        self.assertEqual(decision.selected.action_id, "tool:x/lookup")
        self.assertIsNotNone(decision.state_value)

    def test_beta_zero_disables_shaping(self) -> None:
        policy = JitrlPolicy(AdvantageConfig(min_similarity=0.0, beta=0.0), seed=1)
        near = [neighbor("tool:x/calc", -0.53), neighbor("tool:x/lookup", 0.9)]
        decision = policy.decide(
            candidates=[candidate("tool:x/calc", -0.1), candidate("tool:x/lookup", -0.9)],
            neighbors=near,
        )
        self.assertEqual(decision.selected.action_id, "tool:x/calc")
        for item in decision.shaped:
            self.assertAlmostEqual(item.shaped_score, item.candidate.base_score)

    def test_unseen_action_wins_with_a_full_exploration_bonus(self) -> None:
        policy = JitrlPolicy(
            AdvantageConfig(
                min_similarity=0.0, lambda_explore=1.0, adaptive_exploration=False, alpha=1.0
            ),
            seed=3,
        )
        near = [neighbor("tool:seen", 0.2)]
        decision = policy.decide(
            candidates=[candidate("tool:seen", 0.0), candidate("tool:new", 0.0)],
            neighbors=near,
        )
        self.assertEqual(decision.selected.action_id, "tool:new")

    def test_advantage_is_normalized_then_episode_weighted(self) -> None:
        policy = JitrlPolicy(AdvantageConfig(min_similarity=0.0), seed=4)
        near = [neighbor("tool:a", 1.0), neighbor("tool:b", 0.0)]
        decision = policy.decide(
            candidates=[candidate("tool:a", 0.0), candidate("tool:b", 0.0)],
            neighbors=near,
            episode_index=1,
        )
        advantages = {item.candidate.action_id: item.advantage for item in decision.shaped}
        self.assertAlmostEqual(max(advantages.values()), 1.01)  # weight at episode 1
        self.assertAlmostEqual(min(advantages.values()), -1.01)

    def test_episode_weight_grows_with_experience(self) -> None:
        policy = JitrlPolicy(AdvantageConfig(min_similarity=0.0), seed=4)
        near = [neighbor("tool:a", 1.0), neighbor("tool:b", 0.0)]
        early = policy.decide(
            candidates=[candidate("tool:a", 0.0), candidate("tool:b", 0.0)],
            neighbors=near,
            episode_index=1,
        )
        late = policy.decide(
            candidates=[candidate("tool:a", 0.0), candidate("tool:b", 0.0)],
            neighbors=near,
            episode_index=50,
        )
        self.assertGreater(late.diagnostics["episode_weight"], early.diagnostics["episode_weight"])

    def test_temperature_zero_is_argmax(self) -> None:
        policy = JitrlPolicy(AdvantageConfig(), seed=0)
        decision = policy.decide(
            candidates=[candidate("tool:a", 0.0), candidate("tool:b", -1.0)],
            neighbors=[],
            temperature=0.0,
        )
        self.assertEqual(decision.selected.action_id, "tool:a")

    def test_sampling_can_pick_the_weaker_candidate(self) -> None:
        policy = JitrlPolicy(AdvantageConfig(), seed=99)
        picked = set()
        for _ in range(200):
            decision = policy.decide(
                candidates=[candidate("tool:a", 0.0), candidate("tool:b", -0.05)],
                neighbors=[],
                temperature=1.0,
            )
            picked.add(decision.selected.action_id)
        self.assertIn("tool:b", picked)

    def test_reseed_is_reproducible(self) -> None:
        policy = JitrlPolicy(AdvantageConfig(), seed=1)
        policy.reseed(7)
        first = [
            policy.decide(
                candidates=[candidate("tool:a", 0.0), candidate("tool:b", -0.02)],
                neighbors=[],
                temperature=0.5,
            ).selected.action_id
            for _ in range(10)
        ]
        policy.reseed(7)
        second = [
            policy.decide(
                candidates=[candidate("tool:a", 0.0), candidate("tool:b", -0.02)],
                neighbors=[],
                temperature=0.5,
            ).selected.action_id
            for _ in range(10)
        ]
        self.assertEqual(first, second)

    def test_empty_candidates_is_an_error(self) -> None:
        policy = JitrlPolicy()
        with self.assertRaises(ValueError):
            policy.decide(candidates=[], neighbors=[])


if __name__ == "__main__":
    unittest.main()
