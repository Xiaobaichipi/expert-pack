"""轨迹树存储：append-only JSONL，保留“所有候选分支”，而不是只记最终动作。

设计原则（对应 Dream-RSI 的 discovery tree）：
* **描述性，不规定性**：不按人类预设的 Skill/意图标签裁剪树；节点只记录实际发生过的
  state / observation / 候选动作 / 分数 / 结果，让树自己长出来；
* **保留分支**：每个 step 的所有候选动作都写入（selected + alternatives），
  未执行的候选就是“可 replay 的分支”；
* **可精确 replay**：observation 存完整原文（不是截断后的 prompt 片段），
  这样以后才能判断“模型当时到底看到了什么”；
* **append-only**：episode/node 记录只追加，派生记忆可以随时重建。
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from expert_pack.contracts import EpisodeResult


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        return _plain(asdict(value))
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _candidate(item: Any) -> dict[str, Any]:
    return {
        "actionId": getattr(item, "action_id", ""),
        "kind": getattr(item, "kind", ""),
        "name": getattr(item, "name", ""),
        "arguments": _plain(getattr(item, "arguments", {})),
        "baseScore": getattr(item, "base_score", 0.0),
        "source": getattr(item, "source", ""),
        "description": getattr(item, "description", ""),
    }


class TrajectoryTreeStore:
    """把 EpisodeResult 写成可 replay 的树形事件日志（JSONL）。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, result: EpisodeResult, meta: dict[str, Any] | None = None) -> str:
        episode = result.episode_id
        task = result.trajectory.task
        lines: list[dict[str, Any]] = [
            {
                "type": "episode",
                "episodeId": episode,
                "taskId": task.id,
                "goal": task.goal,
                "family": task.family,
                "successCriteria": task.success_criteria,
                "context": _plain(task.context),
                "success": result.evaluation.success,
                "score": result.evaluation.score,
                "answer": result.trajectory.answer_text(),
                "evaluator": result.evaluation.evaluator,
                "rationale": result.evaluation.rationale,
                "returns": _plain(result.returns),
                "memoryBefore": _plain(result.memory_before),
                "memoryAfter": _plain(result.memory_after),
                "meta": _plain(meta or {}),
                "createdAt": _now(),
            }
        ]
        root_id = f"{episode}:root"
        lines.append(
            {
                "type": "node",
                "nodeId": root_id,
                "episodeId": episode,
                "parentId": None,
                "step": -1,
                "kind": "root",
                "goal": task.goal,
                "success": result.evaluation.success,
            }
        )
        parent = root_id
        for step in result.trajectory.steps:
            node_id = f"{episode}:{step.index}"
            candidates = [_candidate(item) for item in step.candidates]
            selected = _candidate(step.selected)
            alternatives = [item for item in candidates if item["actionId"] != selected["actionId"]]
            shaped = []
            if step.decision is not None:
                shaped = [
                    {
                        "actionId": item.candidate.action_id,
                        "qValue": item.q_value,
                        "rawAdvantage": item.raw_advantage,
                        "advantage": item.advantage,
                        "shapedScore": item.shaped_score,
                    }
                    for item in step.decision.shaped
                ]
            lines.append(
                {
                    "type": "node",
                    "nodeId": node_id,
                    "episodeId": episode,
                    "parentId": parent,
                    "step": step.index,
                    "kind": "step",
                    "state": {
                        "key": step.state.key,
                        "text": step.state.text,
                        "tokens": list(step.state.tokens),
                        "facets": _plain(step.state.facets),
                    },
                    "observation": {
                        "kind": step.observation.kind,
                        "ok": step.observation.ok,
                        # 完整原文；不存 prompt 截断后的版本
                        "text": step.observation.text,
                        "data": _plain(step.observation.data),
                    },
                    "selected": selected,
                    "candidates": candidates,
                    "alternatives": alternatives,
                    "shaped": shaped,
                    "decision": {
                        "stateValue": step.decision.state_value if step.decision else None,
                        "explorationProb": step.decision.exploration_prob if step.decision else None,
                        "temperature": step.decision.temperature if step.decision else None,
                    },
                    "modelText": step.model_text,
                    "usage": _plain(step.usage),
                    "error": step.error,
                }
            )
            parent = node_id
        with self.path.open("a", encoding="utf-8") as handle:
            for line in lines:
                handle.write(json.dumps(line, ensure_ascii=False) + "\n")
        return episode


def load_records(path: str | Path) -> list[dict[str, Any]]:
    file = Path(path)
    if not file.is_file():
        return []
    return [
        json.loads(line)
        for line in file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def build_forest(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    episodes: dict[str, dict[str, Any]] = {}
    nodes: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for record in records:
        if record.get("type") == "episode":
            episode_id = record["episodeId"]
            episodes[episode_id] = {**record, "children": []}
            order.append(episode_id)
        elif record.get("type") == "node":
            nodes[record["nodeId"]] = {**record, "children": []}
    forest: list[dict[str, Any]] = []
    for episode_id in order:
        episode = episodes[episode_id]
        episode_nodes = [node for node in nodes.values() if node["episodeId"] == episode_id]
        by_id = {node["nodeId"]: node for node in episode_nodes}
        root = by_id.get(f"{episode_id}:root")
        for node in episode_nodes:
            parent = by_id.get(node.get("parentId"))
            if parent is not None:
                parent["children"].append(node)
        episode["root"] = root
        forest.append(episode)
    return forest
