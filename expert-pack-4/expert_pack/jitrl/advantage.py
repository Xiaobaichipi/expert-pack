"""Advantage estimation: V(s), Q(s,a), A(s,a), and the exploration bonus.

Implements Algorithm 1 (steps 2-5) of the JitRL paper, including the two
details that only the reference implementation makes explicit:

* adaptive exploration probability from action stability (mean / coefficient of
  variation / sample count) instead of a fixed lambda;
* signed normalisation (divide by the largest positive advantage when one
  exists) instead of dividing by max absolute advantage;
* an episode weight that ramps from 1.0 to 1.5 over the first 50 episodes, so
  early, noisy memory does not overwhelm the prior.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from expert_pack.contracts import Candidate, Neighbor


@dataclass(frozen=True)
class AdvantageConfig:
    top_k: int = 5
    min_similarity: float = 0.4
    gamma: float = 0.5
    alpha: float = 1.0
    lambda_explore: float = 0.3
    beta: float = 1.0
    adaptive_exploration: bool = True
    exploration_rate: float = 1.0
    normalization: str = "signed"  # "signed" | "max_abs"
    episode_weight: bool = True
    max_memory_actions: int = 3


@dataclass
class AdvantageEstimate:
    state_value: float | None
    exploration_prob: float
    q_values: dict[str, float] = field(default_factory=dict)
    raw: dict[str, float] = field(default_factory=dict)
    normalized: dict[str, float] = field(default_factory=dict)
    action_counts: dict[str, int] = field(default_factory=dict)
    weight: float = 1.0
    notes: list[str] = field(default_factory=list)


def action_returns(neighbors: list[Neighbor]) -> dict[str, list[float]]:
    groups: dict[str, list[float]] = {}
    for neighbor in neighbors:
        groups.setdefault(neighbor.transition.action_id, []).append(neighbor.transition.ret)
    return groups


def adaptive_exploration(groups: dict[str, list[float]], config: AdvantageConfig) -> tuple[float, str]:
    """Return (lambda, reason), following the reference implementation."""

    if not config.adaptive_exploration:
        return config.lambda_explore, "fixed"
    candidates: list[float] = []
    for returns in groups.values():
        if len(returns) < 2:
            continue
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / len(returns)
        std = variance**0.5
        cv = (std / mean) if mean > 0 else float("inf")
        performance = max(0.0, mean)
        stability = 1.0 / (1.0 + cv)
        sample_confidence = max(len(returns) / 4.0, 1.0)
        candidates.append((performance * stability) ** config.exploration_rate * sample_confidence)
    if not candidates:
        return 0.8, "no stable action yet"
    confidence = max(candidates)
    value = 1.0 / (1.0 + confidence)
    return max(0.05, min(0.8, value)), f"confidence={confidence:.3f}"


def normalize(values: dict[str, float], mode: str) -> dict[str, float]:
    if not values:
        return {}
    if mode == "max_abs":
        scale = max(abs(v) for v in values.values())
        return {k: (v / scale if scale else 0.0) for k, v in values.items()}
    positives = [v for v in values.values() if v > 0]
    if positives:
        scale = max(positives)
    else:
        scale = abs(min(values.values()))
    return {k: (v / scale if scale else 0.0) for k, v in values.items()}


def episode_weight(episode_index: int, enabled: bool) -> float:
    if not enabled:
        return 1.0
    # 1-based episode index: 1.0 at episode 1, 1.5 at episode 50 and beyond.
    return min(1.0 + (max(1, episode_index) / 50.0) * 0.5, 1.5)


def estimate(
    neighbors: list[Neighbor],
    candidates: list[Candidate],
    *,
    rng: random.Random,
    episode_index: int = 1,
    config: AdvantageConfig | None = None,
) -> AdvantageEstimate:
    cfg = config or AdvantageConfig()
    groups = action_returns(neighbors)
    counts = {action: len(values) for action, values in groups.items()}
    weight = episode_weight(episode_index, cfg.episode_weight)
    if not neighbors:
        return AdvantageEstimate(
            state_value=None,
            exploration_prob=0.0,
            weight=weight,
            notes=["no neighbours: no memory shaping"],
        )

    state_value = sum(n.transition.ret for n in neighbors) / len(neighbors)
    lam, reason = adaptive_exploration(groups, cfg)
    q_values: dict[str, float] = {}
    raw: dict[str, float] = {}
    N = len(neighbors)
    for candidate in candidates:
        action = candidate.action_id
        if groups.get(action):
            q = sum(groups[action]) / len(groups[action])
        elif rng.random() < lam:
            q = state_value + cfg.alpha / N
        else:
            q = 0.0
        q_values[action] = q
        raw[action] = q - state_value
    normalized = normalize(raw, cfg.normalization)
    return AdvantageEstimate(
        state_value=state_value,
        exploration_prob=lam,
        q_values=q_values,
        raw=raw,
        normalized=normalized,
        action_counts=counts,
        weight=weight,
        notes=[f"lambda={reason}"],
    )
