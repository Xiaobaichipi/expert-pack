from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from expert_pack.adapters.model_scripted import ScriptedModel
from expert_pack.contracts import ToolResult
from expert_pack.trajectory.replay import TreeReplayer, find_branches


class FakeProvider:
    name = "fake"

    def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(ok=True, content=json.dumps({"tool": name, "arguments": arguments}))


def records():
    return [
        {
            "type": "episode",
            "episodeId": "e1",
            "taskId": "t1",
            "goal": "answer yes",
            "family": "f",
            "success": True,
            "answer": "yes",
            "context": {"expect": "yes"},
            "meta": {"dataset": "base"},
        },
        {"type": "node", "nodeId": "e1:root", "episodeId": "e1", "parentId": None,
         "step": -1, "kind": "root", "goal": "answer yes"},
        {
            "type": "node", "nodeId": "e1:0", "episodeId": "e1", "parentId": "e1:root",
            "step": 0, "kind": "step",
            "state": {"key": "k", "text": "start", "tokens": [], "facets": {}},
            "observation": {"kind": "start", "ok": True, "text": "", "data": {}},
            "selected": {"actionId": "answer", "kind": "answer", "name": "answer",
                         "arguments": {"answer": "yes"}, "baseScore": 0.0},
            "candidates": [],
            "alternatives": [
                {"actionId": "tool:fake/lookup", "kind": "tool", "name": "lookup",
                 "arguments": {"item": "x"}, "baseScore": -0.1}
            ],
        },
    ]


class TreeReplayTest(unittest.TestCase):
    def test_replay_alternative_and_write_memory(self) -> None:
        data = records()
        branches = find_branches(data)
        self.assertEqual(len(branches), 1)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "replays.jsonl"
            memory = Path(tmp) / "memory.sqlite3"
            outcome = TreeReplayer(FakeProvider()).replay(
                data, branches[0], out_path=str(out), memory_path=str(memory)
            )
            self.assertTrue(outcome.success)
            self.assertTrue(outcome.memory_written)
            self.assertTrue(out.is_file())
            self.assertTrue(memory.is_file())
            written = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(written["alternative"]["actionId"], "tool:fake/lookup")

    def test_model_rollout_after_branch(self) -> None:
        data = records()
        branches = find_branches(data)
        model = ScriptedModel(
            ['{"candidates":[{"action":"answer","arguments":{"answer":"yes"},"confidence":0.9}]}']
        )
        outcome = TreeReplayer(FakeProvider()).replay(
            data, branches[0], rollout_model=model
        )
        self.assertTrue(outcome.success)
        self.assertEqual(outcome.record["rollout"], "model")
        self.assertEqual(outcome.steps, 2)


if __name__ == "__main__":
    unittest.main()
