"""从轨迹树和 replay 结果中提炼可复用的 Skill 候选。

当前实现是**候选生成**，不是自动写正式 Skill：
1. 读取 tree.jsonl / replays.jsonl / generated-branches.jsonl；
2. 按 (task_family, action_sequence) 聚合成功轨迹；
3. 提炼为 Markdown 草稿，写入 skill-candidates/；
4. 人工审核后再转为正式 SKILL.md。
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _action_seq(steps: list[dict[str, Any]]) -> str:
    actions = []
    for step in steps:
        selected = step.get("selected") or {}
        action = selected.get("actionId") or selected.get("action") or ""
        if action:
            actions.append(action)
    return " → ".join(actions)


def _load_records(path: str | Path) -> list[dict[str, Any]]:
    file = Path(path)
    if not file.is_file():
        return []
    return [
        json.loads(line)
        for line in file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _episode_steps(records: Sequence[dict[str, Any]], episode_id: str) -> list[dict[str, Any]]:
    steps = [
        r for r in records
        if r.get("type") == "node" and r.get("episodeId") == episode_id and r.get("kind") == "step"
    ]
    steps.sort(key=lambda r: int(r.get("step", 0)))
    return steps


def distill_skills(
    tree_path: str,
    replays_path: str | None = None,
    generated_path: str | None = None,
    out_dir: str = "skill-candidates",
    min_success: int = 2,
) -> list[dict[str, Any]]:
    """从轨迹树提炼 Skill 候选。"""
    records = _load_records(tree_path)
    episodes = {r["episodeId"]: r for r in records if r.get("type") == "episode"}

    # 聚合成功轨迹
    patterns: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for episode_id, episode in episodes.items():
        if not episode.get("success"):
            continue
        steps = _episode_steps(records, episode_id)
        if not steps:
            continue
        family = episode.get("family", "")
        seq = _action_seq(steps)
        key = f"{family}|{seq}"
        patterns[key].append({
            "episodeId": episode_id,
            "taskId": episode.get("taskId"),
            "goal": episode.get("goal"),
            "family": family,
            "sequence": seq,
            "steps": len(steps),
            "answer": episode.get("answer"),
            "meta": episode.get("meta"),
        })

    # 加入 replay 成功分支
    if replays_path:
        replay_records = _load_records(replays_path)
        for r in replay_records:
            if r.get("type") != "replay" or not r.get("success"):
                continue
            # replay 分支的 action 序列：alt + 后续（从 record 里重建）
            episode_id = r.get("episodeId", "")
            steps = _episode_steps(records, episode_id)
            alt_action = (r.get("alternative") or {}).get("actionId", "")
            seq = alt_action + " → " + _action_seq(steps[int(r.get("branchStep", 0)):]) if steps else alt_action
            family = episodes.get(episode_id, {}).get("family", "")
            key = f"{family}|{seq}"
            patterns[key].append({
                "episodeId": episode_id,
                "taskId": r.get("parentTaskId"),
                "goal": episodes.get(episode_id, {}).get("goal"),
                "family": family,
                "sequence": seq,
                "steps": r.get("steps", 0),
                "answer": r.get("answer"),
                "source": "replay",
            })

    # 加入生成的新候选（未验证，标记为 draft）
    if generated_path:
        gen_records = _load_records(generated_path)
        for r in gen_records:
            if r.get("type") != "generated_branch":
                continue
            family = episodes.get(r.get("episodeId"), {}).get("family", "")
            seq = str(r.get("action", ""))
            key = f"{family}|{seq}"
            patterns[key].append({
                "episodeId": r.get("episodeId"),
                "taskId": None,
                "goal": episodes.get(r.get("episodeId"), {}).get("goal"),
                "family": family,
                "sequence": seq,
                "steps": 0,
                "answer": None,
                "source": "generated",
            })

    # 筛选：至少 min_success 个成功样本，或来自 generated 的 draft
    candidates: list[dict[str, Any]] = []
    for key, items in patterns.items():
        success_items = [i for i in items if i.get("answer") and not i.get("source")]
        generated_items = [i for i in items if i.get("source") == "generated"]
        if len(success_items) >= min_success or generated_items:
            sample = success_items[0] if success_items else generated_items[0]
            candidates.append({
                "id": f"skill-{len(candidates)+1:03d}",
                "family": sample["family"],
                "sequence": sample["sequence"],
                "goal": sample.get("goal"),
                "taskId": sample.get("taskId"),
                "success_count": len(success_items),
                "generated_count": len(generated_items),
                "sample_answer": sample.get("answer"),
                "status": "draft" if generated_items and not success_items else "verified",
                "createdAt": _now(),
            })

    # 写 Markdown 草稿
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for cand in candidates:
        filename = f"{cand['id']}-{cand['family'].replace('_', '-')}.md"
        content = f"""# Skill 候选：{cand['family']}

## 元数据
- **ID**: {cand['id']}
- **意图族**: {cand['family']}
- **状态**: {cand['status']}
- **成功样本**: {cand['success_count']}
- **生成候选**: {cand['generated_count']}
- **提炼时间**: {cand['createdAt']}

## 触发条件
{chr(10).join('- ' + str(g) for g in set(i.get('goal') for i in patterns[key] if i.get('goal')))}

## 推荐动作序列
```
{cand['sequence']}
```

## 示例答案
```
{cand.get('sample_answer') or '（待验证）'}
```

## 审核清单
- [ ] 动作序列是否覆盖所有必要步骤？
- [ ] 是否有遗漏的异常分支？
- [ ] 参数是否可移植（stationId/assetId 等）？
- [ ] 是否需要补充边界条件？
"""
        (out / filename).write_text(content, encoding="utf-8")
        cand["file"] = str(out / filename)

    return candidates
