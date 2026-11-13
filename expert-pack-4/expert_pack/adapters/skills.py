"""Skill loading: ``SKILL.md`` directories, with an optional ``skill.py``.

A skill is both a routing hint and, optionally, an executable capability:

* prompt-only (no ``skill.py``): selecting it loads its instructions into the
  agent context, exactly like a Claude/Agent Skill manual;
* executable (``skill.py`` with ``run(context, arguments)``): selecting it
  calls the function and feeds the result back as an observation.

Frontmatter is a deliberately small YAML subset (flat ``key: value`` plus
``|``/``>`` blocks) so the package needs no YAML dependency to load skills.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

from expert_pack.contracts import SkillContext, SkillResult, SkillSpec
from expert_pack.errors import AssemblyError

_KEY = re.compile(r"^([A-Za-z0-9_.-]+):\s*(.*)$")


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Return (metadata, body). Missing or malformed frontmatter is not fatal."""

    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    header = text[3:end]
    body = text[end + 4 :].lstrip("\n")
    data: dict[str, Any] = {}
    lines = header.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        match = _KEY.match(line)
        if not match:
            index += 1
            continue
        key, value = match.group(1), match.group(2).strip()
        if value in {"|", ">", "|-", ">-"}:
            block: list[str] = []
            index += 1
            while index < len(lines) and (not lines[index].strip() or lines[index][:1] in {" ", "\t"}):
                block.append(lines[index].strip())
                index += 1
            separator = "\n" if value.startswith("|") else " "
            data[key] = separator.join(block).strip()
            continue
        data[key] = _strip_quotes(value)
        index += 1
    return data, body


def _coerce_result(value: Any) -> SkillResult:
    if isinstance(value, SkillResult):
        return value
    if isinstance(value, dict):
        known = {
            "ok": bool(value.get("ok", True)),
            "content": str(value.get("content", "")),
            "error": value.get("error"),
            "kind": str(value.get("kind", "output")),
            "data": value.get("data") if isinstance(value.get("data"), dict) else None,
        }
        return SkillResult(**known)
    if value is None:
        return SkillResult(ok=True, content="")
    return SkillResult(ok=True, content=str(value))


class BookSkill:
    """A loaded skill. ``runner`` is None for prompt-only skills."""

    def __init__(self, spec: SkillSpec, runner: Callable[[SkillContext, Mapping[str, Any]], Any] | None = None) -> None:
        self.spec = spec
        self._runner = runner

    def run(self, context: SkillContext, arguments: Mapping[str, Any]) -> SkillResult:
        if self._runner is None:
            return SkillResult(
                ok=True,
                kind="instructions",
                content=self.spec.instructions,
                data={"skill": self.spec.name, "mode": "instructions"},
            )
        try:
            return _coerce_result(self._runner(context, dict(arguments)))
        except Exception as exc:  # noqa: BLE001 - surfaced as a failed action
            return SkillResult(ok=False, content="", error=f"skill runner raised: {exc}")


def _load_runner(path: Path) -> tuple[Callable[[SkillContext, Mapping[str, Any]], Any], Any]:
    module_name = f"expert_pack_skill_{re.sub(r'[^A-Za-z0-9_]', '_', path.parent.name)}_{abs(hash(str(path))) % 10**8}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise AssemblyError(f"cannot load skill module at {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001
        sys.modules.pop(module_name, None)
        raise AssemblyError(f"skill module {path} failed to import: {exc}") from exc
    runner = getattr(module, "run", None)
    if not callable(runner):
        raise AssemblyError(f"skill module {path} must define run(context, arguments)")
    return runner, module


def load_skill_dir(path: str | Path) -> BookSkill:
    directory = Path(path)
    manifest = directory / "SKILL.md"
    if not manifest.is_file():
        raise AssemblyError(f"no SKILL.md in {directory}")
    text = manifest.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(text)
    name = str(meta.get("name") or directory.name).strip()
    description = str(meta.get("description") or "").strip()
    if not description:
        first = next((line.strip("# ").strip() for line in body.splitlines() if line.strip()), "")
        description = first[:160]
    when = str(meta.get("when_to_use") or meta.get("when-to-use") or "").strip()
    runner = None
    module_path = directory / "skill.py"
    if module_path.is_file():
        runner, module = _load_runner(module_path)
        module_spec = getattr(module, "SPEC", None)
        if isinstance(module_spec, dict):
            desc_override = module_spec.get("description")
            if desc_override:
                description = str(desc_override)
    spec = SkillSpec(
        name=name,
        description=description,
        when_to_use=when,
        instructions=body.strip(),
        metadata={k: v for k, v in meta.items() if k not in {"name", "description", "when_to_use", "when-to-use"}},
    )
    return BookSkill(spec, runner)


def load_skill_directory(path: str | Path) -> list[BookSkill]:
    root = Path(path)
    if not root.exists():
        raise AssemblyError(f"skill directory does not exist: {root}")
    skills: list[BookSkill] = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / "SKILL.md").is_file():
            skills.append(load_skill_dir(child))
    return skills
