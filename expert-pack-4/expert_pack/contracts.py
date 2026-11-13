"""The seams of expert-pack.

Every replaceable part of the system implements one of the Protocols below.
``slots.py`` names a contract for each slot and the assembly layer checks that a
bound object actually satisfies it before the agent runs. This module is the
only thing a new adapter must read: keep it dependency-free.

Design rule: interfaces here are small (one or two methods). Behaviour such as
retrieval scoring, advantage normalisation, MCP framing and prompt rendering
lives behind them, so callers -- and tests -- cross one seam.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence

Json = dict[str, Any]


# --------------------------------------------------------------------------- #
# Model
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ModelMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class ModelReply:
    text: str
    usage: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] | None = None


class ModelBackend(Protocol):
    """A chat-completion style backend. No tool-calling API is required."""

    name: str

    def complete(
        self,
        messages: Sequence[ModelMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> ModelReply: ...


# --------------------------------------------------------------------------- #
# Tools (local providers and MCP servers)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ToolSpec:
    provider: str
    name: str
    description: str = ""
    input_schema: Mapping[str, Any] = field(default_factory=dict)

    @property
    def action_id(self) -> str:
        return f"tool:{self.provider}/{self.name}"


@dataclass
class ToolResult:
    ok: bool
    content: str
    data: Json | None = None
    error: str | None = None


class ToolProvider(Protocol):
    name: str

    def list_tools(self) -> Sequence[ToolSpec]: ...

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> ToolResult: ...


# --------------------------------------------------------------------------- #
# Skills
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SkillSpec:
    name: str
    description: str
    when_to_use: str = ""
    instructions: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def action_id(self) -> str:
        return f"skill:{self.name}"


@dataclass
class SkillResult:
    ok: bool
    content: str
    data: Json | None = None
    error: str | None = None
    kind: str = "output"  # "output" (a result) | "instructions" (a manual to load)


@dataclass(frozen=True)
class SkillContext:
    task: "Task"
    state: "State"
    step_index: int
    observation: "Observation"
    workdir: str | None = None


class Skill(Protocol):
    spec: SkillSpec

    def run(self, context: SkillContext, arguments: Mapping[str, Any]) -> SkillResult: ...


# --------------------------------------------------------------------------- #
# States, tasks, decisions
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class State:
    """An abstracted situation used for retrieval and memory keys.

    ``key`` is the exact identity of the abstraction; ``tokens`` are the units
    compared with Jaccard similarity. Two observations that are functionally
    equivalent (same task family, same normalised text) must produce the same
    key, which is what enables cross-task transfer.

    ``facets`` carries the structural coordinates (family, observation kind,
    success flag) so a retriever can reject structurally incompatible
    neighbours before comparing text.
    """

    key: str
    text: str
    tokens: tuple[str, ...] = ()
    facets: Mapping[str, str] = field(default_factory=dict)


@dataclass
class Task:
    id: str
    goal: str
    success_criteria: str = ""
    max_steps: int = 8
    family: str = ""
    context: Json = field(default_factory=dict)

    def expect(self) -> str | None:
        value = self.context.get("expect")
        return None if value is None else str(value)


@dataclass(frozen=True)
class Observation:
    kind: str  # "start" | "tool" | "skill" | "answer" | "error"
    text: str
    ok: bool = True
    data: Json = field(default_factory=dict)


@dataclass(frozen=True)
class Candidate:
    """One action the policy may choose.


    ``base_score`` is the frozen prior in log space (``ln(confidence)`` for a
    model proposal, ``0.0`` for an action only present in memory, as in the
    JitRL algorithm). The policy adds ``beta * advantage`` to it.
    """

    action_id: str
    kind: str  # "tool" | "skill" | "answer"
    name: str
    arguments: Json = field(default_factory=dict)
    base_score: float = 0.0
    source: str = "model"  # "model" | "memory" | "fallback"
    description: str = ""

    def display(self, max_args: int = 60) -> str:
        if not self.arguments:
            return self.action_id
        raw = _compact_json(self.arguments)
        if len(raw) > max_args:
            raw = raw[: max_args - 1] + "…"
        return f"{self.action_id}{raw}"


@dataclass
class ShapedCandidate:
    candidate: Candidate
    q_value: float | None
    raw_advantage: float
    advantage: float  # normalised and episode-weighted
    shaped_score: float


@dataclass
class PolicyDecision:
    shaped: list[ShapedCandidate]
    selected: Candidate
    state_value: float | None
    exploration_prob: float
    temperature: float
    diagnostics: Json = field(default_factory=dict)

    def trace(self) -> str:
        rows = []
        for item in self.shaped:
            q = "n/a" if item.q_value is None else f"{item.q_value:+.2f}"
            rows.append(
                f"{item.candidate.display()}(base={item.candidate.base_score:+.2f},"
                f"q={q},adv={item.advantage:+.3f}->{item.shaped_score:+.2f})"
            )
        return " ".join(rows)


# --------------------------------------------------------------------------- #
# Experience memory
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Transition:
    episode_id: str
    task_id: str
    family: str
    step: int
    state_key: str
    state_text: str
    tokens: tuple[str, ...]
    action_id: str
    action_name: str
    arguments: Json
    ret: float  # discounted return G_t
    success: bool
    created_at: str
    meta: Json = field(default_factory=dict)


@dataclass(frozen=True)
class EpisodeRecord:
    episode_id: str
    task_id: str
    family: str
    success: bool
    score: float
    steps: int
    created_at: str
    meta: Json = field(default_factory=dict)


@dataclass(frozen=True)
class Neighbor:
    similarity: float
    transition: Transition


class ExperienceStore(Protocol):
    path: str

    def write_episode(self, episode: EpisodeRecord, transitions: Sequence[Transition]) -> None: ...

    def transitions(self) -> Sequence[Transition]: ...

    def stats(self) -> Json: ...

    def clear(self) -> None: ...

    def close(self) -> None: ...


class Retriever(Protocol):
    def retrieve(
        self,
        query: State,
        transitions: Sequence[Transition],
        *,
        k: int = 5,
        min_similarity: float = 0.2,
    ) -> list[Neighbor]: ...


class StateAbstractor(Protocol):
    def abstract(
        self,
        task: Task,
        observation: Observation,
        step_index: int,
        previous_action: str | None = None,
    ) -> State: ...


# --------------------------------------------------------------------------- #
# Evaluation and policy shaping
# --------------------------------------------------------------------------- #


@dataclass
class StepRecord:
    index: int
    state: State
    candidates: list[Candidate]
    selected: Candidate
    observation: Observation
    model_text: str = ""
    decision: PolicyDecision | None = None
    usage: Json = field(default_factory=dict)
    error: str | None = None


@dataclass
class Trajectory:
    task: Task
    steps: list[StepRecord] = field(default_factory=list)
    answer: str | None = None
    success_hint: bool | None = None
    started_at: str = ""
    ended_at: str = ""
    usage: Json = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def step_count(self) -> int:
        return len(self.steps)

    def answer_text(self) -> str:
        if self.answer:
            return self.answer
        for step in reversed(self.steps):
            if step.selected.kind == "answer":
                return str(step.selected.arguments.get("answer", ""))
        return ""


@dataclass
class Evaluation:
    success: bool
    step_rewards: list[float]
    score: float
    rationale: str = ""
    evaluator: str = ""


class Evaluator(Protocol):
    name: str

    def evaluate(self, trajectory: Trajectory) -> Evaluation: ...


@dataclass
class EpisodeResult:
    episode_id: str
    trajectory: Trajectory
    evaluation: Evaluation
    returns: list[float]
    memory_before: Json = field(default_factory=dict)
    memory_after: Json = field(default_factory=dict)
    diagnostics: Json = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.evaluation.success

    @property
    def steps(self) -> int:
        return self.trajectory.step_count


class PolicyShaper(Protocol):
    name: str

    def decide(
        self,
        *,
        candidates: Sequence[Candidate],
        neighbors: Sequence[Neighbor],
        episode_index: int,
        temperature: float = 0.0,
    ) -> PolicyDecision: ...


# --------------------------------------------------------------------------- #
# Contract checking: a slot is only "filled" if it really fits
# --------------------------------------------------------------------------- #

CONTRACT_MEMBERS: dict[str, tuple[str, ...]] = {
    "ModelBackend": ("name", "complete"),
    "ToolProvider": ("name", "list_tools", "call_tool"),
    "Skill": ("spec", "run"),
    "ExperienceStore": ("path", "write_episode", "transitions", "stats", "clear", "close"),
    "Retriever": ("retrieve",),
    "StateAbstractor": ("abstract",),
    "Evaluator": ("name", "evaluate"),
    "PolicyShaper": ("name", "decide"),
}


def check_contract(contract: str, obj: Any) -> list[str]:
    """Return a list of human-readable reasons ``obj`` is not a ``contract``.

    An empty list means the object satisfies the structural contract. We
    deliberately check structure (attributes exist and are callable) rather
    than ``isinstance`` so adapters do not need to import a base class.
    """

    members = CONTRACT_MEMBERS.get(contract)
    if members is None:
        return [f"unknown contract {contract!r}"]
    problems: list[str] = []
    for member in members:
        if not hasattr(obj, member):
            problems.append(f"missing attribute {member!r}")
            continue
        value = getattr(obj, member)
        if member in {"name", "path", "spec"}:
            continue
        if not callable(value):
            problems.append(f"{member!r} is not callable")
    return problems


# --------------------------------------------------------------------------- #
# Small shared helpers
# --------------------------------------------------------------------------- #


def action_kind(action_id: str) -> str:
    return action_id.split(":", 1)[0] if ":" in action_id else "unknown"


def softmax(scores: Sequence[float], temperature: float) -> list[float]:
    """Numerically stable softmax. ``temperature <= 0`` is not accepted here."""

    if temperature <= 0:
        raise ValueError("temperature must be positive for softmax")
    if not scores:
        return []
    scaled = [s / temperature for s in scores]
    peak = max(scaled)
    exps = [math.exp(s - peak) for s in scaled]
    total = sum(exps)
    if total <= 0:
        return [1.0 / len(scores)] * len(scores)
    return [e / total for e in exps]


_WS = re.compile(r"\s+")
_NUM = re.compile(r"^-?\d+(?:\.\d+)?$")


def normalize_answer(text: str | None) -> str:
    if text is None:
        return ""
    return _WS.sub(" ", text.strip().lower()).strip(" .,;:!?\"'`")


def answers_match(expected: str | None, actual: str | None) -> bool | None:
    """Compare an expected answer with an actual one.

    Returns ``None`` when no expectation is available, so callers can fall back
    to the evaluator instead of guessing.
    """

    if expected is None:
        return None
    left = normalize_answer(expected)
    right = normalize_answer(actual)
    if not left or not right:
        return False
    if _NUM.match(left) and _NUM.match(right):
        try:
            return float(left) == float(right)
        except ValueError:
            pass
    if right in left or left in right:
        return True
    return False


def _compact_json(value: Any) -> str:
    import json

    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError):
        return str(value)
