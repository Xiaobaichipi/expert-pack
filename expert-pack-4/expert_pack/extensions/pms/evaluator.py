"""PMS 问数评测器：确定性判分 + 逐步奖励（JitRL 的信用分配入口）。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from expert_pack.contracts import Evaluation, Trajectory, answers_match

_ID_PATTERN = re.compile(
    r"\b(?:AST|PSR|DF|STA|UTC|TOPO|GEO|RP|FT|RT|PR|HZ)[-][A-Za-z0-9-]{4,}\b"
)


@dataclass(frozen=True)
class PmsEvaluatorConfig:
    step_penalty: float = -0.03
    tool_success_bonus: float = 0.2
    error_penalty: float = -0.5
    repeat_penalty: float = -0.1
    success_bonus: float = 1.0
    failure_penalty: float = -1.0
    hallucination_penalty: float = -0.5
    max_step_reward: float = 1.0


class PmsEvaluator:
    """确定性评测器。

    与 ``HeuristicEvaluator`` 的区别：
    * 成功判定严格优先 ``task.context["expect"]``（模型自评不算数）；
    * 工具成功给正奖励，失败/重复给负奖励；
    * 最后一步答案按成功/失败给 terminal bonus；
    * 不依赖 LLM，适合 P0 的可复现实验。
    """

    name = "pms-deterministic"

    def __init__(self, config: PmsEvaluatorConfig | None = None) -> None:
        self.config = config or PmsEvaluatorConfig()

    def evaluate(self, trajectory: Trajectory) -> Evaluation:
        steps = trajectory.steps
        expected = trajectory.task.expect()
        hint = trajectory.success_hint
        if hint is not None:
            success = bool(hint)
        else:
            matched = answers_match(expected, trajectory.answer_text())
            success = bool(matched)
        rewards: list[float] = []
        previous_action: str | None = None
        previous_args: str | None = None
        for step in steps:
            reward = self.config.step_penalty
            if step.observation.ok:
                reward += self.config.tool_success_bonus
            else:
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
        hallucinated = _hallucinated_ids(trajectory)
        if hallucinated and rewards:
            rewards[-1] += self.config.hallucination_penalty
        rewards = [
            max(-self.config.max_step_reward, min(self.config.max_step_reward, round(value, 6)))
            for value in rewards
        ]
        errors = sum(1 for step in steps if not step.observation.ok)
        rationale = (
            "pms-deterministic: {steps} steps, {errors} failed observations, "
            "success={success}, expected={expected!r}, answer={answer!r}, hallucinated={hallucinated}"
        ).format(
            steps=len(steps),
            errors=errors,
            success=success,
            expected=expected,
            answer=trajectory.answer_text(),
            hallucinated=hallucinated,
        )
        return Evaluation(
            success=success,
            step_rewards=rewards,
            score=1.0 if success else 0.0,
            rationale=rationale,
            evaluator=self.name,
        )


def from_config(**kwargs: Any) -> PmsEvaluator:
    """装配工厂：把 config 字典转成 PmsEvaluator。"""

    return PmsEvaluator(PmsEvaluatorConfig(**kwargs))


def _hallucinated_ids(trajectory: Trajectory) -> list[str]:
    """答案中出现、但所有工具观察里都没出现过的业务 ID。"""

    answer_ids = set(_ID_PATTERN.findall(trajectory.answer_text() or ""))
    if not answer_ids:
        return []
    observed: set[str] = set()
    for step in trajectory.steps:
        if step.selected.kind == "answer" or step.observation.kind == "answer":
            continue
        observed.update(_ID_PATTERN.findall(step.observation.text or ""))
    return sorted(answer_ids - observed)
