#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0：PMS 中文问数 × JitRL 三条实验臂（离线、可复现）。

臂 A：无记忆 + 全量 12 技能（基线）
臂 B：有记忆 + 全量 12 技能
臂 C：有记忆 + 薄技能（2 个 SKILL.md）

运行（在 expert-pack-4 下，使用 jitrl conda 环境）：

    python tools/run_pms_experiment.py --out runs/pms-p0

输出：runs/pms-p0/<arm>/results.jsonl + summary.json + summary.md
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

PROVIDERS = {
    "ark": {
        "key": "ARK_API_KEY",
        "base": "ARK_OPENAI_BASE_URL",
        "model": "ARK_MODEL",
    },
    "deepseek": {
        "key": "DEEPSEEK_API_KEY",
        "base": "DEEPSEEK_OPENAI_BASE_URL",
        "model": "DEEP_MODEL",
    },
    "kimi": {
        "key": "KIMI_API_KEY",
        "base": "KIMI_OPENAI_BASE_URL",
        "model": "KIMI_MODEL",
        "extra_body": {"temperature": 1.0, "max_tokens": 2000},
    },
}

PACK_DIR = Path(__file__).resolve().parents[1]
WORKSPACE = PACK_DIR.parent
if str(PACK_DIR) not in sys.path:
    sys.path.insert(0, str(PACK_DIR))
PMS_SKILL = WORKSPACE / "expert-pack-3" / "skills" / "pms-gateway-mcp"
PMS_MCP = PMS_SKILL / "scripts" / "mcp_server.py"
FULL_SKILLS = WORKSPACE / "expert-pack-3" / "skills"
THIN_SKILLS = PACK_DIR / "expert_pack" / "extensions" / "pms" / "thin_skills"
if str(PMS_SKILL / "scripts") not in sys.path:
    sys.path.insert(0, str(PMS_SKILL / "scripts"))


def load_env_file(path: Path) -> None:
    """读取工作区 .env（不覆盖已有环境变量，避免 CI/内网优先值被覆盖）。"""

    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _build_arm(
    arm: str,
    out: Path,
    seed: int,
    model_kind: str = "scripted",
    min_similarity: float = 0.4,
    top_k: int = 7,
    memory_min_neighbors: int = 0,
    memory_min_similarity: float = 0.0,
    memory_max_return_std: float = 0.0,
    enforce_action_hints: bool = False,
    provider: str = "ark",
    rank_tool: bool = False,
):
    from expert_pack.adapters.mcp_stdio import McpToolProvider
    from expert_pack.adapters.skills import load_skill_directory
    from expert_pack.agent import AgentConfig, ExpertAgent
    from expert_pack.extensions.pms.evaluator import PmsEvaluator
    from expert_pack.extensions.pms.planner import PmsScriptedPlanner
    from expert_pack.extensions.pms.retrieval import PmsRetriever, PmsRetrieverConfig
    from expert_pack.extensions.pms.state import PmsAbstractor
    from expert_pack.extensions.pms.rank_tool import PmsRankProvider
    from expert_pack.jitrl.advantage import AdvantageConfig
    from expert_pack.jitrl.memory import NullStore, SqliteExperienceStore
    from expert_pack.jitrl.policy import JitrlPolicy
    from expert_pack.jitrl.retrieval import JaccardRetriever

    if not PMS_MCP.is_file():
        raise SystemExit(f"缺少 PMS MCP：{PMS_MCP}（需要 expert-pack-3 与本包同级）")

    # MCP 的 mock 模式只返回 spec 里的静态样例，不会按参数过滤；实验必须走本地
    # mock gateway（真实 HTTP + token），这样 get_asset_by_id 等对象接口才能按 ID 返回。
    from mock_gateway.server import start_server

    server = start_server("127.0.0.1", 0, "token")
    gateway_env = {
        "PMS_AUTH_MODE": "token",
        "PMS_GATEWAY_BASE_URL": server.base_url,
        "PMS_TOKEN": server.auth.token,
        "PMS_MOCK_DATASET": os.environ.get("PMS_MOCK_DATASET", "base"),
    }
    tool_provider = McpToolProvider(
        "pms",
        sys.executable,
        [str(PMS_MCP)],
        cwd=str(PMS_SKILL),
        env=gateway_env,
        timeout=20.0,
    )
    rank_provider = PmsRankProvider(tool_provider) if rank_tool else None
    if arm in ("A", "B"):
        skills = load_skill_directory(FULL_SKILLS)
    elif arm == "C":
        skills = load_skill_directory(THIN_SKILLS)
    elif arm == "D":
        skills = []
    elif arm == "E":
        skills = []
    else:
        raise SystemExit(f"未知实验臂：{arm}（支持 A/B/C/D/E）")
    if arm in ("A", "E"):
        store = NullStore()
    else:
        memory_path = out / arm / "memory.sqlite3"
        memory_path.parent.mkdir(parents=True, exist_ok=True)
        if memory_path.exists():
            memory_path.unlink()
        store = SqliteExperienceStore(memory_path)
    policy = JitrlPolicy(
        AdvantageConfig(top_k=top_k, min_similarity=min_similarity), seed=seed
    )
    retriever = PmsRetriever(PmsRetrieverConfig(default_min_similarity=min_similarity))
    if model_kind == "openai":
        from expert_pack.adapters.model_openai import OpenAIConfig, OpenAIModel

        settings = PROVIDERS.get(provider)
        if settings is None:
            raise SystemExit(f"未知 provider：{provider}（支持 {sorted(PROVIDERS)}）")
        model_backend = OpenAIModel(
            OpenAIConfig(
                model=os.environ.get(settings["model"], ""),
                base_url=os.environ.get(settings["base"], ""),
                api_key_env=settings["key"],
                timeout=180.0,
                max_tokens=700,
                extra_body=dict(settings.get("extra_body") or {}),
            )
        )
    else:
        model_backend = PmsScriptedPlanner()
    agent = ExpertAgent(
        model=model_backend,
        tools=[tool_provider] + ([rank_provider] if rank_provider else []),
        skills=skills,
        store=store,
        retriever=retriever,
        abstractor=PmsAbstractor(),
        policy=policy,
        evaluator=PmsEvaluator(),
        config=AgentConfig(
            max_steps=6,
            seed=seed,
            temperature=0.0,
            memory_context=True,
            memory_context_k=3,
            memory_action_limit=3,
            max_prompt_observation_chars=2000,
            max_candidates=5,
            repair_attempts=2,
            memory_min_neighbors=memory_min_neighbors,
            memory_min_similarity=memory_min_similarity,
            memory_max_return_std=memory_max_return_std,
            enforce_action_hints=enforce_action_hints,
        ),
        run_id=f"pms-{arm}",
    )
    return tool_provider, rank_provider, store, agent, skills, server


def _run_arm(
    arm: str,
    out: Path,
    seed: int,
    limit: int,
    model_kind: str = "scripted",
    min_similarity: float = 0.4,
    top_k: int = 7,
    memory_min_neighbors: int = 0,
    memory_min_similarity: float = 0.0,
    memory_max_return_std: float = 0.0,
    dataset: str = "base",
    enforce_action_hints: bool = False,
    provider: str = "ark",
    rank_tool: bool = False,
    structured_compare: bool = False,
    tree_store_path: str | None = None,
) -> dict[str, Any]:
    if dataset == "extended":
        from expert_pack.extensions.pms.tasks import build_extended_tasks

        tasks = build_extended_tasks()
    elif dataset == "realistic":
        from expert_pack.extensions.pms.tasks_realistic import build_realistic_tasks

        tasks = build_realistic_tasks()
    elif dataset == "complex":
        from expert_pack.extensions.pms.tasks_complex import build_complex_tasks

        tasks = build_complex_tasks()
    else:
        from expert_pack.extensions.pms.tasks import build_tasks

        tasks = build_tasks()
    if limit > 0:
        tasks = tasks[:limit]
    compare_families = {"capacity_max", "highest_model", "global_rank"}
    if structured_compare:
        for task in tasks:
            if task.family in compare_families:
                task.context["requireComparisonTable"] = True
    if rank_tool:
        for task in tasks:
            if task.family in {"capacity_max", "highest_model"}:
                hints = list(task.context.get("suggestedActions") or [])
                hint = "tool:pms-rank/rank_devices"
                if hint not in hints:
                    hints.append(hint)
                task.context["suggestedActions"] = hints
                task.context["planHint"] = (
                    "可调用 tool:pms-rank/rank_devices(stationId, direction=max) 直接得到最高负载设备，"
                    "再用 get_asset_by_id 查型号。"
                )
            elif task.family == "global_rank":
                hints = list(task.context.get("suggestedActions") or [])
                for hint in ("tool:pms-rank/rank_stations", "tool:pms-rank/rank_devices"):
                    if hint not in hints:
                        hints.append(hint)
                task.context["suggestedActions"] = hints
                task.context["planHint"] = (
                    "可调用 tool:pms-rank/rank_stations(metric=availabilityRate, direction=min) "
                    "或 rank_devices(metric=loadRate, direction=max) 直接得到 winner。"
                )
    tree_store = None
    if tree_store_path:
        from expert_pack.trajectory.tree_store import TrajectoryTreeStore

        tree_store = TrajectoryTreeStore(tree_store_path)
    tool_provider, rank_provider, store, agent, skills, server = _build_arm(
        arm,
        out,
        seed,
        model_kind,
        min_similarity,
        top_k,
        memory_min_neighbors,
        memory_min_similarity,
        memory_max_return_std,
        enforce_action_hints,
        provider,
        rank_tool,
    )
    arm_dir = out / arm
    arm_dir.mkdir(parents=True, exist_ok=True)
    results_path = arm_dir / "results.jsonl"
    if results_path.exists():
        results_path.unlink()
    results: list[dict[str, Any]] = []
    try:
        for index, task in enumerate(tasks, start=1):
            result = None
            error: str | None = None
            for attempt in (1, 2, 3):
                try:
                    result = agent.solve(task, episode_index=index)
                    break
                except Exception as exc:  # noqa: BLE001 - one bad API call must not kill the run
                    error = f"{type(exc).__name__}: {exc}"
                    if attempt < 3:
                        time.sleep(2.0 * attempt)
            if result is None:
                record = {
                    "arm": arm,
                    "task_id": task.id,
                    "family": task.family,
                    "success": False,
                    "steps": 0,
                    "answer": "",
                    "expected": task.context.get("expect"),
                    "tool_errors": 0,
                    "selected": [],
                    "returns": [],
                    "memory_before": {},
                    "memory_after": {},
                    "rationale": error or "model failed",
                    "error": error,
                }
                results.append(record)
                with (arm_dir / "results.jsonl").open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                print(f"[{arm}] {index:02d}/{len(tasks)} {task.id:<24} ERROR {error}")
                continue
            if tree_store is not None:
                tree_store.record(
                    result,
                    {
                        "arm": arm,
                        "provider": provider,
                        "model": model_kind,
                        "dataset": dataset,
                    },
                )
            trajectory = result.trajectory
            tool_errors = sum(1 for step in trajectory.steps if not step.observation.ok)
            record = {
                "arm": arm,
                "task_id": task.id,
                "family": task.family,
                "success": result.evaluation.success,
                "steps": len(trajectory.steps),
                "answer": trajectory.answer_text(),
                "expected": task.context.get("expect"),
                "tool_errors": tool_errors,
                "selected": [step.selected.action_id for step in trajectory.steps],
                "returns": result.returns,
                "memory_before": result.memory_before,
                "memory_after": result.memory_after,
                "rationale": result.evaluation.rationale,
            }
            results.append(record)
            with (arm_dir / "results.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            status = "OK" if result.evaluation.success else "FAIL"
            print(f"[{arm}] {index:02d}/{len(tasks)} {task.id:<24} {status} steps={record['steps']}")
    finally:
        tool_provider.close()
        if rank_provider is not None:
            rank_provider.close()
        store.close()
        server.stop()

    success = sum(1 for item in results if item["success"])
    summary = {
        "arm": arm,
        "tasks": len(results),
        "success": success,
        "success_rate": round(success / len(results), 4) if results else 0.0,
        "avg_steps": round(sum(item["steps"] for item in results) / len(results), 2) if results else 0.0,
        "tool_errors": sum(item["tool_errors"] for item in results),
        "skills": len(skills),
        "memory_transitions": results[-1]["memory_after"].get("transitions", 0) if results else 0,
        "seed": seed,
        "model": model_kind,
        "provider": provider,
        "arm": arm,
        "dataset": dataset,
    }
    (arm_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def _write_report(out: Path, summaries: list[dict[str, Any]]) -> None:
    model = summaries[0].get("model", "scripted") if summaries else "scripted"
    provider = summaries[0].get("provider", "") if summaries else ""
    label = "{}/{}".format(model, provider) if provider else model
    lines = [
        "# PMS × JitRL 实验结果（{}）".format(label),
        "",
        "| 臂 | 任务数 | 成功 | 成功率 | 平均步数 | 工具错误 | 技能数 | 记忆 transitions |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for item in summaries:
        lines.append(
            "| {arm} | {tasks} | {success} | {rate:.2%} | {steps} | {errors} | {skills} | {memory} |".format(
                arm=item["arm"],
                tasks=item["tasks"],
                success=item["success"],
                rate=item["success_rate"],
                steps=item["avg_steps"],
                errors=item["tool_errors"],
                skills=item["skills"],
                memory=item["memory_transitions"],
            )
        )
    if model == "openai":
        note = [
            "> 说明：本实验使用真实 OpenAI 兼容模型（provider={}）；A=无记忆+全技能，B=有记忆+全技能，".format(
                summaries[0].get("provider", "ark") if summaries else "ark"
            ),
            "> C=有记忆+薄技能，D=有记忆+无技能，E=无记忆+无技能；结论只适用于本次模型与任务集。",
        ]
    else:
        note = [
            "> 说明：本实验使用脚本规划器（先选错工具，高置信度），用于验证",
            "> 「记忆优势能否翻转动作选择」；不代表真实 LLM 的绝对能力。",
            "> C 臂只有 2 个薄技能，若与 B 臂成功率接近，说明该任务集不依赖大量技能文本。",
        ]
    lines.extend(note)
    lines.append("")
    text = "\n".join(lines)
    (out / "summary.md").write_text(text, encoding="utf-8")
    (out / "summary.json").write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("")
    print(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PMS 问数 × JitRL P0 实验")
    parser.add_argument("--out", default=str(PACK_DIR / "runs" / "pms-p0"), help="输出目录")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 个任务（0=全部）")
    parser.add_argument("--model", choices=("scripted", "openai"), default="scripted")
    parser.add_argument("--provider", choices=("ark", "deepseek", "kimi"), default="ark")
    parser.add_argument("--arms", default="A,B,C", help="逗号分隔的实验臂，如 A,B")
    parser.add_argument("--min-similarity", type=float, default=0.4)
    parser.add_argument("--top-k", type=int, default=7)
    parser.add_argument("--memory-min-neighbors", type=int, default=0)
    parser.add_argument("--memory-min-similarity", type=float, default=0.0)
    parser.add_argument("--memory-max-return-std", type=float, default=0.0)
    parser.add_argument("--dataset", choices=("base", "extended", "realistic", "complex"), default="base")
    parser.add_argument("--enforce-hints", action="store_true", help="强制只允许任务建议的工具")
    parser.add_argument("--rank-tool", action="store_true", help="绑定 pms-rank 确定性比较工具")
    parser.add_argument("--structured-compare", action="store_true", help="要求比较题先输出候选表")
    parser.add_argument("--tree-store", default=None, help="轨迹树 JSONL 输出路径")
    args = parser.parse_args(argv)

    load_env_file(WORKSPACE / ".env")
    if args.dataset in ("extended", "realistic", "complex"):
        os.environ["PMS_MOCK_DATASET"] = "realistic" if args.dataset == "complex" else args.dataset
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    arms = [item.strip().upper() for item in args.arms.split(",") if item.strip()]
    summaries = []
    for arm in arms:
        print(f"== 实验臂 {arm} ==")
        summaries.append(
            _run_arm(
                arm,
                out,
                args.seed,
                args.limit,
                args.model,
                args.min_similarity,
                args.top_k,
                args.memory_min_neighbors,
                args.memory_min_similarity,
                args.memory_max_return_std,
                args.dataset,
                args.enforce_hints,
                args.provider,
                args.rank_tool,
                args.structured_compare,
                args.tree_store,
            )
        )
    _write_report(out, summaries)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
