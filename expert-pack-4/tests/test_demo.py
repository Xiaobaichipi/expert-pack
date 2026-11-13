"""Integration: the offline demo proves memory changes a decision.

This is the paper's core claim in miniature: a fixed, non-adaptive planner
fails because it fires an action with no operand evidence; after one episode
the memory-derived advantage lifts the retrieval action above it, and every
later task succeeds. No gradients, no fine-tuning, no API key.
"""

from __future__ import annotations

import unittest

from expert_pack.builtin.demo import run_demo


class DemoIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = run_demo(count=6, seed=7)

    def test_baseline_never_succeeds(self) -> None:
        self.assertEqual(self.report.baseline_rate, 0.0)
        for episode in self.report.baseline:
            self.assertFalse(episode.success)
            self.assertEqual(episode.answer, "0")

    def test_memory_improves_after_the_first_episode(self) -> None:
        self.assertGreaterEqual(self.report.memory_rate, 0.66)
        first, *rest = self.report.memory
        self.assertFalse(first.success)
        self.assertTrue(all(episode.success for episode in rest))

    def test_episode_answers_are_correct(self) -> None:
        for episode in self.report.memory:
            if episode.success:
                self.assertEqual(episode.answer, episode.expected)

    def test_memory_is_written(self) -> None:
        stats = self.report.memory_stats
        self.assertEqual(stats["episodes"], len(self.report.memory))
        self.assertGreater(stats["transitions"], 0)
        self.assertTrue(any(item["action_id"].startswith("tool:") for item in stats["actions"]))

    def test_failing_episode_produced_the_lesson(self) -> None:
        # The failing baseline and the first memory episode both took two steps
        # and both ended on the stub's premature answer.
        self.assertEqual(self.report.baseline[0].steps, 2)
        self.assertIn("answer", self.report.memory[0].decisions[-1])


if __name__ == "__main__":
    unittest.main()
