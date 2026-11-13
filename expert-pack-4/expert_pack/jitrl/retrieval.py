"""Retrieval: find the local neighbourhood N(s) used for value estimation.

The default is the paper's token-overlap idea (Jaccard), with two safety rails
that matter for short, structured agent states:

* an exact state-key fast path (similarity 1.0), because normalisation is what
  makes two task instances land on the same situation;
* structural compatibility: a neighbour must share the task family, the
  observation kind and the success flag before its text is compared at all.
  Without this, boilerplate such as ``family=... | ok=true`` dominates short
  states and an answer-step memory contaminates a tool-step decision.

Vector embeddings are intentionally *not* required: the framework must run on a
fresh machine with no model server, and the ``retriever`` slot is the seam where
an embedding retriever can be dropped in later.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Sequence

from expert_pack.contracts import Neighbor, State, Transition
from expert_pack.jitrl.state import normalize_text


def jaccard(a: Sequence[str], b: Sequence[str]) -> float:
    """Multiset Jaccard over token units (unigrams + n-grams)."""

    counter_a = Counter(a)
    counter_b = Counter(b)
    if not counter_a or not counter_b:
        return 0.0
    inter = sum((counter_a & counter_b).values())
    union = sum((counter_a | counter_b).values())
    return inter / union if union else 0.0


def structurally_compatible(query: State, transition: Transition) -> bool:
    facets = query.facets
    if not facets:
        return True
    family = facets.get("family")
    if family and normalize_text(transition.family) != family:
        return False
    if facets.get("obs") and transition.meta.get("obs_kind") != facets.get("obs"):
        return False
    if facets.get("ok"):
        meta_ok = transition.meta.get("ok")
        if meta_ok is None or str(bool(meta_ok)).lower() != facets.get("ok"):
            return False
    return True


@dataclass(frozen=True)
class RetrievalConfig:
    max_scan: int = 20_000
    """Only the newest N transitions are scanned. Documented, not hidden."""

    exact_boost: float = 1.0
    require_structural_match: bool = True


class JaccardRetriever:
    name = "jaccard"

    def __init__(self, config: RetrievalConfig | None = None) -> None:
        self.config = config or RetrievalConfig()

    def retrieve(
        self,
        query: State,
        transitions: Sequence[Transition],
        *,
        k: int = 5,
        min_similarity: float = 0.4,
    ) -> list[Neighbor]:
        if k <= 0 or not transitions:
            return []
        scanned = transitions[-self.config.max_scan :] if self.config.max_scan > 0 else transitions
        scored: list[tuple[float, int, Transition]] = []
        for index, transition in enumerate(scanned):
            if transition.state_key == query.key:
                similarity = self.config.exact_boost
            else:
                if self.config.require_structural_match and not structurally_compatible(
                    query, transition
                ):
                    continue
                similarity = jaccard(query.tokens, transition.tokens)
            if similarity >= min_similarity:
                scored.append((similarity, index, transition))
        # newest first on ties: index is a stable recency proxy
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [Neighbor(similarity=sim, transition=tr) for sim, _, tr in scored[:k]]
