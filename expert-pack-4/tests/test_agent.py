from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Sequence

from expert_pack.adapters.model_scripted import ScriptedModel
from expert_pack.agent import AgentConfig, ExpertAgent
from expert_pack.contracts import ModelMessage, ModelReply, Observation, Task
from expert_pack.jitrl.advantage import AdvantageConfig
from expert_pack.jitrl.evaluator import HeuristicEvaluator
from expert_pack.jitrl.memory import NullStore, SqliteExperienceStore
from expert_pack.jitrl.policy import JitrlPolicy
from expert_pack.jitrl.retrieval import JaccardRetriever
from expert_pack.jitrl.state import DefaultAbstractor
from tests.helpers import FakeTools


class PromptDrivenModel:
    """Chooses the action a test names in the prompt's task goal."""

    name = "test"

    def __init__(self, script: dict[str, list[str]]) -> None:
        self.script = script
        self.calls: list[list[ModelMessage]] = []

    def complete(
        self,
        messages: Sequence[ModelMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> ModelReply:
        self.calls.append(list(messages))
        prompt = messages[-1].content
        for key, actions in self.script.items():
            if key in prompt:
                candidates = [json.loads(item) for item in actions]
                return ModelReply(text=json.dumps({"candidates": candidates}))
        return ModelReply(text=json.dumps({"candidates": []}))


def build_agent(store=None, model=None, skills=None, config=None, seed=1) -> ExpertAgent:
    return ExpertAgent(
        model=model or ScriptedModel(['{"candidates":[{"action":"answer","arguments":{"answer":"1"},"confidence":0.9}]}']),
        tools=[FakeTools()],
        skills=skills or [],
        store=store or NullStore(),
        retriever=JaccardRetriever(),
        abstractor=DefaultAbstractor(),
        policy=JitrlPolicy(AdvantageConfig(min_similarity=0.4), seed=seed),
        evaluator=HeuristicEvaluator(),
        config=config or AgentConfig(max_steps=3),
        run_id="test",
    )


class AgentTest(unittest.TestCase):
    def test_actions_include_tools_skills_and_answer(self) -> None:
        agent = build_agent()
        ids = {item["action_id"] for item in agent.available_actions()}
        self.assertIn("tool:fake/lookup", ids)
        self.assertIn("tool:fake/calc", ids)
        self.assertIn("answer", ids)

    def test_unknown_action_is_repaired(self) -> None:
        model = ScriptedModel(
            [
                '{"candidates":[{"action":"tool:fake/nope","arguments":{}}]}',
                '{"candidates":[{"action":"answer","arguments":{"answer":"ok"},"confidence":0.8}]}',
            ]
        )
        agent = build_agent(model=model)
        result = agent.solve(Task(id="t", goal="g", max_steps=2))
        self.assertEqual(result.steps, 1)
        self.assertEqual(result.trajectory.answer_text(), "ok")
        self.assertEqual(len(model.calls), 2)
        self.assertIn("unknown action", model.calls[1][-1].content)

    def test_unparseable_proposal_falls_back_to_answer(self) -> None:
        model = ScriptedModel(["I refuse to answer in JSON."])
        agent = build_agent(model=model, config=AgentConfig(max_steps=2, repair_attempts=0))
        result = agent.solve(Task(id="t", goal="g", max_steps=2))
        self.assertEqual(result.steps, 1)
        self.assertEqual(result.trajectory.steps[0].selected.source, "fallback")

    def test_missing_required_arguments_are_rejected(self) -> None:
        model = ScriptedModel(
            [
                '{"candidates":[{"action":"tool:fake/lookup","arguments":{}}]}',
                '{"candidates":[{"action":"tool:fake/lookup","arguments":{"item":"alpha"}}]}',
                '{"candidates":[{"action":"answer","arguments":{"answer":"42"},"confidence":0.9}]}',
            ]
        )
        agent = build_agent(model=model, config=AgentConfig(max_steps=2, repair_attempts=1))
        result = agent.solve(Task(id="t", goal="g", max_steps=2))
        self.assertTrue(result.trajectory.steps[0].observation.ok)
        self.assertIn("missing required arguments", model.calls[1][-1].content)

    def test_suggested_actions_are_enforced(self) -> None:
        model = ScriptedModel(
            [
                '{"candidates":[{"action":"tool:fake/calc","arguments":{"expression":"1+1"}}]}',
                '{"candidates":[{"action":"tool:fake/lookup","arguments":{"item":"alpha"}}]}',
                '{"candidates":[{"action":"answer","arguments":{"answer":"42"},"confidence":0.9}]}',
            ]
        )
        task = Task(
            id="t",
            goal="look up alpha",
            max_steps=2,
            context={"suggestedActions": ["tool:fake/lookup"]},
        )
        agent = build_agent(
            model=model,
            config=AgentConfig(max_steps=2, repair_attempts=1, enforce_action_hints=True),
        )
        result = agent.solve(task)
        self.assertIn("SUGGESTED ACTIONS FOR THIS TASK", model.calls[0][-1].content)
        self.assertIn("not in task suggested actions", model.calls[1][-1].content)
        self.assertEqual(result.trajectory.steps[0].selected.action_id, "tool:fake/lookup")

    def test_unknown_arguments_are_rejected(self) -> None:
        model = ScriptedModel(
            [
                '{"candidates":[{"action":"tool:fake/lookup","arguments":{"item":"alpha","stationId":"STA-1"}}]}',
                '{"candidates":[{"action":"tool:fake/lookup","arguments":{"item":"alpha"}}]}',
                '{"candidates":[{"action":"answer","arguments":{"answer":"42"},"confidence":0.9}]}',
            ]
        )
        agent = build_agent(model=model, config=AgentConfig(max_steps=2, repair_attempts=1))
        result = agent.solve(Task(id="t", goal="g", max_steps=2))
        self.assertIn("unknown arguments", model.calls[1][-1].content)
        self.assertTrue(result.trajectory.steps[0].observation.ok)

    def test_tool_error_is_an_observation_not_a_crash(self) -> None:
        model = ScriptedModel(
            [
                '{"candidates":[{"action":"tool:fake/calc","arguments":{"expression":"7/0"}}]}',
                '{"candidates":[{"action":"answer","arguments":{"answer":"1"},"confidence":0.9}]}',
            ]
        )
        agent = build_agent(model=model, config=AgentConfig(max_steps=2))
        result = agent.solve(Task(id="t", goal="g", max_steps=2))
        self.assertFalse(result.trajectory.steps[0].observation.ok)
        self.assertEqual(result.steps, 2)
        self.assertEqual(result.trajectory.answer_text(), "1")

    def test_consecutive_errors_stop_the_episode(self) -> None:
        model = ScriptedModel(
            ['{"candidates":[{"action":"tool:fake/calc","arguments":{"expression":""}}]}'] * 3
        )
        agent = build_agent(
            model=model,
            config=AgentConfig(max_steps=3, max_consecutive_errors=2),
        )
        result = agent.solve(Task(id="t", goal="g", max_steps=3))
        self.assertEqual(result.steps, 2)
        self.assertIn("consecutive failed actions", " ".join(result.trajectory.notes))

    def test_expected_answer_sets_success_hint(self) -> None:
        model = ScriptedModel(
            ['{"candidates":[{"action":"answer","arguments":{"answer":"42"},"confidence":0.9}]}']
        )
        agent = build_agent(model=model, config=AgentConfig(max_steps=2))
        result = agent.solve(Task(id="t", goal="g", max_steps=2, context={"expect": "42.0"}))
        self.assertTrue(result.success)
        self.assertTrue(result.trajectory.success_hint)

    def test_memory_is_written_and_reread(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
            store = SqliteExperienceStore(Path(temp) / "m.sqlite3")
            model = ScriptedModel(
                ['{"candidates":[{"action":"tool:fake/lookup","arguments":{"item":"alpha"},"confidence":0.9}]}'],
            )
            agent = build_agent(store=store, model=model, config=AgentConfig(max_steps=1))
            result = agent.solve(Task(id="t1", goal="g", max_steps=1))
            stats = store.stats()
            self.assertEqual(stats["episodes"], 1)
            self.assertEqual(stats["transitions"], 1)
            self.assertEqual(result.memory_after["transitions"], 1)
            store.close()

    def test_no_memory_config_skips_writes(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
            store = SqliteExperienceStore(Path(temp) / "m.sqlite3")
            agent = build_agent(store=store, config=AgentConfig(max_steps=1, write_memory=False))
            agent.solve(Task(id="t1", goal="g", max_steps=1))
            self.assertEqual(store.stats()["transitions"], 0)
            store.close()

    def test_memory_action_is_replayed_with_a_portable_argument_only(self) -> None:
        # Seed memory with a lookup at a structurally identical state.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
            store = SqliteExperienceStore(Path(temp) / "m.sqlite3")
            first = ScriptedModel(
                [
                    '{"candidates":[{"action":"tool:fake/lookup","arguments":{"item":"alpha"},"confidence":0.9}]}'
                ]
            )
            agent = build_agent(store=store, model=first, config=AgentConfig(max_steps=1))
            agent.solve(Task(id="t1", goal="look up alpha", family="fam", max_steps=1))
            # Second task: the model proposes only calc; memory should add lookup
            # only if its stored argument still fits this task.
            second = ScriptedModel(
                [
                    '{"candidates":[{"action":"tool:fake/calc","arguments":{"expression":"1+1"},"confidence":0.9}]}'
                ]
            )
            agent2 = build_agent(store=store, model=second, config=AgentConfig(max_steps=1))
            result = agent2.solve(Task(id="t2", goal="look up alpha again", family="fam", max_steps=1))
            sources = {item.action_id: item.source for item in result.trajectory.steps[0].candidates}
            self.assertIn("tool:fake/lookup", sources)
            self.assertEqual(sources["tool:fake/lookup"], "memory")
            store.close()

    def test_stale_memory_argument_is_not_replayed(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
            store = SqliteExperienceStore(Path(temp) / "m.sqlite3")
            first = ScriptedModel(
                [
                    '{"candidates":[{"action":"tool:fake/lookup","arguments":{"item":"alpha"},"confidence":0.9}]}'
                ]
            )
            agent = build_agent(store=store, model=first, config=AgentConfig(max_steps=1))
            agent.solve(Task(id="t1", goal="look up alpha", family="fam", max_steps=1))
            second = ScriptedModel(
                [
                    '{"candidates":[{"action":"tool:fake/calc","arguments":{"expression":"1+1"},"confidence":0.9}]}'
                ]
            )
            agent2 = build_agent(store=store, model=second, config=AgentConfig(max_steps=1))
            result = agent2.solve(Task(id="t3", goal="look up beta", family="fam", max_steps=1))
            sources = [item.action_id for item in result.trajectory.steps[0].candidates]
            self.assertNotIn("tool:fake/lookup", sources)
            store.close()

    def test_decision_records_the_shaping_trace(self) -> None:
        model = PromptDrivenModel({"": ['{"action":"answer","arguments":{"answer":"1"},"confidence":0.8}']})
        agent = build_agent(model=model, config=AgentConfig(max_steps=2))
        result = agent.solve(Task(id="t", goal="g", max_steps=2))
        decision = result.trajectory.steps[0].decision
        self.assertIsNotNone(decision)
        self.assertEqual(decision.selected.action_id, "answer")
        self.assertEqual(len(decision.shaped), 1)
        self.assertEqual(decision.temperature, 0.0)

    def test_returns_are_discounted_from_step_rewards(self) -> None:
        from expert_pack.contracts import Evaluation, StepRecord, State

        agent = build_agent()
        evaluation = Evaluation(success=True, step_rewards=[0.5, 0.0, 1.0], score=1.0)
        steps = [
            StepRecord(
                index=index,
                state=State(key=str(index), text="", tokens=()),
                candidates=[],
                selected=_answer_candidate(index),
                observation=Observation("tool", ""),
            )
            for index in range(3)
        ]
        returns = agent._returns(evaluation, steps)
        # G_t = r_t + gamma r_{t+1} + gamma^2 r_{t+2}, gamma = 0.5
        self.assertAlmostEqual(returns[0], 0.5 + 0.5 * 0.0 + 0.25 * 1.0)
        self.assertAlmostEqual(returns[1], 0.0 + 0.5 * 1.0)
        self.assertAlmostEqual(returns[2], 1.0)


def _answer_candidate(index: int):
    from expert_pack.contracts import Candidate

    return Candidate(action_id=f"tool:x/a{index}", kind="tool", name=f"a{index}")


if __name__ == "__main__":
    unittest.main()
