"""让模型在轨迹树节点上提出“原树中没有的新候选动作”，并写入 JSONL。

这些新动作不直接执行；先作为候选分支保存，后续可以由 replay 模块验证。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from expert_pack.contracts import ModelMessage


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_candidates(text: str) -> list[dict[str, Any]]:
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:].strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(payload, dict):
        items = payload.get("candidates")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
        if "answer" in payload:
            return [{"action": "answer", "arguments": {"answer": payload["answer"]}}]
    return []


def find_generation_targets(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """选失败轨迹或最后一步是工具调用（未结束）的节点，作为新分支生成点。"""
    episodes = {r["episodeId"]: r for r in records if r.get("type") == "episode"}
    nodes = [r for r in records if r.get("type") == "node" and r.get("kind") == "step"]
    targets: list[dict[str, Any]] = []
    for node in nodes:
        episode = episodes.get(node["episodeId"])
        if not episode:
            continue
        # 失败轨迹的每个节点都可以生成；成功轨迹只生成最后一个工具节点
        if not episode.get("success"):
            targets.append(node)
        else:
            selected = node.get("selected") or {}
            if selected.get("kind") == "tool":
                targets.append(node)
    return targets


def generate_new_branches(
    records: Sequence[dict[str, Any]],
    model: Any,
    tool_provider: Any,
    out_path: str,
    max_targets: int = 5,
) -> int:
    """对每个目标节点让模型提出新候选，写入 JSONL。"""
    episodes = {r["episodeId"]: r for r in records if r.get("type") == "episode"}
    targets = find_generation_targets(records)[:max_targets]
    if not targets:
        return 0

    tools_desc = []
    try:
        for spec in tool_provider.list_tools():
            schema = getattr(spec, "input_schema", {}) or {}
            props = schema.get("properties") or {}
            params = ", ".join(f"{k}*" for k in props)
            tools_desc.append(
                "tool:{}/{}  {}{}".format(
                    getattr(spec, "provider", "pms"),
                    getattr(spec, "name", ""),
                    getattr(spec, "description", "")[:120],
                    f" params: {params}" if params else "",
                )
            )
    except Exception:
        tools_desc = []

    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    for node in targets:
        episode = episodes[node["episodeId"]]
        existing = set()
        for c in node.get("candidates") or []:
            existing.add(c.get("actionId"))
        for a in node.get("alternatives") or []:
            existing.add(a.get("actionId"))

        prompt = "\n".join([
            "You are a PMS data-query agent. Given the task and current observation, propose 1-2 NEW candidate actions that were NOT tried yet.",
            "TASK: " + str(episode.get("goal", "")),
            "CURRENT OBSERVATION:",
            (node.get("observation") or {}).get("text", "")[:3000],
            "",
            "ALREADY TRIED (do not repeat):",
            str(sorted(existing)),
            "",
            "AVAILABLE TOOLS:",
            *tools_desc[:25],
            "",
            'Return JSON: {"candidates":[{"action":"tool:pms/<name>","arguments":{...},"confidence":0.5,"why":"..."}]}',
        ])
        reply = model.complete([ModelMessage("user", prompt)], temperature=0.0, max_tokens=1500)
        items = _load_candidates(str(getattr(reply, "text", "") or ""))
        for item in items:
            action = str(item.get("action", ""))
            if not action or action in existing:
                continue
            record = {
                "type": "generated_branch",
                "id": "gen:" + uuid.uuid4().hex[:8],
                "episodeId": node["episodeId"],
                "parentNodeId": node["nodeId"],
                "parentStep": node.get("step"),
                "action": action,
                "arguments": item.get("arguments") or {},
                "confidence": item.get("confidence", 0.0),
                "why": item.get("why", ""),
                "createdAt": _now(),
            }
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
    return count
