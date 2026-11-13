"""Assembly: fill the slots from a declarative JSON file.

This is the batch-pipeline wiring layer. The framework ships a complete
skeleton (``slots.DEFAULT_SLOTS``); an assembly file only says *what fills each
slot*. Nothing about the agent loop changes when a skill, MCP server, model or
memory implementation is swapped.

Binding kinds
-------------
``builtin``    one of the framework's fallbacks (``unbound``, ``sqlite``, ...)
``module``     ``package.module:attribute``; config is passed as keyword args
``path``       a ``.py`` file with the same rule as ``module``
``mcp_stdio``  spawn an MCP server and expose its tools (``tools`` slot only)
``skill_dir``  load every ``*/SKILL.md`` under a directory (``skills`` slot)

Relative paths resolve against the assembly file's directory.
"""

from __future__ import annotations

import dataclasses
import importlib
import importlib.util
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from expert_pack.adapters.mcp_stdio import McpToolProvider
from expert_pack.adapters.model_scripted import ScriptedModel
from expert_pack.adapters.model_stub import UnboundModel
from expert_pack.adapters.skills import load_skill_directory
from expert_pack.agent import AgentConfig, ExpertAgent
from expert_pack.contracts import check_contract
from expert_pack.errors import AssemblyError, ContractError, VacancyError
from expert_pack.jitrl.advantage import AdvantageConfig
from expert_pack.jitrl.evaluator import (
    FallbackEvaluator,
    HeuristicConfig,
    HeuristicEvaluator,
    LlmEvaluator,
)
from expert_pack.jitrl.memory import NullStore, SqliteExperienceStore
from expert_pack.jitrl.policy import JitrlPolicy
from expert_pack.jitrl.retrieval import JaccardRetriever, RetrievalConfig
from expert_pack.jitrl.state import AbstractorConfig, DefaultAbstractor
from expert_pack.slots import Binding, SlotRegistry, SlotSpec, VacancyReport

_ENV = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_KINDS = {"builtin", "module", "path", "mcp_stdio", "skill_dir"}


@dataclass
class Assembly:
    version: int = 1
    name: str = "defaults"
    agent: dict[str, Any] = field(default_factory=dict)
    bindings: list[Binding] = field(default_factory=list)
    source: str = "(built-in defaults)"
    base_dir: str = "."

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "name": self.name,
            "agent": dict(self.agent),
            "bindings": [
                {
                    "slot": b.slot,
                    "type": b.kind,
                    "target": b.target,
                    "config": dict(b.config),
                    "quality": b.quality,
                }
                for b in self.bindings
            ],
        }


@dataclass
class Runtime:
    assembly: Assembly
    report: VacancyReport
    model: Any
    tools: list[Any]
    skills: list[Any]
    store: Any
    retriever: Any
    abstractor: Any
    policy: Any
    evaluator: Any
    agent: ExpertAgent
    config: AgentConfig
    run_id: str

    def close(self) -> None:
        for provider in self.tools:
            close = getattr(provider, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # noqa: BLE001 - best-effort teardown
                    pass
        for component in (self.store, self.model):
            close = getattr(component, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # noqa: BLE001
                    pass


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in os.environ:
                raise AssemblyError(f"environment variable {name!r} is not set")
            return os.environ[name]

        return _ENV.sub(replace, value)
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand_env(item) for key, item in value.items()}
    return value


def load_assembly(path: str | Path) -> Assembly:
    target = Path(path).expanduser()
    if not target.is_file():
        raise AssemblyError(f"assembly file not found: {target}")
    text = target.read_text(encoding="utf-8")
    suffix = target.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError as exc:
            raise AssemblyError(
                "YAML assembly files need PyYAML; use JSON or install pyyaml"
            ) from exc
        raw = yaml.safe_load(text)
    else:
        try:
            raw = json.loads(text)
        except ValueError as exc:
            raise AssemblyError(f"{target} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise AssemblyError(f"{target} must contain a JSON object")
    base_dir = target.parent

    version = raw.get("version", 1)
    if version != 1:
        raise AssemblyError(f"unsupported assembly version {version!r}; expected 1")
    name = str(raw.get("name") or target.stem)
    agent = raw.get("agent") or {}
    if not isinstance(agent, dict):
        raise AssemblyError("'agent' must be an object")

    allowed_agent = {f.name for f in dataclasses.fields(AgentConfig)}
    unknown_agent = set(agent) - allowed_agent
    if unknown_agent:
        raise AssemblyError(
            f"unknown agent options: {sorted(unknown_agent)}; allowed: {sorted(allowed_agent)}"
        )

    raw_bindings = raw.get("bindings") or []
    if not isinstance(raw_bindings, list):
        raise AssemblyError("'bindings' must be a list")
    bindings: list[Binding] = []
    for index, item in enumerate(raw_bindings):
        if not isinstance(item, dict):
            raise AssemblyError(f"binding #{index} is not an object")
        slot = item.get("slot")
        kind = item.get("type") or item.get("kind")
        target_value = item.get("target") or item.get("id")
        if not isinstance(slot, str) or not slot:
            raise AssemblyError(f"binding #{index}: missing 'slot'")
        if not isinstance(kind, str) or kind not in _KINDS:
            raise AssemblyError(
                f"binding #{index}: 'type' must be one of {sorted(_KINDS)}"
            )
        if not isinstance(target_value, str) or not target_value:
            raise AssemblyError(f"binding #{index}: missing 'target'")
        config = _expand_env(item.get("config") or {})
        if not isinstance(config, dict):
            raise AssemblyError(f"binding #{index}: 'config' must be an object")
        quality = item.get("quality")
        if quality is None:
            if kind == "builtin" and target_value == "unbound":
                quality = "stub"
            elif kind == "builtin" and target_value in {
                "scripted",
                "null",
                "heuristic",
                "single_static_similarity",
            }:
                quality = "demo"
            else:
                quality = "production"
        bindings.append(
            Binding(
                slot=slot,
                kind=kind,
                target=_expand_env(target_value),
                config=config,
                quality=str(quality),
                source=str(target),
            )
        )
    return Assembly(
        version=1,
        name=name,
        agent=dict(agent),
        bindings=bindings,
        source=str(target),
        base_dir=str(base_dir),
    )


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #


def _load_module_attr(target: str) -> Any:
    if ":" not in target:
        raise AssemblyError(
            f"target {target!r} must look like 'package.module:attribute'"
        )
    module_name, attribute = target.split(":", 1)
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:  # noqa: BLE001
        raise AssemblyError(f"cannot import {module_name!r}: {exc}") from exc
    if not hasattr(module, attribute):
        raise AssemblyError(f"{module_name!r} has no attribute {attribute!r}")
    return getattr(module, attribute)


def _load_path(path: Path) -> Any:
    if not path.is_file():
        raise AssemblyError(f"binding file not found: {path}")
    module_name = f"expert_pack_binding_{abs(hash(str(path.resolve()))) % 10**8}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise AssemblyError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001
        sys.modules.pop(module_name, None)
        raise AssemblyError(f"{path} failed to import: {exc}") from exc
    return module


def _instantiate(obj: Any, config: Mapping[str, Any], describe: str) -> Any:
    if not config:
        return obj
    if not callable(obj):
        raise AssemblyError(
            f"{describe} was given config but is not callable; "
            "bind a factory function or drop 'config'"
        )
    try:
        return obj(**dict(config))
    except TypeError as exc:
        raise AssemblyError(f"{describe}: factory rejected config: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise AssemblyError(f"{describe}: factory raised {type(exc).__name__}: {exc}") from exc


def _builtin(name: str, config: Mapping[str, Any], spec: SlotSpec, values: Mapping[str, Any]) -> tuple[Any, str]:
    if name == "unbound":
        return UnboundModel(), "stub"
    if name == "scripted":
        allowed = {"planner", "responses", "name", "seed"}
        unknown = set(config) - allowed
        if unknown:
            raise AssemblyError(f"builtin scripted: unknown keys {sorted(unknown)}")
        planner = config.get("planner")
        if planner == "demo":
            from expert_pack.builtin.demo import DemoPlanner

            return DemoPlanner(), "stub"
        responses = config.get("responses")
        if isinstance(responses, list) and all(isinstance(item, str) for item in responses):
            return ScriptedModel(responses, name=str(config.get("name") or "scripted")), "stub"
        raise AssemblyError(
            "builtin scripted needs {'planner': 'demo'} or a list of {'responses': [...]}"
        )
    if name == "sqlite":
        allowed = {"path", "max_records"}
        unknown = set(config) - allowed
        if unknown:
            raise AssemblyError(f"builtin sqlite: unknown keys {sorted(unknown)}")
        path = str(config.get("path") or ".expert_pack/memory.sqlite3")
        return SqliteExperienceStore(path, max_records=int(config.get("max_records", 200_000))), "production"
    if name == "null":
        return NullStore(), "demo"
    if name == "jitrl":
        allowed = {f.name for f in dataclasses.fields(AdvantageConfig)} | {"seed"}
        unknown = set(config) - allowed
        if unknown:
            raise AssemblyError(f"builtin jitrl: unknown keys {sorted(unknown)}")
        seed = config.get("seed")
        adv = AdvantageConfig(**{k: v for k, v in config.items() if k != "seed"})
        return JitrlPolicy(adv, seed=int(seed) if seed is not None else None), "production"
    if name == "heuristic":
        allowed = {f.name for f in dataclasses.fields(HeuristicConfig)}
        unknown = set(config) - allowed
        if unknown:
            raise AssemblyError(f"builtin heuristic: unknown keys {sorted(unknown)}")
        return HeuristicEvaluator(HeuristicConfig(**dict(config))), "demo"
    if name == "llm":
        model = values.get("model")
        if model is None:
            raise AssemblyError("builtin llm evaluator needs the model slot to resolve first")
        fallback = HeuristicEvaluator()
        return (
            FallbackEvaluator(
                LlmEvaluator(model, temperature=float(config.get("temperature", 0.0))),
                fallback,
            ),
            "production",
        )
    if name == "default":
        allowed = {f.name for f in dataclasses.fields(AbstractorConfig)}
        unknown = set(config) - allowed
        if unknown:
            raise AssemblyError(f"builtin default abstractor: unknown keys {sorted(unknown)}")
        return DefaultAbstractor(AbstractorConfig(**dict(config))), "production"
    if name == "jaccard":
        allowed = {f.name for f in dataclasses.fields(RetrievalConfig)}
        unknown = set(config) - allowed
        if unknown:
            raise AssemblyError(f"builtin jaccard: unknown keys {sorted(unknown)}")
        return JaccardRetriever(RetrievalConfig(**dict(config))), "production"
    raise AssemblyError(f"unknown builtin {name!r}")


def _resolve_binding(binding: Binding, spec: SlotSpec, values: Mapping[str, Any], base_dir: Path) -> Any:
    if binding.kind == "builtin":
        value, _quality = _builtin(binding.target, binding.config, spec, values)
        return value
    if binding.kind == "module":
        obj = _load_module_attr(binding.target)
        return _instantiate(obj, binding.config, binding.target)
    if binding.kind == "path":
        path = Path(binding.target)
        if not path.is_absolute():
            path = base_dir / path
        module = _load_path(path)
        name = path.stem
        if not hasattr(module, name):
            raise AssemblyError(
                f"{path} must define '{name}' (or use type 'module' to name the attribute)"
            )
        return _instantiate(getattr(module, name), binding.config, str(path))
    if binding.kind == "mcp_stdio":
        if spec.id != "tools":
            raise AssemblyError("mcp_stdio bindings are only valid for the 'tools' slot")
        allowed = {"command", "args", "env", "cwd", "timeout"}
        unknown = set(binding.config) - allowed
        if unknown:
            raise AssemblyError(f"mcp_stdio: unknown keys {sorted(unknown)}")
        command = binding.config.get("command")
        if not command:
            raise AssemblyError("mcp_stdio needs 'command' in config")
        args = binding.config.get("args") or []
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            raise AssemblyError("mcp_stdio 'args' must be a list of strings")
        env = binding.config.get("env") or {}
        if not isinstance(env, dict):
            raise AssemblyError("mcp_stdio 'env' must be an object")
        cwd = binding.config.get("cwd")
        if cwd:
            cwd_path = Path(str(cwd))
            if not cwd_path.is_absolute():
                cwd_path = base_dir / cwd_path
            cwd = str(cwd_path)
        return McpToolProvider(
            binding.target,
            command,
            args,
            cwd=cwd,
            env=env,
            timeout=float(binding.config.get("timeout", 20.0)),
        )
    if binding.kind == "skill_dir":
        if spec.id != "skills":
            raise AssemblyError("skill_dir bindings are only valid for the 'skills' slot")
        if binding.config:
            raise AssemblyError("skill_dir takes no config; use 'target' for the directory")
        path = Path(binding.target)
        if not path.is_absolute():
            path = base_dir / path
        return load_skill_directory(path)
    raise AssemblyError(f"unsupported binding kind {binding.kind!r}")


# --------------------------------------------------------------------------- #
# Runtime construction
# --------------------------------------------------------------------------- #


def build_runtime(
    assembly: Assembly | None = None,
    *,
    base_dir: str | Path | None = None,
    overrides: Mapping[str, Any] | None = None,
    strict: bool = False,
    run_id: str = "run",
) -> Runtime:
    assembly = assembly or Assembly()
    if base_dir is not None:
        root = Path(base_dir)
    elif assembly.base_dir:
        root = Path(assembly.base_dir)
    else:
        root = Path.cwd()
    registry = SlotRegistry()
    for binding in assembly.bindings:
        registry.bind(binding)

    report = registry.resolve(
        lambda binding, spec, values: _resolve_binding(binding, spec, values, root),
        lambda name, config, spec, values: _builtin(name, config, spec, values),
        overrides=overrides,
        order=["model", "abstractor", "retriever", "store", "policy", "evaluator", "tools", "skills"],
    )
    if strict:
        problems = report.strict_problems()
        if problems:
            raise VacancyError(
                "strict assembly failed:\n  - " + "\n  - ".join(problems) + "\n\n" + report.table()
            )

    model = report.state("model").value
    if model is None:
        raise VacancyError(
            "the model slot is vacant; bind it in the assembly file or run `expert-pack slots`.\n\n"
            + report.table()
        )
    store = report.state("store").value
    if store is None:
        store = NullStore()
    policy = report.state("policy").value or JitrlPolicy()
    config = AgentConfig(**assembly.agent)
    if config.seed is not None and hasattr(policy, "reseed"):
        policy.reseed(config.seed)

    components = {
        "model": model,
        "tools": report.state("tools").value or [],
        "skills": report.state("skills").value or [],
        "store": store,
        "retriever": report.state("retriever").value,
        "abstractor": report.state("abstractor").value,
        "policy": policy,
        "evaluator": report.state("evaluator").value,
    }
    for slot, component in components.items():
        if component is None:
            raise VacancyError(f"slot {slot!r} resolved to nothing")
        contract = report.state(slot).spec.contract
        problems = check_contract(contract, component) if not isinstance(component, list) else []
        if problems:
            raise ContractError(f"slot {slot!r} does not satisfy {contract}: {problems}")

    try:
        agent = ExpertAgent(**components, config=config, run_id=run_id)
    except ContractError as exc:
        raise AssemblyError(str(exc)) from exc
    return Runtime(
        assembly=assembly,
        report=report,
        model=model,
        tools=list(components["tools"]),
        skills=list(components["skills"]),
        store=store,
        retriever=components["retriever"],
        abstractor=components["abstractor"],
        policy=policy,
        evaluator=components["evaluator"],
        agent=agent,
        config=config,
        run_id=run_id,
    )


def inspect_assembly(path: str | Path) -> tuple[Assembly, VacancyReport]:
    assembly = load_assembly(path)
    registry = SlotRegistry()
    for binding in assembly.bindings:
        registry.bind(binding)
    report = registry.resolve(
        lambda binding, spec, values: _resolve_binding(binding, spec, values, Path(assembly.base_dir)),
        lambda name, config, spec, values: _builtin(name, config, spec, values),
        order=["model", "abstractor", "retriever", "store", "policy", "evaluator", "tools", "skills"],
    )
    return assembly, report


def default_assembly() -> Assembly:
    return Assembly()
