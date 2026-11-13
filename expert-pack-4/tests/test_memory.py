from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from expert_pack.contracts import EpisodeRecord
from expert_pack.jitrl.memory import NullStore, SqliteExperienceStore
from tests.helpers import make_transition


def episode(episode_id: str = "e1", success: bool = True) -> EpisodeRecord:
    return EpisodeRecord(
        episode_id=episode_id,
        task_id="t1",
        family="fam",
        success=success,
        score=1.0 if success else 0.0,
        steps=2,
        created_at="2026-01-01T00:00:00+00:00",
        meta={"evaluator": "heuristic"},
    )


class MemoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "memory.sqlite3"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_roundtrip_and_reload(self) -> None:
        store = SqliteExperienceStore(self.path)
        store.write_episode(
            episode(),
            [
                make_transition(action="tool:x/a", ret=1.0, step=0),
                make_transition(action="answer", ret=0.5, step=1),
            ],
        )
        stats = store.stats()
        self.assertEqual(stats["episodes"], 1)
        self.assertEqual(stats["transitions"], 2)
        self.assertEqual(stats["success_rate"], 1.0)
        store.close()

        reopened = SqliteExperienceStore(self.path)
        rows = reopened.transitions()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].tokens, ("obs",))
        self.assertEqual(rows[0].arguments, {})
        self.assertEqual(rows[1].action_id, "answer")
        self.assertEqual(reopened.episodes()[0].episode_id, "e1")
        reopened.close()

    def test_pruning_keeps_newest(self) -> None:
        store = SqliteExperienceStore(self.path, max_records=2)
        store.write_episode(episode("e1"), [make_transition(action="a", ret=1)])
        store.write_episode(
            episode("e2"), [make_transition(action="b", ret=2), make_transition(action="c", ret=3)]
        )
        rows = store.transitions()
        self.assertEqual(len(rows), 2)
        self.assertEqual([row.action_id for row in rows], ["b", "c"])
        store.close()

    def test_clear(self) -> None:
        store = SqliteExperienceStore(self.path)
        store.write_episode(episode(), [make_transition()])
        store.clear()
        self.assertEqual(store.stats()["transitions"], 0)
        self.assertEqual(store.stats()["episodes"], 0)
        store.close()

    def test_null_store(self) -> None:
        store = NullStore()
        store.write_episode(episode(), [make_transition()])
        self.assertEqual(store.transitions(), [])
        self.assertEqual(store.stats()["transitions"], 0)
        self.assertFalse(store.stats()["enabled"])


if __name__ == "__main__":
    unittest.main()
