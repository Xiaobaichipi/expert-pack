from __future__ import annotations

import unittest

from expert_pack.contracts import Observation, Task
from expert_pack.jitrl.state import DefaultAbstractor, normalize_text, tokenize


class StateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.abstractor = DefaultAbstractor()

    def test_numbers_and_ids_are_placeholders(self) -> None:
        left = self.abstractor.abstract(
            Task(id="a", goal="g", family="fam"), Observation("tool", "42"), 0
        )
        right = self.abstractor.abstract(
            Task(id="b", goal="g", family="fam"), Observation("tool", "17"), 0
        )
        self.assertEqual(left.key, right.key)
        self.assertIn("__num__", normalize_text("42"))
        uuid = normalize_text("550e8400-e29b-41d4-a716-446655440000")
        self.assertIn("__id__", uuid)

    def test_ok_flag_distinguishes_states(self) -> None:
        ok = self.abstractor.abstract(
            Task(id="a", goal="g", family="fam"), Observation("tool", "42", True), 0
        )
        failed = self.abstractor.abstract(
            Task(id="a", goal="g", family="fam"), Observation("tool", "42", False), 0
        )
        self.assertNotEqual(ok.key, failed.key)
        self.assertEqual(ok.facets["ok"], "true")
        self.assertEqual(failed.facets["ok"], "false")

    def test_family_separates_transfer(self) -> None:
        one = self.abstractor.abstract(
            Task(id="a", goal="g", family="alpha"), Observation("tool", "42"), 0
        )
        two = self.abstractor.abstract(
            Task(id="b", goal="g", family="beta"), Observation("tool", "42"), 0
        )
        self.assertNotEqual(one.key, two.key)
        self.assertEqual(one.facets["family"], "alpha")

    def test_previous_action_is_part_of_the_state(self) -> None:
        one = self.abstractor.abstract(
            Task(id="a", goal="g", family="fam"), Observation("tool", "42"), 0, "tool:calc"
        )
        two = self.abstractor.abstract(
            Task(id="a", goal="g", family="fam"), Observation("tool", "42"), 0, "tool:lookup"
        )
        self.assertNotEqual(one.key, two.key)

    def test_tokens_include_bigrams(self) -> None:
        tokens = tokenize("alpha beta gamma", 2)
        self.assertIn("alpha", tokens)
        self.assertIn("alpha~beta", tokens)

    def test_chinese_text_yields_character_tokens(self) -> None:
        tokens = tokenize("查询郑州变电站1号主变套管缺陷")
        self.assertIn("查询", tokens)
        self.assertIn("主变", tokens)
        self.assertIn("套管", tokens)
        self.assertIn("__num__", tokens)
        self.assertGreater(len(tokens), 10)

    def test_chinese_numbers_are_placeholders(self) -> None:
        self.assertEqual(normalize_text("1号主变"), "__num__ 号主变")
        self.assertEqual(normalize_text("2号主变"), "__num__ 号主变")


if __name__ == "__main__":
    unittest.main()
