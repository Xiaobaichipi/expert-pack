"""Command line interface: slots, validate, demo, run, memory, init, pack."""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from expert_pack import __version__
from expert_pack.adapters.model_stub import UnboundModel
from expert_pack.assembly import Assembly, build_runtime, default_assembly, inspect_assembly, load_assembly
from expert_pack.contracts import Task
from expert_pack.errors import AssemblyError, ExpertPackError, ModelError, VacancyError
from expert_pack.jitrl.memory import NullStore, SqliteExperienceStore
from expert_pack.pipeline import BatchItem, BatchPipeline, PipelineContext, Stage
from expert_pack.slots import SlotRegistry

_TASK_FIELDS = {"id", "goal", "success_criteria", "max_steps", "family", "context"}


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _default_assembly_path() -> Path | None:
    candidate = Path(".expert_pack/assembly.json")
    return candidate if candidate.is_file() else None


def _load_tasks(path: str | Path) -> list[Task]:
    target = Path(path)
    if not target.is_file():
        raise AssemblyError(f"task file not found: {target}")
    tasks: list[Task] = []
    ids: set[str] = set()
    for lineno, line in enumerate(target.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            raw = json.loads(line)
        except ValueError as exc:
            raise AssemblyError(f"{target}:{lineno}: invalid JSON: {exc}") from exc
        if not isinstance(raw, dict):
            raise AssemblyError(f"{target}:{lineno}: each line must be a JSON object")
        unknown = set(raw) - _TASK_FIELDS
        if unknown:
            raise AssemblyError(f"{target}:{lineno}: unknown task fields {sorted(unknown)}")
        if not raw.get("id") or not raw.get("goal"):
            raise AssemblyError(f"{target}:{lineno}: 'id' and 'goal' are required")
        if str(raw["id"]) in ids:
            raise AssemblyError(f"{target}:{lineno}: duplicate task id {raw['id']!r}")
        ids.add(str(raw["id"]))
        context = raw.get("context") or {}
        if not isinstance(context, dict):
            raise AssemblyError(f"{target}:{lineno}: 'context' must be an object")
        tasks.append(
            Task(
                id=str(raw["id"]),
                goal=str(raw["goal"]),
                success_criteria=str(raw.get("success_criteria") or ""),
                max_steps=int(raw.get("max_steps") or 0),
                family=str(raw.get("family") or ""),
                context=context,
            )
        )
    if not tasks:
        raise AssemblyError(f"{target} contains no tasks")
    return tasks


def _summary(result: Any) -> dict[str, Any]:
    trace = []
    for step in result.trajectory.steps:
        decision = step.decision
        trace.append(
            {
                "step": step.index,
                "state_key": step.state.key,
                "selected": step.selected.display(80),
                "source": step.selected.source,
                "ok": step.observation.ok,
                "observation": step.observation.text[:300],
                "state_value": None if decision is None else decision.state_value,
                "exploration_prob": None if decision is None else decision.exploration_prob,
                "shaped": [] if decision is None else [
                    {
                        "action": item.candidate.action_id,
                        "base": round(item.candidate.base_score, 4),
                        "q": item.q_value,
                        "advantage": round(item.advantage, 4),
                        "score": round(item.shaped_score, 4),
                    }
                    for item in decision.shaped
                ],
            }
        )
    return {
        "episode_id": result.episode_id,
        "task_id": result.trajectory.task.id,
        "success": result.success,
        "steps": result.steps,
        "answer": result.trajectory.answer_text(),
        "expected": result.trajectory.task.expect(),
        "score": result.evaluation.score,
        "evaluator": result.evaluation.evaluator,
        "rationale": result.evaluation.rationale,
        "returns": result.returns,
        "usage": result.trajectory.usage,
        "memory_before": result.memory_before,
        "memory_after": result.memory_after,
        "trace": trace,
    }


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


def cmd_slots(args: argparse.Namespace) -> int:
    if args.assembly:
        _assembly, report = inspect_assembly(args.assembly)
    else:
        report = SlotRegistry().describe()
    output = report.to_json() if args.json else report.table()
    print(output)
    vacancies = [s for s in report.vacancies]
    if vacancies and not args.json:
        print("\nNext vacancies (fill these in assembly.json):")
        for state in vacancies:
            print(f"  - {state.spec.id} ({state.status}): {state.spec.hint or state.spec.description}")
    if args.write:
        target = Path(args.write)
        target.parent.mkdir(parents=True, exist_ok=True)
        content = report.to_json() if target.suffix.lower() == ".json" else report.table()
        target.write_text(content + "\n", encoding="utf-8")
        print(f"\nwrote {target}")
    if args.strict and not report.ok:
        print("\nstrict check failed", file=sys.stderr)
        return 1
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    path = Path(args.assembly) if args.assembly else _default_assembly_path()
    if path is None:
        print(
            "no assembly file: pass --assembly PATH or run from a project with "
            ".expert_pack/assembly.json",
            file=sys.stderr,
        )
        return 2
    assembly, report = inspect_assembly(path)
    print(f"assembly: {assembly.name}  ({assembly.source})")
    print(f"agent options: {json.dumps(assembly.agent, ensure_ascii=False)}")
    print()
    print(report.table())
    problems = report.strict_problems() if args.strict else [
        f"{s.spec.id}: {s.status}" for s in report.states if s.status in {"vacant", "invalid"}
    ]
    for state in report.vacancies:
        print(f"hint {state.spec.id}: {state.spec.hint or state.spec.description}")
    if problems:
        print("\nnot runnable:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("\nassembly is runnable")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    from expert_pack.builtin.demo import run_demo

    report = run_demo(count=args.tasks, seed=args.seed)
    print("== expert-pack offline demo ==")
    print("model: scripted demo planner (no API key) | tools: MCP stdio demo server")
    print("skills: 2 built-in | memory: sqlite")
    print()
    print(f"{'task':10} {'baseline':16} {'with JitRL memory':16}")
    for base, mem in zip(report.baseline, report.memory):
        b = ("ok  " if base.success else "FAIL") + f" ({base.answer or '-'})"
        m = ("ok  " if mem.success else "FAIL") + f" ({mem.answer or '-'})"
        print(f"{base.task_id:10} {b:16} {m:16}")
    print()
    print(
        f"success rate: baseline {report.baseline_rate:.0%} "
        f"-> memory {report.memory_rate:.0%}"
    )
    print(
        f"memory: {report.memory_stats.get('episodes')} episodes, "
        f"{report.memory_stats.get('transitions')} transitions"
    )
    if args.trace:
        print("\n== decision traces (memory arm) ==")
        for episode in report.memory:
            print(f"\n{episode.task_id} (success={episode.success}, answer={episode.answer!r})")
            for index, trace in enumerate(episode.decisions):
                print(f"  step {index}: {trace}")
    if not args.keep:
        parent = Path(report.memory_path).parent
        if "expert-pack-demo-" in str(parent):
            shutil.rmtree(parent, ignore_errors=True)
    else:
        print(f"\nmemory kept at {report.memory_path}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    tasks = _load_tasks(args.tasks)
    assembly_path = Path(args.assembly) if args.assembly else _default_assembly_path()
    assembly = load_assembly(assembly_path) if assembly_path else default_assembly()
    run_id = args.run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out) if args.out else Path(".expert_pack/runs") / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "results.jsonl"
    overrides = {"store": NullStore()} if args.no_memory else None

    runtime = build_runtime(
        assembly,
        base_dir=assembly.base_dir,
        overrides=overrides,
        strict=args.strict,
        run_id=run_id,
    )
    if isinstance(runtime.model, UnboundModel):
        runtime.close()
        print(
            "the model slot is vacant: bind a model in assembly.json or set "
            "EXPERT_PACK_MODEL / EXPERT_PACK_BASE_URL / EXPERT_PACK_API_KEY",
            file=sys.stderr,
        )
        return 2
    config = runtime.config
    if args.max_steps:
        config.max_steps = args.max_steps
    if args.temperature is not None:
        config.temperature = args.temperature
    if args.seed is not None:
        config.seed = args.seed
        if hasattr(runtime.policy, "reseed"):
            runtime.policy.reseed(args.seed)

    (out_dir / "run.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "assembly": assembly.as_dict(),
                "assembly_source": str(assembly_path) if assembly_path else "(defaults)",
                "tasks": str(Path(args.tasks).resolve()),
                "started_at": datetime.now().isoformat(timespec="seconds"),
                "no_memory": bool(args.no_memory),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def prepare(_ctx: PipelineContext, item: BatchItem) -> BatchItem:
        if not item.payload.get("goal"):
            raise ValueError("task has no goal")
        return item

    def solve(ctx: PipelineContext, item: BatchItem) -> BatchItem:
        ctx.data["seq"] = ctx.data.get("seq", 0) + 1
        raw = item.payload
        task = Task(
            id=str(raw["id"]),
            goal=str(raw["goal"]),
            success_criteria=str(raw.get("success_criteria") or ""),
            max_steps=int(raw.get("max_steps") or runtime.config.max_steps),
            family=str(raw.get("family") or ""),
            context=dict(raw.get("context") or {}),
        )
        result = runtime.agent.solve(task, episode_index=ctx.data["seq"])
        summary = _summary(result)
        item.data["summary"] = summary
        status = "ok" if summary["success"] else "FAIL"
        print(
            f"[{ctx.data['seq']}/{len(ctx.data['items'])}] {task.id} {status} "
            f"steps={summary['steps']} answer={summary['answer']!r}"
        )
        if args.trace:
            for step in summary["trace"]:
                print(
                    f"    step {step['step']}: {step['selected']} "
                    f"(source={step['source']}, ok={step['ok']}, V={step['state_value']})"
                )
                for shaped in step["shaped"]:
                    print(
                        f"      {shaped['action']}: base={shaped['base']:+.2f} "
                        f"q={shaped['q']} adv={shaped['advantage']:+.2f} "
                        f"score={shaped['score']:+.2f}"
                    )
        return item

    def record(_ctx: PipelineContext, item: BatchItem) -> BatchItem:
        summary = item.data.get("summary")
        if not summary:
            raise ValueError("no summary to record")
        with results_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(summary, ensure_ascii=False) + "\n")
        return item

    pipeline = BatchPipeline(
        [Stage("prepare", prepare), Stage("solve", solve), Stage("record", record)],
        state_dir=out_dir,
    )
    items = [BatchItem(id=task.id, payload=_task_payload(task)) for task in tasks]
    context = PipelineContext(run_id=run_id, runtime=runtime, data={"items": items, "seq": 0})
    report = pipeline.run(items, context, resume=args.resume)
    summary = report.summary()
    successes = sum(
        1 for item in report.done if (item.data.get("summary") or {}).get("success")
    )
    print()
    print(
        f"run {run_id}: {successes}/{summary['total']} succeeded, "
        f"{summary['failed']} failed, {summary['resumed']} resumed"
    )
    for item in report.failed:
        print(f"  failed {item.id}: {item.error}")
    print(f"results: {results_path}")
    print(f"memory: {json.dumps(runtime.store.stats(), ensure_ascii=False)}")
    runtime.close()
    return 0


def _task_payload(task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "goal": task.goal,
        "success_criteria": task.success_criteria,
        "max_steps": task.max_steps,
        "family": task.family,
        "context": dict(task.context),
    }


def cmd_memory(args: argparse.Namespace) -> int:
    path = Path(args.path)
    if args.action == "stats":
        if not path.exists():
            print(f"no memory at {path}")
            return 1
        store = SqliteExperienceStore(path)
        try:
            print(json.dumps(store.stats(), indent=2, ensure_ascii=False))
        finally:
            store.close()
        return 0
    if args.action == "clear":
        if not path.exists():
            print(f"no memory at {path}")
            return 1
        store = SqliteExperienceStore(path)
        try:
            store.clear()
            print(f"cleared {path}")
        finally:
            store.close()
        return 0
    if args.action == "export":
        if not path.exists():
            print(f"no memory at {path}")
            return 1
        store = SqliteExperienceStore(path)
        try:
            payload = {
                "episodes": [episode.__dict__ for episode in store.episodes()],
                "transitions": [transition.__dict__ for transition in store.transitions()],
            }
        finally:
            store.close()
        target = Path(args.out or (path.with_suffix(".export.json")))
        target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"exported {len(payload['episodes'])} episodes, "
              f"{len(payload['transitions'])} transitions to {target}")
        return 0
    raise AssertionError(args.action)


_INIT_ASSEMBLY = """{
  "version": 1,
  "name": "my-expert-pack",
  "agent": {
    "max_steps": 8,
    "temperature": 0.0,
    "memory_context": true,
    "seed": 7
  },
  "bindings": []
}
"""

_INIT_README = """# my-expert-pack

A skeleton produced by `expert-pack init`. The slots are declared, the loop
runs, and the model is the only hard vacancy.

First make the framework importable from this directory, one of:

    pip install -e /path/to/expert-pack        # or: pip install expert-pack.zip
    set PYTHONPATH=/path/to/expert-pack        # Windows (cmd)
    export PYTHONPATH=/path/to/expert-pack     # bash

Then the commands below work.

## 1. See the vacancies

    python -m expert_pack slots --assembly .expert_pack/assembly.json

## 2. Fill them

Edit `.expert_pack/assembly.json`. Examples:

    {"slot": "model", "type": "module",
     "target": "expert_pack.adapters.model_openai:from_config",
     "config": {"model": "gpt-4o-mini", "api_key_env": "OPENAI_API_KEY"}}

    {"slot": "tools", "type": "mcp_stdio", "target": "filesystem",
     "config": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "."]}}

    {"slot": "skills", "type": "skill_dir", "target": "skills"}

## 3. Validate and run

    python -m expert_pack validate --assembly .expert_pack/assembly.json
    python -m expert_pack run --tasks tasks.example.jsonl --assembly .expert_pack/assembly.json --trace

Memory lives in `.expert_pack/memory.sqlite3`. Delete it to reset the learner.
"""

_INIT_SKILL = """---
name: example-skill
description: A prompt-only skill: selecting it loads these instructions.
when_to_use: When the task needs a short, explicit checklist.
---

# Example skill

1. Restate the goal in one line.
2. Name the observation that supplies each operand.
3. Answer with the smallest sufficient text.
"""

_INIT_TASKS = """{"id":"ex-1","goal":"What is 21 multiplied by 2? Answer with the number only.","success_criteria":"Return the numeric result.","family":"arithmetic","max_steps":4,"context":{"expect":"42"}}
{"id":"ex-2","goal":"What is 9 multiplied by 7? Answer with the number only.","success_criteria":"Return the numeric result.","family":"arithmetic","max_steps":4,"context":{"expect":"63"}}
"""


def _write_new(path: Path, content: str, *, force: bool) -> bool:
    if path.exists() and not force:
        print(f"skip existing {path}")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"wrote {path}")
    return True


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.directory)
    root.mkdir(parents=True, exist_ok=True)
    state = root / ".expert_pack"
    _write_new(state / "assembly.json", _INIT_ASSEMBLY, force=args.force)
    _write_new(root / "tasks.example.jsonl", _INIT_TASKS, force=args.force)
    _write_new(root / "skills" / "example-skill" / "SKILL.md", _INIT_SKILL, force=args.force)
    _write_new(root / "README.md", _INIT_README, force=args.force)
    _write_new(root / ".gitignore", ".expert_pack/\n__pycache__/\n", force=args.force)
    print("\nnext: python -m expert_pack slots --assembly .expert_pack/assembly.json")
    return 0


def cmd_pack(args: argparse.Namespace) -> int:
    root = _repo_root()
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    include = [
        "expert_pack",
        "skills",
        "docs",
        "tests",
        "AGENTS.md",
        "README.md",
        "pyproject.toml",
        "assembly.example.json",
    ]
    skip_dirs = {"__pycache__", ".expert_pack", "dist"}
    count = 0
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in include:
            path = root / name
            if not path.exists():
                continue
            if path.is_file():
                archive.write(path, name)
                count += 1
                continue
            for child in path.rglob("*"):
                if child.is_dir() or any(part in skip_dirs for part in child.parts):
                    continue
                if child.suffix in {".sqlite3", ".pyc"}:
                    continue
                relative = child.relative_to(root).as_posix()
                archive.write(child, relative)
                count += 1
    print(f"packed {count} files into {target}")
    return 0


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="expert-pack",
        description="A slot-based Skills + MCP agent with JitRL-style adaptation.",
    )
    parser.add_argument("--version", action="version", version=f"expert-pack {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    slots = sub.add_parser("slots", help="show the slot catalog and its vacancies")
    slots.add_argument("--assembly", help="assembly.json used to compute bindings")
    slots.add_argument("--json", action="store_true", help="machine-readable output")
    slots.add_argument("--write", help="write the report to this path (.json or text)")
    slots.add_argument("--strict", action="store_true", help="exit 1 on a non-runnable slot")
    slots.set_defaults(func=cmd_slots)

    validate = sub.add_parser("validate", help="resolve every binding and check contracts")
    validate.add_argument("--assembly")
    validate.add_argument("--strict", action="store_true", help="also reject stub bindings")
    validate.set_defaults(func=cmd_validate)

    demo = sub.add_parser("demo", help="offline demo: MCP tools + memory flips a decision")
    demo.add_argument("--tasks", type=int, default=5)
    demo.add_argument("--seed", type=int, default=7)
    demo.add_argument("--trace", action="store_true", help="print per-step candidate scores")
    demo.add_argument("--keep", action="store_true", help="keep the demo memory database")
    demo.set_defaults(func=cmd_demo)

    run = sub.add_parser("run", help="run a batch of tasks through the pipeline")
    run.add_argument("--tasks", required=True, help="JSONL task file")
    run.add_argument("--assembly")
    run.add_argument("--out", help="output directory")
    run.add_argument("--run-id")
    run.add_argument("--no-memory", action="store_true", help="baseline arm: do not read or write memory")
    run.add_argument("--resume", action="store_true", help="resume from checkpoints in --out")
    run.add_argument("--max-steps", type=int)
    run.add_argument("--temperature", type=float)
    run.add_argument("--seed", type=int)
    run.add_argument("--strict", action="store_true")
    run.add_argument("--trace", action="store_true")
    run.set_defaults(func=cmd_run)

    memory = sub.add_parser("memory", help="inspect or export the experience store")
    memory.add_argument("action", choices=["stats", "export", "clear"])
    memory.add_argument("--path", default=".expert_pack/memory.sqlite3")
    memory.add_argument("--out", help="export destination")
    memory.set_defaults(func=cmd_memory)

    init = sub.add_parser("init", help="scaffold a new project skeleton with vacancies")
    init.add_argument("directory", nargs="?", default=".")
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=cmd_init)

    pack = sub.add_parser("pack", help="zip the framework for another machine")
    pack.add_argument("--out", default="dist/expert-pack.zip")
    pack.set_defaults(func=cmd_pack)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        return int(args.func(args))
    except (VacancyError, AssemblyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ModelError as exc:
        print(f"model error: {exc}", file=sys.stderr)
        return 2
    except ExpertPackError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
