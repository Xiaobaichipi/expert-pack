"""Shared test fixtures."""

from __future__ import annotations

from typing import Any, Callable, Mapping

from expert_pack.builtin.safe_math import evaluate, format_number
from expert_pack.contracts import State, ToolResult, ToolSpec, Transition


def make_state(text: str = "obs 42", *, family: str = "fam", obs: str = "tool", ok: bool = True, key: str | None = None, tokens: tuple[str, ...] = ("obs",)) -> State:
    facets = {"family": family, "obs": obs, "ok": "true" if ok else "false"}
    return State(key=key or f"key-{obs}-{ok}-{text}", text=text, tokens=tokens, facets=facets)


def make_transition(
    *,
    state: State | None = None,
    action: str = "tool:x/a",
    args: Mapping[str, Any] | None = None,
    ret: float = 0.0,
    family: str = "fam",
    success: bool = False,
    obs_kind: str = "tool",
    ok: bool = True,
    step: int = 0,
    episode_id: str = "e1",
    task_id: str = "t1",
    created: str = "2026-01-01T00:00:00+00:00",
) -> Transition:
    state = state or make_state(obs=obs_kind, ok=ok)
    return Transition(
        episode_id=episode_id,
        task_id=task_id,
        family=family,
        step=step,
        state_key=state.key,
        state_text=state.text,
        tokens=state.tokens,
        action_id=action,
        action_name=action.split("/")[-1],
        arguments=dict(args or {}),
        ret=ret,
        success=success,
        created_at=created,
        meta={"obs_kind": obs_kind, "ok": ok},
    )


class FakeTools:
    """An in-process ToolProvider with deterministic behaviour."""

    name = "fake"

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._tools = {
            "lookup": (
                "Look up a named fact.",
                {"type": "object", "properties": {"item": {"type": "string"}}, "required": ["item"]},
                self._lookup,
            ),
            "calc": (
                "Evaluate an arithmetic expression.",
                {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]},
                self._calc,
            ),
        }

    def list_tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(provider=self.name, name=name, description=desc, input_schema=schema)
            for name, (desc, schema, _) in self._tools.items()
        ]

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> ToolResult:
        self.calls.append((name, dict(arguments)))
        entry = self._tools.get(name)
        if entry is None:
            return ToolResult(ok=False, content="", error=f"unknown tool {name}")
        return entry[2](dict(arguments))

    def _lookup(self, arguments: dict[str, Any]) -> ToolResult:
        item = str(arguments.get("item", "")).lower()
        data = {"alpha": "42", "beta": "17", "gamma": "3.14"}
        if item in data:
            return ToolResult(ok=True, content=data[item])
        return ToolResult(ok=False, content="", error=f"unknown item {item!r}")

    def _calc(self, arguments: dict[str, Any]) -> ToolResult:
        expression = str(arguments.get("expression", ""))
        if not expression:
            return ToolResult(ok=False, content="", error="calc needs an expression")
        try:
            return ToolResult(ok=True, content=format_number(evaluate(expression)))
        except (SyntaxError, ValueError, TypeError) as exc:
            return ToolResult(ok=False, content="", error=f"cannot evaluate: {exc}")

    def close(self) -> None:
        return None
