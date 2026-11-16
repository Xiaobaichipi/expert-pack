#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在轨迹树上做反事实 replay（Dream-RSI 轻量版）。

支持：
* fixed：沿用原后续动作；
* model：从分支点由模型重新规划；
* --all：批量 replay 所有未选分支；
* --generate：让模型提出原树中没有的新候选动作。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PACK_DIR = Path(__file__).resolve().parents[1]
WORKSPACE = PACK_DIR.parent
PMS_SKILL = WORKSPACE / "expert-pack-3" / "skills" / "pms-gateway-mcp"
PMS_MCP = PMS_SKILL / "scripts" / "mcp_server.py"

if str(PACK_DIR) not in sys.path:
    sys.path.insert(0, str(PACK_DIR))
if str(PMS_SKILL / "scripts") not in sys.path:
    sys.path.insert(0, str(PMS_SKILL / "scripts"))


def _load_env(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _build_model(provider: str):
    from expert_pack.adapters.model_openai import OpenAIConfig, OpenAIModel

    settings = {
        "ark": ("ARK_API_KEY", "ARK_OPENAI_BASE_URL", "ARK_MODEL", {}),
        "deepseek": (
            "DEEPSEEK_API_KEY",
            "DEEPSEEK_OPENAI_BASE_URL",
            "DEEP_MODEL",
            {"max_tokens": 2000},
        ),
        "kimi": (
            "KIMI_API_KEY",
            "KIMI_OPENAI_BASE_URL",
            "KIMI_MODEL",
            {"temperature": 1.0, "max_tokens": 2000},
        ),
    }[provider]
    return OpenAIModel(
        OpenAIConfig(
            model=os.environ.get(settings[2], ""),
            base_url=os.environ.get(settings[1], ""),
            api_key_env=settings[0],
            timeout=180.0,
            max_tokens=2000,
            extra_body=dict(settings[3]),
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="轨迹树反事实 replay")
    parser.add_argument("tree", help="tree.jsonl")
    parser.add_argument("--episode", default="", help="episodeId；省略则用第一个有分支的")
    parser.add_argument("--task", default="", help="taskId；省略则用第一个有分支的")
    parser.add_argument("--step", type=int, default=-1, help="分支所在 step")
    parser.add_argument("--alt", default="", help="未选候选 actionId；省略则用第一个")
    parser.add_argument("--out", default="", help="replay 记录 JSONL")
    parser.add_argument("--memory", default="", help="把验证成功的分支写入该 sqlite 记忆")
    parser.add_argument("--include-failed", action="store_true", help="失败分支也写记忆")
    parser.add_argument("--rollout", choices=("fixed", "model"), default="fixed",
                        help="fixed=沿用原后续动作；model=从分支点由模型重新规划")
    parser.add_argument("--provider", choices=("ark", "deepseek", "kimi"), default="deepseek")
    parser.add_argument("--all", action="store_true", help="批量 replay 所有未选分支")
    parser.add_argument("--generate", action="store_true", help="让模型提出新候选动作")
    parser.add_argument("--max-gen", type=int, default=5, help="生成新分支的最大节点数")
    parser.add_argument("--list", action="store_true", help="只列出可选分支")
    args = parser.parse_args(argv)
    _load_env(WORKSPACE / ".env")

    from expert_pack.trajectory.replay import TreeReplayer, find_branches, episode_record
    from expert_pack.trajectory.tree_store import load_records

    records = load_records(args.tree)
    branches = find_branches(records)
    if not branches and not args.generate:
        print("没有可 replay 的未选分支")
        return 1

    if args.generate:
        # 生成新候选动作，不需要现有分支
        dataset = "realistic"
        os.environ["PMS_MOCK_DATASET"] = dataset
        from mock_gateway.server import start_server
        from expert_pack.adapters.mcp_stdio import McpToolProvider
        server = start_server("127.0.0.1", 0, "token")
        provider = McpToolProvider(
            "pms", sys.executable, [str(PMS_MCP)], cwd=str(PMS_SKILL),
            env={
                "PMS_AUTH_MODE": "token",
                "PMS_GATEWAY_BASE_URL": server.base_url,
                "PMS_TOKEN": server.auth.token,
                "PMS_MOCK_DATASET": dataset,
            },
            timeout=20.0,
        )
        model = _build_model(args.provider)
        try:
            from expert_pack.trajectory.generate import generate_new_branches
            count = generate_new_branches(
                records, model, provider,
                out_path=args.out or str(Path(args.tree).with_suffix(".gen.jsonl")),
                max_targets=args.max_gen,
            )
            print(f"generated {count} new branches")
        finally:
            provider.close()
            server.stop()
        return 0

    selected = []
    for branch in branches:
        episode = episode_record(records, branch.episode_id)
        if args.episode and branch.episode_id != args.episode:
            continue
        if args.task and episode.get("taskId") != args.task:
            continue
        if args.step >= 0 and int(branch.node.get("step", 0)) != args.step:
            continue
        if args.alt and branch.alternative.get("actionId") != args.alt:
            continue
        selected.append(branch)

    if args.list:
        for branch in selected or branches:
            print(
                "episode={} task={} step={} alt={}".format(
                    branch.episode_id,
                    episode_record(records, branch.episode_id).get("taskId"),
                    branch.node.get("step"),
                    branch.alternative.get("actionId"),
                )
            )
        return 0

    if not selected and not args.all:
        print("没有匹配的分支")
        return 1

    # 数据集判断
    dataset = "realistic"
    for r in records:
        if r.get("type") == "episode":
            dataset = str((r.get("meta") or {}).get("dataset") or "realistic")
            break
    os.environ["PMS_MOCK_DATASET"] = dataset

    from mock_gateway.server import start_server
    from expert_pack.adapters.mcp_stdio import McpToolProvider

    server = start_server("127.0.0.1", 0, "token")
    provider = McpToolProvider(
        "pms", sys.executable, [str(PMS_MCP)], cwd=str(PMS_SKILL),
        env={
            "PMS_AUTH_MODE": "token",
            "PMS_GATEWAY_BASE_URL": server.base_url,
            "PMS_TOKEN": server.auth.token,
            "PMS_MOCK_DATASET": dataset,
        },
        timeout=20.0,
    )
    rollout_model = _build_model(args.provider) if args.rollout == "model" else None
    try:
        replayer = TreeReplayer(provider)
        if args.all:
            outcomes = replayer.replay_all(
                records,
                out_path=args.out or None,
                memory_path=args.memory or None,
                rollout_model=rollout_model,
                write_failed=args.include_failed,
            )
            ok = sum(1 for o in outcomes if o.success)
            print(f"replayed {len(outcomes)} branches, success {ok}/{len(outcomes)}")
            for o in outcomes:
                print(
                    "  {} step={} alt={} success={} steps={}".format(
                        o.episode_id, o.branch_step, o.branch_action, o.success, o.steps
                    )
                )
        else:
            branch = selected[0]
            outcome = replayer.replay(
                records,
                branch,
                out_path=args.out or None,
                memory_path=args.memory or None,
                write_failed=args.include_failed,
                rollout_model=rollout_model,
            )
            print("replay:", outcome.replay_id)
            print("episode:", outcome.episode_id, "step:", outcome.branch_step, "alt:", outcome.branch_action)
            print(
                "original={} branch={} score={:.3f} steps={}".format(
                    outcome.original_success, outcome.success, outcome.score, outcome.steps
                )
            )
            print("answer:", outcome.answer)
            print("memoryWritten:", outcome.memory_written)
    finally:
        provider.close()
        server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
