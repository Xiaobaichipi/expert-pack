"""PMS 检索器：在 Jaccard 之上支持按意图族设置相似度阈值。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from expert_pack.contracts import Neighbor, State, Transition
from expert_pack.jitrl.retrieval import JaccardRetriever, RetrievalConfig


@dataclass(frozen=True)
class PmsRetrieverConfig:
    default_min_similarity: float = 0.4
    family_min_similarity: dict[str, float] = field(default_factory=dict)
    max_scan: int = 20_000
    exact_boost: float = 1.0
    require_structural_match: bool = True


class PmsRetriever:
    """按 ``query.facets["family"]`` 选择相似度阈值。

    JitRL 的起始状态在同一意图族内是 exact-key（相似度 1.0），因此阈值主要影响
    工具观察之后的状态；按族配置可避免“台账族”和“缺陷族”共用同一阈值。
    """

    name = "pms-jaccard"

    def __init__(self, config: PmsRetrieverConfig | None = None) -> None:
        self.config = config or PmsRetrieverConfig()
        self._base = JaccardRetriever(
            RetrievalConfig(
                max_scan=self.config.max_scan,
                exact_boost=self.config.exact_boost,
                require_structural_match=self.config.require_structural_match,
            )
        )
        self._family_thresholds = {
            str(key): float(value) for key, value in self.config.family_min_similarity.items()
        }

    def retrieve(
        self,
        query: State,
        transitions: Sequence[Transition],
        *,
        k: int = 5,
        min_similarity: float = 0.4,
    ) -> list[Neighbor]:
        family = str(query.facets.get("family", ""))
        threshold = self._family_thresholds.get(family, min_similarity)
        return self._base.retrieve(query, transitions, k=k, min_similarity=threshold)


def from_config(**kwargs: Any) -> PmsRetriever:
    """装配工厂；``family_min_similarity`` 支持 dict 配置。"""

    return PmsRetriever(PmsRetrieverConfig(**kwargs))
