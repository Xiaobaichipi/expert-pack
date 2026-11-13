#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P2-1 记忆门控测试。"""

from __future__ import annotations

import unittest

from expert_pack.agent import gate_neighbors
from expert_pack.contracts import Neighbor
from tests.helpers import make_state, make_transition


def _neighbor(similarity: float, ret: float) -> Neighbor:
    state = make_state(key=f"k{similarity}-{ret}", tokens=("a",))
    return Neighbor(similarity=similarity, transition=make_transition(state=state, ret=ret))


class MemoryGateTest(unittest.TestCase):
    def test_empty_signal_is_dropped(self) -> None:
        self.assertEqual(gate_neighbors([]), [])

    def test_min_neighbors(self) -> None:
        neighbors = [_neighbor(0.9, 0.2)]
        self.assertEqual(gate_neighbors(neighbors, min_neighbors=2), [])
        self.assertEqual(gate_neighbors(neighbors, min_neighbors=1), neighbors)

    def test_min_similarity(self) -> None:
        neighbors = [_neighbor(0.5, 0.2), _neighbor(0.55, 0.1)]
        self.assertEqual(gate_neighbors(neighbors, min_similarity=0.8), [])
        self.assertEqual(gate_neighbors(neighbors, min_similarity=0.5), neighbors)

    def test_return_disagreement(self) -> None:
        neighbors = [_neighbor(0.9, -1.0), _neighbor(0.9, 1.0)]
        self.assertEqual(gate_neighbors(neighbors, max_return_std=0.5), [])
        self.assertEqual(gate_neighbors(neighbors, max_return_std=2.0), neighbors)

    def test_zero_values_preserve_p0_behavior(self) -> None:
        neighbors = [_neighbor(0.2, -1.0)]
        self.assertEqual(gate_neighbors(neighbors), neighbors)


if __name__ == "__main__":
    unittest.main()
