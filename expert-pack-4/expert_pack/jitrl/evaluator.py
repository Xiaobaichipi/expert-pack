"""Episode evaluation: turn a trajectory into step rewards and a success flag.

JitRL needs *dense* credit assignment because it stores a return per step, not
one episodic reward. The paper uses an LLM evaluator; here that is one adapter,
with a deterministic heuristic as both the offline default and the fallback
when an LLM answer is unparseable. The heuristic is honest about being coarse:
it can see tool failures, repetition, and the final answer, not subtle
reasoning quality.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from expert_pack.contracts import (
    Evaluation,
    Evaluator,
    ModelBackend,
    ModelMessage,
    Trajectory,
    answers_match,
)
from expert_pack.jsonutil import as_object

_MAX_STEP_REWARD = 1.0


def _structural_success(trajectory: Trajectory) -> bool:
    return bool(trajectory.answer_text()) and all(step.observation.ok for step in trajectory.steps)


def _decide_success(trajectory: Trajectory, *, fallback: bool) -> bool:
    """Trust an explicit expectation above any evaluator's opinion.

    Order: the agent's own comparison against ``task.context["expect"]``, then
    the evaluator's judgement, then a structural guess. A wrong answer must not
    be rewarded just because the model called it a success.
    """

    hint = trajectory.success_hint
    if hint is not None:
        return bool(hint)
    matched = answers_match(trajectory.task.expect(), trajectory.answer_text())
    if matched is not None:
        return matched
    return bool(fallback)


@dataclass(frozen=True)
class HeuristicConfig:
    step_penalty: float = -0.03
    error_penalty: float = -0.5
    repeat_penalty: float = -0.1
    success_bonus: float = 1.0
    failure_penalty: float = -1.0


class HeuristicEvaluator:
    name = "heuristic"

    def __init__(self, config: HeuristicConfig | None = None) -> None:
        self.config = config or HeuristicConfig()

    def evaluate(self, trajectory: Trajectory) -> Evaluation:
        steps = trajectory.steps
        success = _decide_success(trajectory, fallback=_structural_success(trajectory))
        rewards: list[float] = []
        previous_action: str | None = None
        previous_args: str | None = None
        for step in steps:
            reward = self.config.step_penalty
            if not step.observation.ok:
                reward += self.config.error_penalty
            args = json.dumps(step.selected.arguments, sort_keys=True, ensure_ascii=False)
            if step.selected.action_id == previous_action and args == previous_args:
                reward += self.config.repeat_penalty
            previous_action = step.selected.action_id
            previous_args = args
            rewards.append(reward)
        if rewards:
            last = len(rewards) - 1
            if steps[last].selected.kind == "answer" or steps[last].observation.kind == "answer":
                rewards[last] += self.config.success_bonus if success else self.config.failure_penalty
        rewards = [
            max(-_MAX_STEP_REWARD, min(_MAX_STEP_REWARD, round(r, 6))) for r in rewards
        ]
        errors = sum(1 for s in steps if not s.observation.ok)
        rationale = (
            f"heuristic: {len(steps)} steps, {errors} failed observations, "
            f"{sum(1 for s in steps if s.selected.kind == 'answer')} answer steps, success={success}"
        )
        return Evaluation(
            success=success,
            step_rewards=rewards,
            score=1.0 if success else 0.0,
            rationale=rationale,
            evaluator=self.name,
        )


_SYSTEM = """You are the reflective evaluator of a tool-using agent.
You receive one episode as a numbered list of (action, observation, ok) steps.
Assign each step a reward in [-1, 1] measuring its contribution to the final
outcome, and decide whether the episode succeeded.

Rules:
- reward the retrieval/verification steps that made the final answer possible;
- punish steps that failed, repeated a failed action, or wasted a step;
- give the final answer step the largest positive reward when it is correct;
- return ONLY JSON: {"success": true|false, "step_rewards": [..], "rationale": ".."}
- step_rewards MUST contain exactly one number per step."""


class LlmEvaluator:
    name = "llm"

    def __init__(self, model: ModelBackend, *, temperature: float = 0.0, max_tokens: int | None = 600) -> None:
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def evaluate(self, trajectory: Trajectory) -> Evaluation:
        steps = trajectory.steps
        hint = trajectory.success_hint
        if not steps:
            return Evaluation(
                success=bool(hint),
                step_rewards=[],
                score=1.0 if hint else 0.0,
                rationale="empty trajectory",
                evaluator=self.name,
            )
        lines = [
            f"TASK: {trajectory.task.goal}",
            f"SUCCESS CRITERIA: {trajectory.task.success_criteria or '(not given)'}",
            f"FINAL ANSWER: {trajectory.answer_text() or '(none)'}",
            f"EXPECTED ANSWER: {trajectory.task.expect() or '(unknown)'}",
            "STEPS:",
        ]
        for step in steps:
            lines.append(
                f"{step.index}. action={step.selected.display()} "
                f"observation_kind={step.observation.kind} ok={step.observation.ok} "
                f"observation={step.observation.text[:220]!r}"
            )
        messages = [
            ModelMessage("system", _SYSTEM),
            ModelMessage("user", "\n".join(lines)),
        ]
        reply = self.model.complete(messages, temperature=self.temperature, max_tokens=self.max_tokens)
        payload = as_object(reply.text)
        if payload is None:
            raise ValueError("evaluator did not return a JSON object")
        rewards_raw = payload.get("step_rewards")
        if not isinstance(rewards_raw, list) or len(rewards_raw) != len(steps):
            raise ValueError(
                f"evaluator returned {len(rewards_raw) if isinstance(rewards_raw, list) else 0} rewards"
                f" for {len(steps)} steps"
            )
        rewards = []
        for value in rewards_raw:
            try:
                rewards.append(max(-_MAX_STEP_REWARD, min(_MAX_STEP_REWARD, float(value))))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"non-numeric step reward: {value!r}") from exc
        success = _decide_success(trajectory, fallback=bool(payload.get("success")))
        return Evaluation(
            success=success,
            step_rewards=rewards,
            score=1.0 if success else 0.0,
            rationale=str(payload.get("rationale", ""))[:400],
            evaluator=self.name,
        )


class FallbackEvaluator:
    """Use ``primary`` when it works, ``fallback`` when it raises anything."""

    def __init__(self, primary: Evaluator, fallback: Evaluator) -> None:
        self.primary = primary
        self.fallback = fallback
        self.name = f"{primary.name}->{fallback.name}"

    def evaluate(self, trajectory: Trajectory) -> Evaluation:
        try:
            return self.primary.evaluate(trajectory)
        except Exception as exc:  # noqa: BLE001 - the fallback exists for exactly this
            result = self.fallback.evaluate(trajectory)
            result.rationale = f"fallback after {type(exc).__name__}: {exc}; {result.rationale}"[:500]
            result.evaluator = self.name
            return result
