"""The non-parametric experience store: ``<state, action, return>`` triplets.

Mirrors JitRL's dynamic memory bank, with two practical differences:

* SQLite instead of a vector index, so memory survives process restarts on any
  machine without a service or an embedding model;
* tokens are stored per transition, so retrieval is a pure function that can be
  swapped (``retriever`` slot) without touching storage.

Writes are per episode, never per step: the return of a step is only known after
the episode is evaluated, which is the JitRL memory-update stream.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Sequence

from expert_pack.contracts import EpisodeRecord, Transition

_SCHEMA = """
CREATE TABLE IF NOT EXISTS transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    family TEXT NOT NULL,
    step INTEGER NOT NULL,
    state_key TEXT NOT NULL,
    state_text TEXT NOT NULL,
    tokens TEXT NOT NULL,
    action_id TEXT NOT NULL,
    action_name TEXT NOT NULL,
    arguments TEXT NOT NULL,
    ret REAL NOT NULL,
    success INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    meta TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_transitions_state_key ON transitions(state_key);
CREATE INDEX IF NOT EXISTS idx_transitions_action ON transitions(action_id);

CREATE TABLE IF NOT EXISTS episodes (
    episode_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    family TEXT NOT NULL,
    success INTEGER NOT NULL,
    score REAL NOT NULL,
    steps INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    meta TEXT NOT NULL DEFAULT '{}'
);
"""


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _load(raw: str) -> object:
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {}


class SqliteExperienceStore:
    """Default ``ExperienceStore``. Safe to share inside one process."""

    def __init__(self, path: str | Path, *, max_records: int = 200_000) -> None:
        self._lock = threading.RLock()
        self._revision = 0
        self._cache_revision = -1
        self._cache: list[Transition] = []
        self.max_records = max_records
        if str(path) == ":memory:":
            self.path = ":memory:"
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        else:
            target = Path(path).expanduser()
            target.parent.mkdir(parents=True, exist_ok=True)
            self.path = str(target.resolve())
            self._conn = sqlite3.connect(self.path, timeout=10.0, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # -- writes ------------------------------------------------------------ #

    def write_episode(self, episode: EpisodeRecord, transitions: Sequence[Transition]) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "INSERT OR REPLACE INTO episodes"
                "(episode_id, task_id, family, success, score, steps, created_at, meta)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (
                    episode.episode_id,
                    episode.task_id,
                    episode.family,
                    int(episode.success),
                    float(episode.score),
                    int(episode.steps),
                    episode.created_at,
                    _dump(episode.meta),
                ),
            )
            cur.executemany(
                "INSERT INTO transitions"
                "(episode_id, task_id, family, step, state_key, state_text, tokens,"
                " action_id, action_name, arguments, ret, success, created_at, meta)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        t.episode_id,
                        t.task_id,
                        t.family,
                        t.step,
                        t.state_key,
                        t.state_text,
                        _dump(list(t.tokens)),
                        t.action_id,
                        t.action_name,
                        _dump(t.arguments),
                        float(t.ret),
                        int(t.success),
                        t.created_at,
                        _dump(t.meta),
                    )
                    for t in transitions
                ],
            )
            if self.max_records > 0:
                total = cur.execute("SELECT COUNT(*) FROM transitions").fetchone()[0]
                if total > self.max_records:
                    cutoff = total - self.max_records
                    cur.execute(
                        "DELETE FROM transitions WHERE id IN "
                        "(SELECT id FROM transitions ORDER BY id ASC LIMIT ?)",
                        (cutoff,),
                    )
            self._conn.commit()
            self._revision += 1

    def clear(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM transitions")
            self._conn.execute("DELETE FROM episodes")
            self._conn.commit()
            self._revision += 1

    # -- reads ------------------------------------------------------------- #

    def transitions(self) -> Sequence[Transition]:
        with self._lock:
            if self._cache_revision == self._revision:
                return list(self._cache)
            rows = self._conn.execute(
                "SELECT episode_id, task_id, family, step, state_key, state_text, tokens,"
                " action_id, action_name, arguments, ret, success, created_at, meta"
                " FROM transitions ORDER BY id ASC"
            ).fetchall()
            parsed: list[Transition] = []
            for row in rows:
                tokens = _load(row[6])
                arguments = _load(row[9])
                meta = _load(row[13])
                parsed.append(
                    Transition(
                        episode_id=row[0],
                        task_id=row[1],
                        family=row[2],
                        step=int(row[3]),
                        state_key=row[4],
                        state_text=row[5],
                        tokens=tuple(tokens) if isinstance(tokens, list) else (),
                        action_id=row[7],
                        action_name=row[8],
                        arguments=arguments if isinstance(arguments, dict) else {},
                        ret=float(row[10]),
                        success=bool(row[11]),
                        created_at=row[12],
                        meta=meta if isinstance(meta, dict) else {},
                    )
                )
            self._cache = parsed
            self._cache_revision = self._revision
            return list(parsed)

    def stats(self) -> dict:
        with self._lock:
            episodes = self._conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
            transitions = self._conn.execute("SELECT COUNT(*) FROM transitions").fetchone()[0]
            wins = self._conn.execute("SELECT COUNT(*) FROM episodes WHERE success=1").fetchone()[0]
            actions = self._conn.execute(
                "SELECT action_id, COUNT(*) c, AVG(ret) r FROM transitions GROUP BY action_id ORDER BY c DESC LIMIT 12"
            ).fetchall()
            size = 0
            if self.path != ":memory:":
                try:
                    size = Path(self.path).stat().st_size
                except OSError:
                    size = 0
            return {
                "path": self.path,
                "episodes": int(episodes),
                "transitions": int(transitions),
                "success_rate": (float(wins) / episodes) if episodes else 0.0,
                "actions": [
                    {"action_id": row[0], "count": int(row[1]), "mean_return": float(row[2])}
                    for row in actions
                ],
                "bytes": int(size),
            }

    def episodes(self) -> Sequence[EpisodeRecord]:
        """Episode metadata (not part of the minimal store contract, but useful)."""

        with self._lock:
            rows = self._conn.execute(
                "SELECT episode_id, task_id, family, success, score, steps, created_at, meta"
                " FROM episodes ORDER BY created_at ASC"
            ).fetchall()
        records: list[EpisodeRecord] = []
        for row in rows:
            meta = _load(row[7])
            records.append(
                EpisodeRecord(
                    episode_id=row[0],
                    task_id=row[1],
                    family=row[2],
                    success=bool(row[3]),
                    score=float(row[4]),
                    steps=int(row[5]),
                    created_at=row[6],
                    meta=meta if isinstance(meta, dict) else {},
                )
            )
        return records

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass


class NullStore:
    """A store that remembers nothing: the no-memory baseline arm."""

    path = "(disabled)"
    name = "null"

    def write_episode(self, episode: EpisodeRecord, transitions: Sequence[Transition]) -> None:
        return None

    def transitions(self) -> Sequence[Transition]:
        return []

    def stats(self) -> dict:
        return {
            "path": self.path,
            "episodes": 0,
            "transitions": 0,
            "success_rate": 0.0,
            "actions": [],
            "bytes": 0,
            "enabled": False,
        }

    def clear(self) -> None:
        return None

    def close(self) -> None:
        return None
