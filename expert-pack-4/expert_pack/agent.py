"""The episode loop: propose candidates, shape them with memory, execute, learn.

This module is the assembly point of the JitRL streams:

* inference stream  -> ``_propose`` + ``policy.decide`` on every step;
* memory stream     -> ``_evaluate`` + ``_returns`` + ``store.write_episode``
  after the episode ends.

It is deliberately thin: every replaceable behaviour lives behind a slot
(model, tools, skills, store, retriever, abstractor, policy, evaluator).
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from expert_pack.contracts import (
    Candidate,
    EpisodeRecord,
    EpisodeResult,
    Evaluation,
    ModelBackend,
    ModelMessage,
    Neighbor,
    Observation,
    PolicyDecision,
    Skill,
    SkillContext,
    SkillResult,
    State,
    StepRecord,
    Task,
    ToolProvider,
    ToolResult,
    Trajectory,
    Transition,
    answers_match,
    check_contract,
)
from expert_pack.errors import ContractError, ModelError, ToolError
from expert_pack.jsonutil import as_object

log = logging.getLogger("expert_pack.agent")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class AgentConfig:
    max_steps: int = 8
    temperature: float = 0.0
    seed: int | None = None
    memory_context: bool = True
    memory_context_k: int = 3
    max_candidates: int = 5
    max_consecutive_errors: int = 3
    write_memory: bool = True
    repair_attempts: int = 1
    memory_actions: bool = True
    memory_action_limit: int = 3
    #: Memory gating (0 disables each check). Prevents strong-model negative
    #: transfer when evidence is too sparse/similarity is low/returns disagree.
    memory_min_neighbors: int = 0
    memory_min_similarity: float = 0.0
    memory_max_return_std: float = 0.0
    #: When a task carries ``context["suggestedActions"]``, drop candidates
    #: outside that small set (plus "answer"). This turns a soft hint into a
    #: strong candidate-generation constraint for high-ambiguity domains.
    enforce_action_hints: bool = False
    max_answer_chars: int = 400
    max_prompt_observation_chars: int = 500


_SYSTEM = """You are the policy head of expert-pack, a tool-using agent.
Your job is to choose the next action from a finite list, not to write prose.

At every step:
1. Read the task, the current observation, recent steps and any activated skills.
2. Use JIT MEMORY (retrieved past situations with discounted returns) as evidence
   about which actions were valuable in similar situations, not as text to copy.
3. Propose 1-3 concrete candidate actions. A candidate that is already in memory
   is handled by the runtime; you only need to propose what you believe in.
4. Set confidence as your prior belief BEFORE memory evidence. The runtime adds
   the memory-derived advantage to it.
5. When the task asks for a comparison (highest / lowest / maximum / minimum /
   threshold / whether X is greater/lower than Y), you MUST:
   a) retrieve every relevant candidate record first (do not answer after seeing
      only one row);
   b) compare their key fields explicitly;
   c) only then answer. Never guess from a single row.

Return ONLY a JSON object:
{"thought": "one sentence",
 "candidates": [{"action": "<one of AVAILABLE ACTIONS>",
                 "arguments": {..},
                 "confidence": 0.0-1.0,
                 "why": "short reason"}]}

Rules:
- Never invent actions: the "action" value must exactly match an AVAILABLE ACTION id.
- Use {"answer": "..."} as the arguments of the answer action when you are ready.
- Fewer, better candidates beat a long list. Maximum 3.
- If an observation reports an error, change strategy instead of repeating it.
"""


@dataclass
class _Proposal:
    candidates: list[Candidate] = field(default_factory=list)
    thought: str = ""
    errors: list[str] = field(default_factory=list)
    raw_text: str = ""
    usage: dict[str, Any] = field(default_factory=dict)


class ExpertAgent:
    """One agent over one task; ``solve`` is the whole public surface."""

    def __init__(
        self,
        *,
        model: ModelBackend,
        tools: Sequence[ToolProvider],
        skills: Sequence[Skill],
        store,
        retriever,
        abstractor,
        policy,
        evaluator,
        config: AgentConfig | None = None,
        run_id: str = "run",
    ) -> None:
        self._check(model, "ModelBackend")
        self._check(retriever, "Retriever")
        self._check(abstractor, "StateAbstractor")
        self._check(policy, "PolicyShaper")
        self._check(evaluator, "Evaluator")
        self._check(store, "ExperienceStore")
        self.model = model
        self.store = store
        self.retriever = retriever
        self.abstractor = abstractor
        self.policy = policy
        self.evaluator = evaluator
        self.config = config or AgentConfig()
        self.run_id = run_id
        self._providers: dict[str, ToolProvider] = {}
        self._tools: dict[str, tuple[ToolProvider, Any]] = {}
        self._skills: dict[str, Skill] = {}
        self._catalog: dict[str, dict[str, Any]] = {}
        self._index_components(tools, skills)
        self._episode_seq = 0

    # -- wiring ------------------------------------------------------------ #

    @staticmethod
    def _check(obj: Any, contract: str) -> None:
        problems = check_contract(contract, obj)
        if problems:
            raise ContractError(f"{contract} binding is invalid: {', '.join(problems)}")

    def _index_components(self, tools: Sequence[ToolProvider], skills: Sequence[Skill]) -> None:
        for provider in tools:
            self._check(provider, "ToolProvider")
            if provider.name in self._providers:
                raise ContractError(f"duplicate tool provider name {provider.name!r}")
            self._providers[provider.name] = provider
            for spec in provider.list_tools():
                tool_id = spec.action_id
                if tool_id in self._tools:
                    raise ContractError(f"duplicate tool action id {tool_id!r}")
                self._tools[tool_id] = (provider, spec)
                self._catalog[tool_id] = {
                    "kind": "tool",
                    "name": spec.name,
                    "description": spec.description,
                    "schema": dict(spec.input_schema or {}),
                    "provider": provider.name,
                    "provider_obj": provider,
                }
        for skill in skills:
            self._check(skill, "Skill")
            name = skill.spec.name
            if name in self._skills:
                raise ContractError(f"duplicate skill name {name!r}")
            self._skills[name] = skill
            self._catalog[skill.spec.action_id] = {
                "kind": "skill",
                "name": name,
                "description": skill.spec.description,
                "schema": {},
                "skill_obj": skill,
            }
        self._catalog["answer"] = {
            "kind": "answer",
            "name": "answer",
            "description": "Finish the task with the final answer.",
            "schema": {"type": "object", "required": ["answer"]},
        }

    def available_actions(self) -> list[dict[str, Any]]:
        return [
            {
                "action_id": action_id,
                "kind": meta["kind"],
                "name": meta["name"],
                "description": meta["description"],
                "schema": meta["schema"],
            }
            for action_id, meta in self._catalog.items()
        ]

    # -- public API -------------------------------------------------------- #

    def solve(self, task: Task, *, episode_index: int = 1) -> EpisodeResult:
        if not isinstance(task, Task):
            raise TypeError("solve expects a Task")
        self._episode_seq += 1
        episode_id = f"{self.run_id}:{episode_index:03d}:{task.id}"
        started = utc_now()
        memory_before = dict(self.store.stats())
        max_steps = task.max_steps if task.max_steps > 0 else self.config.max_steps
        observation = Observation("start", "Task received. No action has run yet.", True)
        steps: list[StepRecord] = []
        activated: list[tuple[str, str]] = []
        answer: str | None = None
        previous_action: str | None = None
        consecutive_errors = 0
        usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0}
        diagnostics: dict[str, Any] = {"proposal_errors": [], "invalid_candidates": 0, "neighbors": []}

        for index in range(max_steps):
            state = self.abstractor.abstract(task, observation, index, previous_action)
            neighbors = self._retrieve(state)
            proposal = self._propose(task, state, observation, index, neighbors, activated, steps)
            usage_total = _merge_usage(usage_total, proposal.usage)
            if proposal.errors:
                diagnostics["proposal_errors"].append(proposal.errors)
            candidates = self._augment_with_memory(
                proposal.candidates, neighbors, task, state, previous_action
            )
            decision = self.policy.decide(
                candidates=candidates,
                neighbors=neighbors,
                episode_index=episode_index,
                temperature=self.config.temperature,
            )
            selected = decision.selected
            executed = self._execute(task, state, index, observation, selected)
            observation = executed["observation"]
            pending_skill = self._take_pending_skill()
            if pending_skill is not None:
                activated.append(pending_skill)
            step = StepRecord(
                index=index,
                state=state,
                candidates=candidates,
                selected=selected,
                observation=observation,
                model_text=proposal.raw_text,
                decision=decision,
                usage=proposal.usage,
                error=executed["error"],
            )
            steps.append(step)
            diagnostics["neighbors"].append(
                {
                    "step": index,
                    "count": len(neighbors),
                    "max_similarity": max((n.similarity for n in neighbors), default=0.0),
                    "selected_source": selected.source,
                }
            )
            previous_action = selected.action_id

            if selected.kind == "answer":
                answer = str(selected.arguments.get("answer", "")).strip()[: self.config.max_answer_chars]
                break
            if executed["error"]:
                consecutive_errors += 1
                if consecutive_errors >= self.config.max_consecutive_errors:
                    diagnostics.setdefault("notes", []).append(
                        f"stopped after {consecutive_errors} consecutive failed actions"
                    )
                    break
            else:
                consecutive_errors = 0

        if answer is not None:
            hint = answers_match(task.expect(), answer)
        else:
            hint = False
        if not steps:
            diagnostics.setdefault("notes", []).append("no steps executed")
        trajectory = Trajectory(
            task=task,
            steps=steps,
            answer=answer,
            success_hint=hint,
            started_at=started,
            ended_at=utc_now(),
            usage=usage_total,
            notes=diagnostics.get("notes", []),
        )
        evaluation = self.evaluator.evaluate(trajectory)
        returns = self._returns(evaluation, steps)
        transitions = self._transitions(task, episode_id, steps, returns, evaluation)
        if self.config.write_memory:
            self._write_memory(episode_id, task, steps, transitions, evaluation)
        memory_after = dict(self.store.stats())
        diagnostics["success_hint"] = hint
        diagnostics["evaluation"] = evaluation.evaluator
        return EpisodeResult(
            episode_id=episode_id,
            trajectory=trajectory,
            evaluation=evaluation,
            returns=returns,
            memory_before=memory_before,
            memory_after=memory_after,
            diagnostics=diagnostics,
        )

    # -- inference stream -------------------------------------------------- #

    def _retrieve(self, state: State) -> list[Neighbor]:
        try:
            transitions = self.store.transitions()
        except Exception as exc:  # noqa: BLE001 - memory failure must not kill the task
            log.warning("memory read failed: %s", exc)
            return []
        neighbors = self.retriever.retrieve(
            state,
            transitions,
            k=self._policy_top_k(),
            min_similarity=self._policy_min_similarity(),
        )
        return gate_neighbors(
            neighbors,
            min_neighbors=self.config.memory_min_neighbors,
            min_similarity=self.config.memory_min_similarity,
            max_return_std=self.config.memory_max_return_std,
        )

    def _policy_top_k(self) -> int:
        return int(getattr(getattr(self.policy, "config", None), "top_k", 5))

    def _policy_min_similarity(self) -> float:
        return float(getattr(getattr(self.policy, "config", None), "min_similarity", 0.4))

    def _propose(
        self,
        task: Task,
        state: State,
        observation: Observation,
        index: int,
        neighbors: list[Neighbor],
        activated: list[tuple[str, str]],
        steps: list[StepRecord],
    ) -> _Proposal:
        messages = [
            ModelMessage("system", _SYSTEM),
            ModelMessage("user", self._render_prompt(task, observation, index, neighbors, activated, steps)),
        ]
        attempts = self.config.repair_attempts + 1
        last_text = ""
        errors: list[str] = []
        usage: dict[str, Any] = {}
        for attempt in range(attempts):
            try:
                reply = self.model.complete(
                    messages, temperature=self.config.temperature, max_tokens=700
                )
            except ModelError:
                raise
            except Exception as exc:  # noqa: BLE001 - backend failures become a failed proposal
                raise ModelError(f"model backend failed: {exc}") from exc
            last_text = reply.text
            usage = _merge_usage(usage, reply.usage)
            parsed, parse_errors = self._parse_candidates(reply.text)
            if self.config.enforce_action_hints:
                suggested = task.context.get("suggestedActions")
                if suggested:
                    allowed = set(suggested) | {"answer"}
                    before = len(parsed)
                    parsed = [candidate for candidate in parsed if candidate.action_id in allowed]
                    if len(parsed) != before:
                        parse_errors.append(
                            "candidate filtered: not in task suggested actions "
                            + str(sorted(allowed))
                        )
            if parsed:
                return _Proposal(
                    candidates=parsed,
                    thought="",
                    errors=parse_errors,
                    raw_text=last_text,
                    usage=usage,
                )
            errors = parse_errors or ["no valid candidates"]
            if attempt + 1 < attempts:
                messages = messages + [
                    ModelMessage("assistant", reply.text[:800]),
                    ModelMessage(
                        "user",
                        "Your previous response could not be used: "
                        + "; ".join(errors)
                        + ". Return ONLY the JSON object, with action ids copied exactly "
                        "from AVAILABLE ACTIONS.",
                    ),
                ]
        fallback = Candidate(
            action_id="answer",
            kind="answer",
            name="answer",
            arguments={"answer": last_text.strip()[: self.config.max_answer_chars]},
            base_score=math.log(0.25),
            source="fallback",
            description="fallback after unparseable proposal",
        )
        return _Proposal(
            candidates=[fallback],
            errors=errors + ["fell back to answer"],
            raw_text=last_text,
            usage=usage,
        )

    def _render_prompt(
        self,
        task: Task,
        observation: Observation,
        index: int,
        neighbors: list[Neighbor],
        activated: list[tuple[str, str]],
        steps: list[StepRecord],
    ) -> str:
        actions = self.available_actions()
        lines = [
            f"TASK ID: {task.id}",
            f"GOAL: {task.goal}",
            f"SUCCESS CRITERIA: {task.success_criteria or '(not given)'}",
            f"STEP: {index + 1}/{task.max_steps or self.config.max_steps}",
        ]
        lines.append("")
        lines.append(f"CURRENT OBSERVATION (kind={observation.kind}, ok={observation.ok}):")
        lines.append(observation.text[: self.config.max_prompt_observation_chars])
        plan_hint = task.context.get("planHint")
        if plan_hint:
            lines.append("")
            lines.append("TASK PLAN (follow unless the data contradicts it):")
            lines.append(str(plan_hint))
        suggested = task.context.get("suggestedActions")
        if suggested:
            lines.append("")
            lines.append(
                "SUGGESTED ACTIONS FOR THIS TASK (prefer these; unrelated tools are usually wrong):"
            )
            for action_id in suggested:
                lines.append(f"- {action_id}")
        if steps:
            lines.append("")
            lines.append("RECENT STEPS:")
            for step in steps[-3:]:
                lines.append(
                    f"- {step.selected.display(40)} -> ok={step.observation.ok}: "
                    f"{step.observation.text[:110]!r}"
                )
        if activated:
            lines.append("")
            lines.append("ACTIVATED SKILLS (follow these instructions):")
            for name, instructions in activated[-2:]:
                lines.append(f"[{name}]")
                lines.append(instructions[:1200])
        if self.config.memory_context and neighbors:
            lines.append("")
            lines.append(
                "JIT MEMORY (past similar states; ret is the discounted return that followed):"
            )
            for neighbor in neighbors[: self.config.memory_context_k]:
                transition = neighbor.transition
                lines.append(
                    f"- sim={neighbor.similarity:.2f} ret={transition.ret:+.2f} "
                    f"action={transition.action_id} args={_short_json(transition.arguments)} "
                    f"state={transition.state_text[:130]!r}"
                )
        lines.append("")
        lines.append("AVAILABLE ACTIONS:")
        for action in actions:
            schema = action["schema"] if isinstance(action["schema"], dict) else {}
            required = schema.get("required") if isinstance(schema, dict) else None
            properties = schema.get("properties") if isinstance(schema, dict) else None
            if isinstance(properties, dict) and properties:
                names = []
                for name in sorted(properties):
                    names.append(name + ("*" if isinstance(required, list) and name in required else ""))
                suffix = " | params: " + ", ".join(names)
            elif isinstance(required, list) and required:
                suffix = f" | required={required}"
            else:
                suffix = ""
            lines.append(f"- {action['action_id']} — {action['description'][:90]}{suffix}")
        lines.append("")
        lines.append("* = required. Do not invent parameter names outside 'params'.")
        goal_lower = (task.goal or "").lower()
        compare_markers = (
            "最高", "最低", "最大", "最小", "高于", "低于", "是否低", "是否高",
            "比较", "对比", "top", "highest", "lowest", "max", "min",
        )
        if any(marker in goal_lower for marker in compare_markers):
            lines.append("")
            lines.append("COMPARISON REQUIRED:")
            lines.append(
                "- This task requires a comparison. First retrieve ALL candidate rows with the "
                "appropriate tool (e.g. query_open_capacity / query_station_scale_analysis), "
                "compare their key fields (loadRate / availabilityRate / defectLevel), "
                "and only then answer. Do NOT answer after seeing only one row."
            )
        lines.append("Return the JSON object now.")
        return "\n".join(lines)

    def _parse_candidates(self, text: str) -> tuple[list[Candidate], list[str]]:
        payload = as_object(text)
        if payload is None:
            return [], ["response is not a JSON object"]
        raw = payload.get("candidates")
        if isinstance(raw, dict):
            raw = [raw]
        if not isinstance(raw, list) or not raw:
            return [], ["missing non-empty 'candidates' array"]
        parsed: list[Candidate] = []
        errors: list[str] = []
        seen: dict[str, Candidate] = {}
        for item in raw[: self.config.max_candidates + 2]:
            action_id, arguments, confidence, error = self._validate_item(item)
            if error:
                errors.append(error)
                continue
            assert action_id is not None
            meta = self._catalog[action_id]
            candidate = Candidate(
                action_id=action_id,
                kind=meta["kind"],
                name=meta["name"],
                arguments=arguments,
                base_score=math.log(max(0.001, min(1.0, confidence))),
                source="model",
                description=meta["description"],
            )
            if action_id in seen:
                if candidate.base_score > seen[action_id].base_score:
                    seen[action_id] = candidate
                continue
            seen[action_id] = candidate
            parsed.append(candidate)
            if len(parsed) >= self.config.max_candidates:
                break
        return parsed, errors

    def _validate_item(
        self, item: Any
    ) -> tuple[str | None, dict[str, Any], float, str | None]:
        if isinstance(item, str):
            return item, {}, 0.5, None
        if not isinstance(item, dict):
            return None, {}, 0.0, "candidate is not an object"
        action_id = item.get("action") or item.get("action_id")
        if not isinstance(action_id, str) or action_id not in self._catalog:
            return None, {}, 0.0, f"unknown action {action_id!r}"
        raw_args = item.get("arguments", {})
        if isinstance(raw_args, str):
            try:
                import json

                raw_args = json.loads(raw_args)
            except ValueError:
                return None, {}, 0.0, f"arguments for {action_id} are not JSON"
        if raw_args is None:
            raw_args = {}
        if not isinstance(raw_args, dict):
            return None, {}, 0.0, f"arguments for {action_id} are not an object"
        schema = self._catalog[action_id].get("schema") or {}
        required = schema.get("required") if isinstance(schema, dict) else None
        if isinstance(required, list):
            missing = [key for key in required if key not in raw_args]
            if missing:
                return None, {}, 0.0, f"{action_id} is missing required arguments {missing}"
        properties = schema.get("properties") if isinstance(schema, dict) else None
        if isinstance(properties, dict) and properties:
            unknown = [key for key in raw_args if key not in properties]
            if unknown:
                allowed = sorted(properties)
                return (
                    None,
                    {},
                    0.0,
                    f"{action_id} has unknown arguments {unknown}; allowed: {allowed}",
                )
        try:
            confidence = float(item.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        return action_id, dict(raw_args), confidence, None

    def _augment_with_memory(
        self,
        proposed: list[Candidate],
        neighbors: list[Neighbor],
        task: Task,
        state: State,
        previous_action: str | None,
    ) -> list[Candidate]:
        candidates = list(proposed)
        if not self.config.memory_actions or not neighbors:
            return candidates
        seen = {c.action_id for c in candidates}
        stats: dict[str, list[float]] = {}
        last_args: dict[str, dict[str, Any]] = {}
        for neighbor in neighbors:
            action_id = neighbor.transition.action_id
            if action_id in seen or action_id == "answer":
                continue
            if action_id == previous_action:
                continue  # do not replay the action we just took
            if action_id not in self._catalog:
                continue
            stats.setdefault(action_id, []).append(neighbor.transition.ret)
            last_args.setdefault(action_id, dict(neighbor.transition.arguments))
        ranked = sorted(stats, key=lambda a: sum(stats[a]) / len(stats[a]), reverse=True)
        for action_id in ranked[: self.config.memory_action_limit]:
            arguments = last_args.get(action_id, {})
            if not self._arguments_portable(arguments, task, state):
                continue  # stale argument from another task instance
            meta = self._catalog[action_id]
            candidates.append(
                Candidate(
                    action_id=action_id,
                    kind=meta["kind"],
                    name=meta["name"],
                    arguments=arguments,
                    base_score=0.0,  # Algorithm 1: zero logit for memory-only actions
                    source="memory",
                    description=meta["description"],
                )
            )
        return candidates

    @staticmethod
    def _arguments_portable(arguments: Mapping[str, Any], task: Task, state: State) -> bool:
        """A replayed action may only reuse arguments that still fit this task.

        Argument-free actions are always portable. For the rest, every string
        value must appear in the current task text or state text; otherwise the
        argument belongs to another instance (item ``alpha`` vs ``beta``,
        expression ``17*3`` vs ``42*3``) and replaying it would be wrong.
        """

        if not arguments:
            return True
        haystack = f"{task.goal} {task.success_criteria} {state.text}".lower()
        for value in arguments.values():
            if isinstance(value, str) and value.strip():
                if value.strip().lower() not in haystack:
                    return False
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                if str(value) not in haystack:
                    return False
            elif isinstance(value, (list, dict)):
                return False
        return True

    # -- execution --------------------------------------------------------- #

    def _execute(
        self,
        task: Task,
        state: State,
        index: int,
        observation: Observation,
        selected: Candidate,
    ) -> dict[str, Any]:
        if selected.kind == "answer":
            text = selected.arguments.get("answer", selected.arguments.get("text", ""))
            answer = str(text).strip()[: self.config.max_answer_chars]
            return {
                "observation": Observation("answer", answer, True),
                "error": None,
            }
        if selected.kind == "tool":
            return self._call_tool(selected)
        if selected.kind == "skill":
            return self._call_skill(task, state, index, observation, selected)
        return {
            "observation": Observation("error", f"unsupported action kind {selected.kind}", False),
            "error": f"unsupported action kind {selected.kind}",
        }

    def _call_tool(self, selected: Candidate) -> dict[str, Any]:
        entry = self._tools.get(selected.action_id)
        if entry is None:
            message = f"tool {selected.action_id} is not registered"
            return {"observation": Observation("error", message, False), "error": message}
        provider, spec = entry
        try:
            result: ToolResult = provider.call_tool(spec.name, dict(selected.arguments))
        except ToolError as exc:
            return {
                "observation": Observation("error", f"tool error: {exc}", False),
                "error": str(exc),
            }
        except Exception as exc:  # noqa: BLE001 - adapters must not crash the loop
            log.warning("tool %s failed: %s", selected.action_id, exc)
            return {
                "observation": Observation("error", f"tool failed: {exc}", False),
                "error": str(exc),
            }
        if not result.ok:
            text = result.error or result.content or "tool failed without a message"
            return {"observation": Observation("tool", text, False), "error": text}
        text = result.content if result.content else "(empty result)"
        return {
            "observation": Observation("tool", text, True, result.data or {}),
            "error": None,
        }

    def _call_skill(
        self,
        task: Task,
        state: State,
        index: int,
        observation: Observation,
        selected: Candidate,
    ) -> dict[str, Any]:
        skill = self._skills.get(selected.name)
        if skill is None:
            message = f"skill {selected.action_id} is not registered"
            return {"observation": Observation("error", message, False), "error": message}
        context = SkillContext(
            task=task, state=state, step_index=index, observation=observation
        )
        try:
            result: SkillResult = skill.run(context, dict(selected.arguments))
        except Exception as exc:  # noqa: BLE001
            log.warning("skill %s failed: %s", selected.action_id, exc)
            return {
                "observation": Observation("error", f"skill failed: {exc}", False),
                "error": str(exc),
            }
        if not result.ok:
            text = result.error or result.content or "skill failed"
            return {"observation": Observation("skill", text, False), "error": text}
        if result.kind == "instructions":
            # The agent loop keeps activated instructions in context; this
            # observation only acknowledges the load.
            setattr(self, "_pending_skill", (skill.spec.name, result.content))
            return {
                "observation": Observation(
                    "skill", f"Loaded instructions for skill {skill.spec.name}.", True
                ),
                "error": None,
            }
        return {
            "observation": Observation("skill", result.content, True, result.data or {}),
            "error": None,
        }

    # -- memory stream ----------------------------------------------------- #

    def _returns(self, evaluation: Evaluation, steps: list[StepRecord]) -> list[float]:
        rewards = list(evaluation.step_rewards)
        if len(rewards) < len(steps):
            rewards.extend([0.0] * (len(steps) - len(rewards)))
        rewards = rewards[: len(steps)]
        gamma = float(getattr(getattr(self.policy, "config", None), "gamma", 0.5))
        returns: list[float] = []
        for t in range(len(steps)):
            total = 0.0
            for u in range(t, len(rewards)):
                total += (gamma ** (u - t)) * rewards[u]
            returns.append(round(total, 6))
        return returns

    def _transitions(
        self,
        task: Task,
        episode_id: str,
        steps: list[StepRecord],
        returns: list[float],
        evaluation: Evaluation,
    ) -> list[Transition]:
        created = utc_now()
        transitions: list[Transition] = []
        for step, ret in zip(steps, returns):
            transitions.append(
                Transition(
                    episode_id=episode_id,
                    task_id=task.id,
                    family=task.family or task.goal[:60],
                    step=step.index,
                    state_key=step.state.key,
                    state_text=step.state.text,
                    tokens=step.state.tokens,
                    action_id=step.selected.action_id,
                    action_name=step.selected.name,
                    arguments=dict(step.selected.arguments),
                    ret=ret,
                    success=evaluation.success,
                    created_at=created,
                    meta={
                        "source": step.selected.source,
                        "ok": step.observation.ok,
                        "obs_kind": step.observation.kind,
                    },
                )
            )
        return transitions

    def _write_memory(
        self,
        episode_id: str,
        task: Task,
        steps: list[StepRecord],
        transitions: list[Transition],
        evaluation: Evaluation,
    ) -> None:
        record = EpisodeRecord(
            episode_id=episode_id,
            task_id=task.id,
            family=task.family or task.goal[:60],
            success=evaluation.success,
            score=evaluation.score,
            steps=len(steps),
            created_at=utc_now(),
            meta={"evaluator": evaluation.evaluator, "rationale": evaluation.rationale[:300]},
        )
        try:
            self.store.write_episode(record, transitions)
        except Exception as exc:  # noqa: BLE001 - learning must not kill the task
            log.warning("memory write failed: %s", exc)

    # -- activation plumbing ----------------------------------------------- #

    def _take_pending_skill(self) -> tuple[str, str] | None:
        pending = getattr(self, "_pending_skill", None)
        if pending:
            self._pending_skill = None
            return pending
        return None


def gate_neighbors(
    neighbors: Sequence[Neighbor],
    *,
    min_neighbors: int = 0,
    min_similarity: float = 0.0,
    max_return_std: float = 0.0,
) -> list[Neighbor]:
    """Filter retrieved neighbours before they influence prompt/policy.

    All checks are opt-in (0 disables one). When any check fails the whole
    neighbourhood is dropped, so the model sees no JIT MEMORY section and the
    policy falls back to the frozen prior. This is the P2-1 guard against
    strong-model negative transfer from sparse or contradictory experience.
    """

    items = list(neighbors)
    if not items:
        return []
    if min_neighbors > 0 and len(items) < min_neighbors:
        return []
    max_similarity = max(neighbor.similarity for neighbor in items)
    if min_similarity > 0 and max_similarity < min_similarity:
        return []
    if max_return_std > 0:
        returns = [neighbor.transition.ret for neighbor in items]
        mean = sum(returns) / len(returns)
        variance = sum((value - mean) ** 2 for value in returns) / len(returns)
        if variance**0.5 > max_return_std:
            return []
    return items


def _merge_usage(left: dict[str, Any], right: Mapping[str, Any] | None) -> dict[str, Any]:
    merged = dict(left)
    if not right:
        return merged
    for key, value in right.items():
        if isinstance(value, (int, float)):
            merged[key] = merged.get(key, 0) + value
    merged["calls"] = merged.get("calls", 0) + 1
    return merged


def _short_json(value: Mapping[str, Any], limit: int = 60) -> str:
    import json

    try:
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError):
        raw = str(value)
    return raw[:limit]
