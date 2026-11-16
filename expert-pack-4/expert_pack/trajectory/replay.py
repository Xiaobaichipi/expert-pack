"""在已记录的轨迹树上做反事实 replay（Dream-RSI 的轻量版）。

当前实现是**固定后续策略**的 branch replay：
1. 选中一个历史 step 的“未选候选”；
2. 从该 step 的父 observation 出发，执行这个候选；
3. 之后沿用原轨迹后续的 selected actions（固定策略）；
4. 用同一个评测器重新判分，成功则把分支写回 JitRL 记忆（带 source=replay 标签）。

它不调用大模型，因此可离线、可重复；真正的“dream 出新的后续策略”留给下一步。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from expert_pack.contracts import (
    Candidate,
    EpisodeRecord,
    Observation,
    State,
    StepRecord,
    Task,
    Trajectory,
    Transition,
)
from expert_pack.extensions.pms.evaluator import PmsEvaluator
from expert_pack.trajectory.tree_store import load_records


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class ReplayBranch:
    episode_id: str
    node: dict[str, Any]
    alternative: dict[str, Any]
    parent_node: dict[str, Any] | None


@dataclass
class ReplayOutcome:
    replay_id: str
    episode_id: str
    branch_step: int
    branch_action: str
    original_success: bool
    success: bool
    answer: str
    score: float
    steps: int
    verified: bool
    memory_written: bool
    record: dict[str, Any]


def find_branches(records: Iterable[dict[str, Any]]) -> list[ReplayBranch]:
    nodes = [item for item in records if item.get("type") == "node"]
    by_id = {item["nodeId"]: item for item in nodes}
    branches: list[ReplayBranch] = []
    for node in nodes:
        if node.get("kind") != "step":
            continue
        for alternative in node.get("alternatives") or []:
            branches.append(
                ReplayBranch(
                    episode_id=node["episodeId"],
                    node=node,
                    alternative=alternative,
                    parent_node=by_id.get(node.get("parentId")),
                )
            )
    return branches


def episode_record(records: Sequence[dict[str, Any]], episode_id: str) -> dict[str, Any]:
    for item in records:
        if item.get("type") == "episode" and item.get("episodeId") == episode_id:
            return item
    raise KeyError(f"episode not found: {episode_id}")


def task_from_record(record: dict[str, Any]) -> Task:
    return Task(
        id=str(record.get("taskId", "")),
        goal=str(record.get("goal", "")),
        success_criteria=str(record.get("successCriteria", "")),
        max_steps=8,
        family=str(record.get("family", "")),
        context=dict(record.get("context") or {}),
    )


def _candidate(raw: dict[str, Any]) -> Candidate:
    return Candidate(
        action_id=str(raw.get("actionId", "")),
        kind=str(raw.get("kind", "tool")),
        name=str(raw.get("name", "")),
        arguments=dict(raw.get("arguments") or {}),
        base_score=float(raw.get("baseScore") or 0.0),
        source=str(raw.get("source", "replay")),
        description=str(raw.get("description", "")),
    )


def _state(node: dict[str, Any] | None) -> State:
    raw = (node or {}).get("state") or {}
    return State(
        key=str(raw.get("key", "replay-state")),
        text=str(raw.get("text", "")),
        tokens=tuple(str(token) for token in raw.get("tokens") or ()),
        facets=dict(raw.get("facets") or {}),
    )


def _execute(tool_provider: Any, candidate: Candidate) -> Observation:
    if candidate.kind == "answer" or candidate.action_id == "answer":
        answer = str(candidate.arguments.get("answer", ""))
        return Observation(kind="answer", text=answer, ok=True)
    action = candidate.action_id
    if action.startswith("tool:"):
        action = action[len("tool:") :]
    # action is "pms/query_open_capacity"; the MCP adapter takes the bare tool name
    if "/" in action:
        action = action.split("/", 1)[1]
    result = tool_provider.call_tool(action, dict(candidate.arguments))
    return Observation(
        kind="tool",
        text=str(getattr(result, "content", "") or ""),
        ok=bool(getattr(result, "ok", False)),
        data=dict(getattr(result, "data", {}) or {}),
    )


class TreeReplayer:
    def __init__(self, tool_provider: Any) -> None:
        self.tool_provider = tool_provider

    def replay(
        self,
        records: Sequence[dict[str, Any]],
        branch: ReplayBranch,
        *,
        out_path: str | None = None,
        memory_path: str | None = None,
        write_failed: bool = False,
    ) -> ReplayOutcome:
        episode = episode_record(records, branch.episode_id)
        task = task_from_record(episode)
        nodes = [
            item
            for item in records
            if item.get("type") == "node"
            and item.get("episodeId") == branch.episode_id
            and item.get("kind") == "step"
        ]
        nodes.sort(key=lambda item: int(item.get("step", 0)))
        branch_step = int(branch.node.get("step", 0))

        steps: list[StepRecord] = []
        answer = ""

        def add(candidate: Candidate, state_node: dict[str, Any] | None) -> None:
            nonlocal answer
            observation = _execute(self.tool_provider, candidate)
            step = StepRecord(
                index=len(steps),
                state=_state(state_node),
                candidates=[candidate],
                selected=candidate,
                observation=observation,
            )
            steps.append(step)
            if observation.kind == "answer":
                answer = observation.text

        # 分支点：执行未选候选（用分支节点所属的状态；它不是父节点执行后的状态，
        # 但 tree 里 node.state 就是“做这个动作之前”的状态）
        add(_candidate(branch.alternative), branch.node)
        if not answer:
            # 固定后续策略：沿用原轨迹在该 step 之后实际选择的动作
            for node in nodes:
                if int(node.get("step", 0)) <= branch_step:
                    continue
                selected = node.get("selected") or {}
                if not selected.get("actionId"):
                    continue
                add(_candidate(selected), node)
                if answer:
                    break
        if not answer and episode.get("answer"):
            # 固定后续策略没有 answer 动作时，沿用原轨迹的最终答案
            add(
                Candidate(
                    action_id="answer",
                    kind="answer",
                    name="answer",
                    arguments={"answer": str(episode.get("answer"))},
                    source="replay-fixed-continuation",
                ),
                None,
            )

        trajectory = Trajectory(task=task, steps=steps, answer=answer)
        evaluation = PmsEvaluator().evaluate(trajectory)
        replay_id = f"replay:{uuid.uuid4().hex[:10]}"
        verified = bool(evaluation.success)
        memory_written = False
        if memory_path and (verified or write_failed):
            memory_written = self._write_memory(
                memory_path, replay_id, episode, task, steps, evaluation.success, evaluation.score
            )
        record = {
            "type": "replay",
            "replayId": replay_id,
            "episodeId": branch.episode_id,
            "parentTaskId": episode.get("taskId"),
            "branchStep": branch_step,
            "originalSelected": (branch.node.get("selected") or {}).get("actionId"),
            "alternative": branch.alternative,
            "answer": answer,
            "success": verified,
            "score": evaluation.score,
            "originalSuccess": bool(episode.get("success")),
            "verified": verified,
            "memoryWritten": memory_written,
            "steps": len(steps),
            "createdAt": _now(),
        }
        if out_path:
            path = Path(out_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return ReplayOutcome(
            replay_id=replay_id,
            episode_id=branch.episode_id,
            branch_step=branch_step,
            branch_action=str(branch.alternative.get("actionId", "")),
            original_success=bool(episode.get("success")),
            success=verified,
            answer=answer,
            score=evaluation.score,
            steps=len(steps),
            verified=verified,
            memory_written=memory_written,
            record=record,
        )

    def _write_memory(
        self,
        path: str,
        replay_id: str,
        episode: dict[str, Any],
        task: Task,
        steps: Sequence[StepRecord],
        success: bool,
        score: float,
    ) -> bool:
        from expert_pack.jitrl.memory import SqliteExperienceStore

        store = SqliteExperienceStore(path)
        try:
            transitions = []
            for step in steps:
                state = step.state
                transitions.append(
                    Transition(
                        episode_id=replay_id,
                        task_id=task.id,
                        family=task.family,
                        step=step.index,
                        state_key=state.key,
                        state_text=state.text,
                        tokens=state.tokens,
                        action_id=step.selected.action_id,
                        action_name=step.selected.name,
                        arguments=dict(step.selected.arguments),
                        ret=float(score),
                        success=success,
                        created_at=_now(),
                        meta={
                            "source": "replay",
                            "parentEpisode": episode.get("episodeId"),
                            "verified": success,
                        },
                    )
                )
            store.write_episode(
                EpisodeRecord(
                    episode_id=replay_id,
                    task_id=task.id,
                    family=task.family,
                    success=success,
                    score=float(score),
                    steps=len(steps),
                    created_at=_now(),
                    meta={"source": "replay", "parentEpisode": episode.get("episodeId")},
                ),
                transitions,
            )
            return True
        finally:
            store.close()
