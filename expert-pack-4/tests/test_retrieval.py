from __future__ import annotations

import unittest

from expert_pack.jitrl.retrieval import JaccardRetriever, jaccard, structurally_compatible
from expert_pack.jitrl.state import tokenize
from tests.helpers import make_state, make_transition


class RetrievalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.retriever = JaccardRetriever()

    def test_jaccard_multiset(self) -> None:
        self.assertAlmostEqual(jaccard(["a", "b"], ["a", "c"]), 1 / 3)
        self.assertEqual(jaccard(["a", "a", "b"], ["a", "a", "b"]), 1.0)
        self.assertEqual(jaccard([], ["a"]), 0.0)

    def test_exact_key_wins(self) -> None:
        query = make_state(key="same", tokens=())
        transitions = [
            make_transition(state=make_state(key="other", tokens=("a", "b")), ret=1.0),
            make_transition(state=make_state(key="same", tokens=()), ret=0.5),
        ]
        neighbors = self.retriever.retrieve(query, transitions, k=2, min_similarity=0.99)
        self.assertEqual(len(neighbors), 1)
        self.assertEqual(neighbors[0].similarity, 1.0)
        self.assertEqual(neighbors[0].transition.ret, 0.5)

    def test_structural_mismatch_is_rejected(self) -> None:
        query = make_state(obs="tool", tokens=("same",))
        answer_state = make_state(obs="answer", tokens=("same",))
        transition = make_transition(state=answer_state, obs_kind="answer")
        self.assertFalse(structurally_compatible(query, transition))
        neighbors = self.retriever.retrieve(query, [transition], k=5, min_similarity=0.0)
        self.assertEqual(neighbors, [])

    def test_order_and_limit(self) -> None:
        query = make_state(key="q", tokens=("a", "b", "c"))
        near = make_transition(state=make_state(key="n", tokens=("a", "b", "c")), ret=1.0)
        far = make_transition(state=make_state(key="f", tokens=("a",)), ret=2.0)
        neighbors = self.retriever.retrieve(query, [far, near], k=1, min_similarity=0.1)
        self.assertEqual(len(neighbors), 1)
        self.assertEqual(neighbors[0].transition, near)

    def test_threshold_filters(self) -> None:
        query = make_state(key="q", tokens=("a", "b", "c", "d"))
        cold = make_transition(state=make_state(key="c", tokens=("x", "y", "z")), ret=1.0)
        self.assertEqual(self.retriever.retrieve(query, [cold], k=5, min_similarity=0.3), [])

    def test_chinese_similar_states_are_retrieved(self) -> None:
        query_text = "查询郑州变电站1号主变套管缺陷"
        near_text = "查询二里岗变电站1号主变套管渗油"
        far_text = "查询郑州变电站停电事件"
        query = make_state(
            text=query_text,
            family="缺陷查询",
            obs="tool",
            tokens=tuple(tokenize(query_text)),
            key="q",
        )
        near = make_transition(
            state=make_state(
                text=near_text,
                family="缺陷查询",
                obs="tool",
                tokens=tuple(tokenize(near_text)),
                key="near",
            ),
            family="缺陷查询",
            ret=1.0,
        )
        far = make_transition(
            state=make_state(
                text=far_text,
                family="缺陷查询",
                obs="tool",
                tokens=tuple(tokenize(far_text)),
                key="far",
            ),
            family="缺陷查询",
            ret=2.0,
        )
        neighbors = self.retriever.retrieve(query, [far, near], k=2, min_similarity=0.4)
        self.assertEqual([item.transition for item in neighbors], [near])
        self.assertGreater(jaccard(query.tokens, near.tokens), 0.4)


if __name__ == "__main__":
    unittest.main()
