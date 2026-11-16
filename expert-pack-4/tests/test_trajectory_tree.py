from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from expert_pack.adapters.model_scripted import ScriptedModel
from expert_pack.agent import AgentConfig
from expert_pack.contracts import Task
from expert_pack.trajectory.tree_store import TrajectoryTreeStore, build_forest, load_records
from expert_pack.trajectory.visualize import text_tree
from tests.test_agent import build_agent


class TrajectoryTreeTest(unittest.TestCase):
    def test_record_preserves_all_candidates(self) -> None:
        agent = build_agent(
            config=AgentConfig(max_steps=2),
            model=ScriptedModel(
                [
                    '{"candidates":['
                    '{"action":"tool:fake/lookup","arguments":{"item":"alpha"},"confidence":0.6},'
                    '{"action":"tool:fake/calc","arguments":{"expression":"1+1"},"confidence":0.4}'
                    "]}",
                    '{"candidates":[{"action":"answer","arguments":{"answer":"42"},"confidence":0.9}]}',
                ]
            ),
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tree.jsonl"
            store = TrajectoryTreeStore(path)
            result = agent.solve(Task(id="t", goal="look up alpha", max_steps=2))
            store.record(result, {"provider": "test"})
            records = load_records(path)
            forest = build_forest(records)
            self.assertEqual(len(forest), 1)
            self.assertEqual(forest[0]["taskId"], "t")
            step_nodes = [
                item
                for item in records
                if item.get("type") == "node" and item.get("kind") == "step"
            ]
            self.assertEqual(len(step_nodes), len(result.trajectory.steps))
            first = step_nodes[0]
            self.assertEqual(first["selected"]["actionId"], result.trajectory.steps[0].selected.action_id)
            self.assertEqual(len(first["candidates"]), 2)
            self.assertEqual(len(first["alternatives"]), 1)
            self.assertIn("TASK t", text_tree(forest[0]))

    def test_forest_handles_empty_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            forest = build_forest(load_records(Path(tmp) / "missing.jsonl"))
            self.assertEqual(forest, [])


if __name__ == "__main__":
    unittest.main()
