"""The shaping policy: z' = z + beta * advantage.

JitRL applies its additive update to token logits. A tool-using agent does not
control token logits, so the same closed-form update is applied at the level the
agent *does* choose from: a finite candidate set of actions. ``base_score`` is
the frozen prior in log space (the model's confidence), and the memory-derived
advantage shifts it before a softmax (or argmax at temperature 0).

This is the exact form of Eq. 8 in the paper over discrete candidates. It is
also the only honest place to put the update: we never claim to change weights.
"""

from __future__ import annotations

import random
from dataclasses import replace
from typing import Sequence

from expert_pack.contracts import (
    Candidate,
    Neighbor,
    PolicyDecision,
    ShapedCandidate,
    softmax,
)
from expert_pack.jitrl import advantage as advantage_mod
from expert_pack.jitrl.advantage import AdvantageConfig


class JitrlPolicy:
    name = "jitrl"

    def __init__(self, config: AdvantageConfig | None = None, *, seed: int | None = None) -> None:
        self.config = config or AdvantageConfig()
        self._rng = random.Random(seed)
        self._seed = seed

    def reseed(self, seed: int | None) -> None:
        """Make the policy reproducible when a run-level seed is supplied."""

        self._seed = seed
        self._rng = random.Random(seed)

    def decide(
        self,
        *,
        candidates: Sequence[Candidate],
        neighbors: Sequence[Neighbor],
        episode_index: int = 1,
        temperature: float = 0.0,
    ) -> PolicyDecision:
        if not candidates:
            raise ValueError("the policy needs at least one candidate")
        estimate = advantage_mod.estimate(
            list(neighbors),
            list(candidates),
            rng=self._rng,
            episode_index=episode_index,
            config=self.config,
        )
        shaped: list[ShapedCandidate] = []
        for index, candidate in enumerate(candidates):
            normalized = estimate.normalized.get(candidate.action_id, 0.0)
            effective = normalized * estimate.weight
            shaped_score = candidate.base_score + self.config.beta * effective
            shaped.append(
                ShapedCandidate(
                    candidate=candidate,
                    q_value=estimate.q_values.get(candidate.action_id),
                    raw_advantage=estimate.raw.get(candidate.action_id, 0.0),
                    advantage=effective,
                    shaped_score=shaped_score,
                )
            )
        shaped.sort(key=lambda item: item.shaped_score, reverse=True)
        diagnostics = {
            "state_value": estimate.state_value,
            "exploration_prob": estimate.exploration_prob,
            "episode_weight": estimate.weight,
            "normalization": self.config.normalization,
            "notes": estimate.notes,
            "beta": self.config.beta,
        }
        if temperature <= 0:
            selected = shaped[0].candidate
        else:
            probabilities = softmax([item.shaped_score for item in shaped], temperature)
            chosen = self._rng.choices(range(len(shaped)), weights=probabilities, k=1)[0]
            selected = shaped[chosen].candidate
        return PolicyDecision(
            shaped=shaped,
            selected=selected,
            state_value=estimate.state_value,
            exploration_prob=estimate.exploration_prob,
            temperature=temperature,
            diagnostics=diagnostics,
        )


def with_base(candidate: Candidate, base_score: float, *, source: str | None = None) -> Candidate:
    """Small helper used when the agent derives a candidate from memory."""

    return replace(
        candidate,
        base_score=base_score,
        source=source or candidate.source,
    )
