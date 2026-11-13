"""Batch pipeline with per-item checkpoints.

The agent loop is one stage, not the whole program: a run is a list of tasks
moved through ``prepare -> solve -> record``, each stage a function that can be
retried independently. Checkpoints make a long batch resumable after a crash,
and per-item isolation means one bad task cannot take down the rest.

Stages are plain callables, so the assembly agent can add one without changing
this module: stage-level behaviour is code, slot-level behaviour is assembly.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass
class BatchItem:
    id: str
    payload: dict[str, Any] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)
    completed: list[str] = field(default_factory=list)
    error: str | None = None
    status: str = "pending"  # pending | done | failed

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "payload": self.payload,
            "data": self.data,
            "completed": list(self.completed),
            "error": self.error,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "BatchItem":
        return cls(
            id=str(raw.get("id", "")),
            payload=dict(raw.get("payload") or {}),
            data=dict(raw.get("data") or {}),
            completed=[str(x) for x in raw.get("completed") or []],
            error=raw.get("error"),
            status=str(raw.get("status", "pending")),
        )


@dataclass
class Stage:
    id: str
    run: Callable[["PipelineContext", BatchItem], BatchItem | None]
    on_error: str = "skip"  # "skip" the item or "continue" to the next stage
    optional: bool = False


@dataclass
class PipelineContext:
    run_id: str
    state_dir: Path | None = None
    runtime: Any = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineReport:
    items: list[BatchItem]
    resumed: list[str] = field(default_factory=list)

    @property
    def done(self) -> list[BatchItem]:
        return [item for item in self.items if item.status == "done"]

    @property
    def failed(self) -> list[BatchItem]:
        return [item for item in self.items if item.status == "failed"]

    def summary(self) -> dict[str, Any]:
        return {
            "total": len(self.items),
            "done": len(self.done),
            "failed": len(self.failed),
            "resumed": len(self.resumed),
            "failed_ids": [item.id for item in self.failed],
        }


class BatchPipeline:
    def __init__(self, stages: Sequence[Stage], *, state_dir: str | Path | None = None) -> None:
        if not stages:
            raise ValueError("a pipeline needs at least one stage")
        ids = [stage.id for stage in stages]
        if len(set(ids)) != len(ids):
            raise ValueError(f"stage ids must be unique: {ids}")
        self.stages = list(stages)
        self.state_dir = Path(state_dir) if state_dir else None
        if self.state_dir:
            (self.state_dir / "items").mkdir(parents=True, exist_ok=True)

    # -- checkpoints ------------------------------------------------------- #

    def _checkpoint_path(self, item_id: str) -> Path | None:
        if not self.state_dir:
            return None
        safe = _SAFE.sub("_", item_id) or "item"
        return self.state_dir / "items" / f"{safe}.json"

    def _load_checkpoint(self, item: BatchItem) -> BatchItem | None:
        path = self._checkpoint_path(item.id)
        if path is None or not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            return None
        restored = BatchItem.from_dict(raw)
        restored.payload = item.payload or restored.payload
        return restored

    def _save_checkpoint(self, item: BatchItem) -> None:
        path = self._checkpoint_path(item.id)
        if path is None:
            return
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(item.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(path)

    # -- execution --------------------------------------------------------- #

    def run(self, items: Sequence[BatchItem], context: PipelineContext, *, resume: bool = False) -> PipelineReport:
        context.state_dir = self.state_dir
        resumed: list[str] = []
        processed: list[BatchItem] = []
        for original in items:
            item = original
            if resume:
                restored = self._load_checkpoint(item)
                if restored is not None:
                    restored.payload = original.payload or restored.payload
                    item = restored
                    if item.status == "done":
                        resumed.append(item.id)
                        processed.append(item)
                        continue
                    item.error = None
                    item.status = "pending"
                    resumed.append(item.id)
            for stage in self.stages:
                if stage.id in item.completed:
                    continue
                try:
                    result = stage.run(context, item)
                    if result is not None:
                        item = result
                    item.completed.append(stage.id)
                    # A retried stage that now succeeds clears its own failure.
                    if item.error and item.error.startswith(f"{stage.id}:"):
                        item.error = None
                except Exception as exc:  # noqa: BLE001 - per-item isolation
                    item.error = f"{stage.id}: {type(exc).__name__}: {exc}"
                    item.status = "failed"
                    self._save_checkpoint(item)
                    if stage.on_error == "skip":
                        break
                finally:
                    if item.status != "failed":
                        self._save_checkpoint(item)
            if item.status != "failed" and not item.error:
                item.status = "done"
            self._save_checkpoint(item)
            processed.append(item)
        return PipelineReport(items=processed, resumed=resumed)
