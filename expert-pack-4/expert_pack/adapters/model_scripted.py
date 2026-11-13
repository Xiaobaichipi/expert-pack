"""Deterministic model backends for tests and offline demos."""

from __future__ import annotations

from typing import Callable, Sequence

from expert_pack.contracts import ModelMessage, ModelReply
from expert_pack.errors import ModelError


class ScriptedModel:
    """Return queued strings, or delegate to a responder function.

    This is a test seam, not an agent: it lets a test drive the exact proposal
    the policy will shape, which is the only way to unit-test a stochastic
    policy deterministically.
    """

    name = "scripted"

    def __init__(
        self,
        responses: Sequence[str] | Callable[[Sequence[ModelMessage]], str],
        *,
        name: str | None = None,
    ) -> None:
        self._queue = list(responses) if not callable(responses) else None
        self._responder = responses if callable(responses) else None
        self.name = name or "scripted"
        self.calls: list[list[ModelMessage]] = []

    def complete(
        self,
        messages: Sequence[ModelMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> ModelReply:
        self.calls.append(list(messages))
        if self._responder is not None:
            text = self._responder(messages)
        elif self._queue:
            text = self._queue.pop(0)
        else:
            raise ModelError("ScriptedModel ran out of queued responses")
        if not isinstance(text, str):
            raise ModelError(f"ScriptedModel responder returned {type(text).__name__}, not str")
        return ModelReply(text=text, usage={"calls": 1})
