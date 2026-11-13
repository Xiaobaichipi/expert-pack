"""Slots: the explicit vacancies of the framework.

A slot is a named place in the architecture with a contract. The catalog below
is the *skeleton*: it exists before any skill or MCP server is known, exactly
like an empty pipeline stage. A slot is in one of five states:

===========  ==========================================================
``bound``    an assembly binding resolved and satisfied the contract
``builtin``  no binding; the framework's built-in adapter is used
``open``     optional, nothing bound (a place waiting for an adapter)
``vacant``   required, nothing bound and no usable built-in
``invalid``  something was bound but it broke its contract
===========  ==========================================================

``open`` and ``vacant`` are the two kinds of vacancy the assembly agent fills.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

from expert_pack.contracts import CONTRACT_MEMBERS, check_contract
from expert_pack.errors import SlotError

STATUSES = ("bound", "builtin", "open", "vacant", "invalid")
QUALITIES = ("production", "demo", "stub", "unknown")


@dataclass(frozen=True)
class SlotSpec:
    id: str
    contract: str
    required: bool
    description: str
    hint: str = ""
    multi: bool = False
    builtin: str | None = None
    builtin_quality: str = "production"
    builtin_config: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.contract not in CONTRACT_MEMBERS:
            raise SlotError(f"slot {self.id!r} names unknown contract {self.contract!r}")


DEFAULT_SLOTS: tuple[SlotSpec, ...] = (
    SlotSpec(
        id="model",
        contract="ModelBackend",
        required=True,
        description="The reasoning backend that proposes candidate actions.",
        hint="Bind an OpenAI-compatible endpoint, a local model, or a domain-specific planner.",
        builtin="unbound",
        builtin_quality="stub",
    ),
    SlotSpec(
        id="tools",
        contract="ToolProvider",
        required=False,
        multi=True,
        description="Tool providers: MCP servers or local Python providers.",
        hint='Add {"slot":"tools","type":"mcp_stdio","target":"<name>","config":{...}} per server.',
    ),
    SlotSpec(
        id="skills",
        contract="Skill",
        required=False,
        multi=True,
        description="Skills the agent may select as actions or load as instructions.",
        hint='Bind {"type":"skill_dir","target":"skills"} or a Python module exposing skills.',
    ),
    SlotSpec(
        id="store",
        contract="ExperienceStore",
        required=False,
        description="The non-parametric experience memory (state, action, return).",
        hint="Replace with a vector store or a shared database; the interface is four methods.",
        builtin="sqlite",
        builtin_quality="production",
        builtin_config={"path": ".expert_pack/memory.sqlite3"},
    ),
    SlotSpec(
        id="retriever",
        contract="Retriever",
        required=False,
        description="Finds the neighbourhood N(s) used to estimate V and Q.",
        hint="Replace Jaccard with embeddings; keep exact-key transfer if you can.",
        builtin="jaccard",
    ),
    SlotSpec(
        id="abstractor",
        contract="StateAbstractor",
        required=False,
        description="Maps an observation to a retrievable state (normalisation is the transfer mechanism).",
        hint="Give it task-specific facets so equivalent situations collide.",
        builtin="default",
    ),
    SlotSpec(
        id="policy",
        contract="PolicyShaper",
        required=False,
        description="Turns candidate priors plus advantage estimates into one decision.",
        hint="JitRL is the default; ablate it with a prior-only policy.",
        builtin="jitrl",
        builtin_config={
            "top_k": 5,
            "min_similarity": 0.4,
            "gamma": 0.5,
            "alpha": 1.0,
            "lambda_explore": 0.3,
            "beta": 1.0,
            "normalization": "signed",
        },
    ),
    SlotSpec(
        id="evaluator",
        contract="Evaluator",
        required=False,
        description="Assigns dense step rewards and a success flag after each episode.",
        hint="Bind an LLM evaluator for credit assignment on open tasks.",
        builtin="heuristic",
        builtin_quality="demo",
    ),
)


@dataclass
class Binding:
    slot: str
    kind: str  # builtin | module | path | mcp_stdio | skill_dir
    target: str
    config: dict[str, Any] = field(default_factory=dict)
    quality: str = "unknown"
    source: str = "assembly"


@dataclass
class SlotState:
    spec: SlotSpec
    bindings: list[Binding] = field(default_factory=list)
    value: Any = None
    status: str = "open"
    quality: str = "-"
    problems: list[str] = field(default_factory=list)

    @property
    def slot(self) -> str:
        return self.spec.id

    @property
    def binding_text(self) -> str:
        if not self.bindings:
            if self.spec.builtin:
                return f"builtin:{self.spec.builtin}"
            return "-"
        return ", ".join(f"{b.kind}:{b.target}" for b in self.bindings)

    def as_dict(self) -> dict[str, Any]:
        return {
            "slot": self.spec.id,
            "contract": self.spec.contract,
            "required": self.spec.required,
            "multi": self.spec.multi,
            "status": self.status,
            "quality": self.quality,
            "binding": self.binding_text,
            "description": self.spec.description,
            "hint": self.spec.hint,
            "problems": list(self.problems),
        }


@dataclass
class VacancyReport:
    states: list[SlotState]

    def state(self, slot: str) -> SlotState:
        for state in self.states:
            if state.spec.id == slot:
                return state
        raise SlotError(f"unknown slot {slot!r}")

    @property
    def vacancies(self) -> list[SlotState]:
        return [s for s in self.states if s.status in {"open", "vacant"}]

    def strict_problems(self) -> list[str]:
        problems: list[str] = []
        for state in self.states:
            if state.status in {"vacant", "invalid"}:
                problems.append(f"{state.spec.id}: {state.status}")
            elif state.spec.required and state.quality in {"stub", "unknown"}:
                problems.append(f"{state.spec.id}: required slot holds a {state.quality} binding")
            elif state.spec.required and not state.bindings and state.spec.builtin is None:
                problems.append(f"{state.spec.id}: required slot is not bound")
        return problems

    @property
    def ok(self) -> bool:
        return not self.strict_problems()

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "strict_problems": self.strict_problems(),
            "slots": [state.as_dict() for state in self.states],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.as_dict(), indent=indent, ensure_ascii=False)

    def table(self) -> str:
        headers = ("SLOT", "STATUS", "QUALITY", "REQ", "CONTRACT", "BINDING")
        rows = [
            (
                s.spec.id,
                s.status,
                s.quality,
                "yes" if s.spec.required else "no",
                s.spec.contract,
                s.binding_text,
            )
            for s in self.states
        ]
        widths = [max(len(headers[i]), *(len(r[i]) for r in rows)) for i in range(len(headers))]
        lines = ["  ".join(headers[i].ljust(widths[i]) for i in range(len(headers)))]
        lines.append("  ".join("-" * widths[i] for i in range(len(headers))))
        for row in rows:
            lines.append("  ".join(row[i].ljust(widths[i]) for i in range(len(headers))))
        for state in self.states:
            for problem in state.problems:
                lines.append(f"! {state.spec.id}: {problem}")
        lines.append("")
        lines.append(
            f"{len(self.vacancies)} vacancy(ies); strict {'PASS' if self.ok else 'FAIL'}"
        )
        return "\n".join(lines)


class SlotRegistry:
    """Collects bindings, resolves them, and reports what is still missing."""

    def __init__(self, specs: Iterable[SlotSpec] | None = None) -> None:
        self._specs = list(specs if specs is not None else DEFAULT_SLOTS)
        self._ids = {spec.id for spec in self._specs}
        if len(self._ids) != len(self._specs):
            raise SlotError("slot ids must be unique")
        self._bindings: dict[str, list[Binding]] = {spec.id: [] for spec in self._specs}

    @property
    def specs(self) -> list[SlotSpec]:
        return list(self._specs)

    def spec(self, slot: str) -> SlotSpec:
        for spec in self._specs:
            if spec.id == slot:
                return spec
        raise SlotError(f"unknown slot {slot!r}; known slots: {', '.join(self._ids)}")

    def bind(self, binding: Binding) -> None:
        if binding.slot not in self._ids:
            raise SlotError(f"unknown slot {binding.slot!r}")
        spec = self.spec(binding.slot)
        if not spec.multi and self._bindings[binding.slot]:
            raise SlotError(
                f"slot {binding.slot!r} accepts exactly one binding; "
                f"already bound to {self._bindings[binding.slot][0].target!r}"
            )
        self._bindings[binding.slot].append(binding)

    def describe(self, *, overrides: Mapping[str, Any] | None = None) -> VacancyReport:
        """Report slot status without constructing adapters or touching disk."""

        overrides = overrides or {}
        states: list[SlotState] = []
        for spec in self._specs:
            state = SlotState(spec=spec)
            if spec.id in overrides:
                state.status = "bound"
                state.quality = "production"
                state.bindings = [Binding(spec.id, "override", "runtime", source="override")]
            elif self._bindings[spec.id]:
                state.bindings = list(self._bindings[spec.id])
                state.status = "bound"
                state.quality = state.bindings[0].quality
            elif spec.builtin:
                state.status = "builtin"
                state.quality = spec.builtin_quality
            else:
                state.status = "vacant" if spec.required else "open"
                state.quality = "-"
            states.append(state)
        return VacancyReport(states=states)

    def resolve(
        self,
        resolve_binding: Callable[[Binding, SlotSpec, Mapping[str, Any]], Any],
        resolve_builtin: Callable[[str, Mapping[str, Any], SlotSpec, Mapping[str, Any]], tuple[Any, str]],
        *,
        overrides: Mapping[str, Any] | None = None,
        order: Iterable[str] | None = None,
    ) -> VacancyReport:
        overrides = overrides or {}
        values: dict[str, Any] = {}
        states: dict[str, SlotState] = {}
        for spec in self._specs:
            states[spec.id] = SlotState(spec=spec)

        order_list = list(order or [])
        ordered = [self.spec(slot) for slot in order_list if slot in self._ids]
        ordered += [spec for spec in self._specs if spec.id not in {s.id for s in ordered}]
        for spec in ordered:
            state = states[spec.id]
            if spec.id in overrides:
                state.value = overrides[spec.id]
                state.status = "bound"
                state.quality = "production"
                state.bindings = [Binding(spec.id, "override", "runtime", source="override")]
                values[spec.id] = state.value
                continue
            bindings = self._bindings[spec.id]
            if bindings:
                state.bindings = bindings
                try:
                    resolved = [
                        resolve_binding(binding, spec, values) for binding in bindings
                    ]
                except Exception as exc:  # noqa: BLE001 - reported, not hidden
                    state.status = "invalid"
                    state.quality = bindings[0].quality
                    state.problems.append(str(exc))
                    state.value = None
                    values[spec.id] = None
                    continue
                if spec.multi:
                    merged: list[Any] = []
                    for item in resolved:
                        if isinstance(item, (list, tuple)):
                            merged.extend(item)
                        else:
                            merged.append(item)
                    state.value = merged
                    contract_problems = [
                        f"item {index}: {problem}"
                        for index, item in enumerate(merged)
                        for problem in check_contract(spec.contract, item)
                    ]
                else:
                    state.value = resolved[0]
                    contract_problems = check_contract(spec.contract, resolved[0])
                if contract_problems:
                    state.status = "invalid"
                    state.quality = bindings[0].quality
                    state.problems.extend(contract_problems)
                else:
                    state.status = "bound"
                    state.quality = bindings[0].quality
                values[spec.id] = state.value
                continue
            if spec.builtin:
                try:
                    value, quality = resolve_builtin(spec.builtin, spec.builtin_config, spec, values)
                except Exception as exc:  # noqa: BLE001
                    state.status = "invalid"
                    state.quality = "unknown"
                    state.problems.append(f"builtin {spec.builtin!r} failed: {exc}")
                    state.value = None
                    values[spec.id] = None
                    continue
                state.status = "builtin"
                state.quality = quality
                state.value = value
                values[spec.id] = value
                continue
            state.status = "vacant" if spec.required else "open"
            state.quality = "-"
            state.value = [] if spec.multi else None
            values[spec.id] = [] if spec.multi else None

        return VacancyReport(states=[states[spec.id] for spec in self._specs])
