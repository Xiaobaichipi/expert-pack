"""Offline demo: a scripted planner + a real MCP server + a growing memory.

The point is not to fake intelligence. The planner is deliberately stubborn:
at every task start it strongly prefers ``calc`` over ``lookup``. Episode 1
fails, the evaluator assigns a negative return to that action at that state,
and the JitRL advantage term flips the choice for every later task. That is the
paper's claim in miniature -- test-time policy improvement with no gradients.
"""

from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from expert_pack.adapters.mcp_stdio import McpToolProvider
from expert_pack.adapters.skills import load_skill_directory
from expert_pack.agent import AgentConfig, ExpertAgent
from expert_pack.contracts import ModelMessage, ModelReply, Task
from expert_pack.jitrl.advantage import AdvantageConfig
from expert_pack.jitrl.evaluator import HeuristicEvaluator
from expert_pack.jitrl.memory import NullStore, SqliteExperienceStore
from expert_pack.jitrl.policy import JitrlPolicy
from expert_pack.jitrl.retrieval import JaccardRetriever
from expert_pack.jitrl.state import DefaultAbstractor

_ITEM = re.compile(r"GOAL:.*?\b(alpha|beta|gamma)\b", re.IGNORECASE)
_LAST_STEP = re.compile(r"^- (.*?) -> ok=(True|False): (.*)$")
_NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")


class DemoPlanner:
    """Stubborn, deterministic policy prior used when no API key is available."""

    name = "demo-planner"

    def complete(
        self,
        messages: Sequence[ModelMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> ModelReply:
        prompt = next(
            (m.content for m in reversed(messages) if "CURRENT OBSERVATION" in m.content),
            messages[-1].content if messages else "",
        )
        observation = _observation(prompt)
        last = _last_step(prompt)
        item = _item(prompt)
        candidates = self._decide(observation, last, item)
        payload = {"thought": "demo planner", "candidates": candidates}
        return ModelReply(text=json.dumps(payload), usage={"calls": 1})

    def _decide(self, observation: str, last: tuple[str, bool, str] | None, item: str) -> list[dict]:
        if last is None:
            return [
                {
                    "action": "tool:demo/calc",
                    "arguments": {"expression": "0"},
                    "confidence": 0.9,
                    "why": "compute immediately before retrieving (the stub's bad habit)",
                },
                {
                    "action": "tool:demo/lookup",
                    "arguments": {"item": item},
                    "confidence": 0.4,
                    "why": "retrieve the operand",
                },
            ]
        action, ok, text = last
        if "lookup" in action and ok and _NUMBER.match(text.strip()):
            value = text.strip()
            return [
                {
                    "action": "tool:demo/calc",
                    "arguments": {"expression": f"{value}*3"},
                    "confidence": 0.9,
                    "why": "multiply the retrieved value",
                },
                {
                    "action": f"skill:verify-arithmetic",
                    "arguments": {"expression": f"{value}*3", "answer": ""},
                    "confidence": 0.05,
                    "why": "optional check",
                },
            ]
        if "calc" in action and ok and _NUMBER.match(text.strip()):
            return [
                {
                    "action": "answer",
                    "arguments": {"answer": text.strip()},
                    "confidence": 0.9,
                    "why": "submit the computed value",
                }
            ]
        return [
            {
                "action": "answer",
                "arguments": {"answer": "unknown"},
                "confidence": 0.6,
                "why": "give up after a failed action",
            }
        ]


def _observation(prompt: str) -> str:
    lines = prompt.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("CURRENT OBSERVATION"):
            block = lines[index + 1 :]
            collected: list[str] = []
            for candidate in block:
                if not candidate.strip():
                    break
                collected.append(candidate)
            return "\n".join(collected).strip()
    return ""


def _last_step(prompt: str) -> tuple[str, bool, str] | None:
    found: tuple[str, bool, str] | None = None
    for line in prompt.splitlines():
        match = _LAST_STEP.match(line)
        if match:
            found = (match.group(1), match.group(2) == "True", match.group(3).strip("'\""))
    return found


def _item(prompt: str) -> str:
    match = _ITEM.search(prompt)
    return match.group(1).lower() if match else "alpha"


def build_tasks(count: int = 5) -> list[Task]:
    items = ["alpha", "beta", "alpha", "beta", "alpha", "beta"]
    expected = {"alpha": "126", "beta": "51"}
    tasks: list[Task] = []
    for index in range(count):
        item = items[index % len(items)]
        tasks.append(
            Task(
                id=f"demo-{index + 1}",
                goal=f"What is {item} multiplied by 3? Answer with the number only.",
                success_criteria="Return the numeric result.",
                family="arithmetic-retrieval",
                max_steps=4,
                context={"expect": expected[item], "item": item},
            )
        )
    return tasks


@dataclass
class DemoEpisode:
    arm: str
    task_id: str
    success: bool
    steps: int
    answer: str
    expected: str
    evaluations: list[float]
    decisions: list[str] = field(default_factory=list)


@dataclass
class DemoReport:
    tasks: list[Task]
    baseline: list[DemoEpisode]
    memory: list[DemoEpisode]
    memory_stats: dict
    memory_path: str

    @property
    def baseline_rate(self) -> float:
        return sum(1 for e in self.baseline if e.success) / len(self.baseline) if self.baseline else 0.0

    @property
    def memory_rate(self) -> float:
        return sum(1 for e in self.memory if e.success) / len(self.memory) if self.memory else 0.0


def _build_agent(store, provider: McpToolProvider, seed: int, run_id: str) -> ExpertAgent:
    skills = load_skill_directory(Path(__file__).parent / "skills")
    policy = JitrlPolicy(
        AdvantageConfig(top_k=5, min_similarity=0.4, gamma=0.5, beta=1.0),
        seed=seed,
    )
    return ExpertAgent(
        model=DemoPlanner(),
        tools=[provider],
        skills=skills,
        store=store,
        retriever=JaccardRetriever(),
        abstractor=DefaultAbstractor(),
        policy=policy,
        evaluator=HeuristicEvaluator(),
        config=AgentConfig(max_steps=4, seed=seed),
        run_id=run_id,
    )


def _run_arm(label: str, tasks: list[Task], store, provider: McpToolProvider, seed: int) -> list[DemoEpisode]:
    agent = _build_agent(store, provider, seed, run_id=f"demo-{label}")
    episodes: list[DemoEpisode] = []
    for index, task in enumerate(tasks, start=1):
        result = agent.solve(task, episode_index=index)
        decisions = [
            step.decision.trace() if step.decision else "" for step in result.trajectory.steps
        ]
        episodes.append(
            DemoEpisode(
                arm=label,
                task_id=task.id,
                success=result.success,
                steps=result.steps,
                answer=result.trajectory.answer_text(),
                expected=task.expect() or "?",
                evaluations=result.evaluation.step_rewards,
                decisions=decisions,
            )
        )
    return episodes


def run_demo(
    *,
    count: int = 5,
    seed: int = 7,
    memory_path: str | Path | None = None,
) -> DemoReport:
    import sys

    tasks = build_tasks(count)
    if memory_path is None:
        temp_dir = tempfile.mkdtemp(prefix="expert-pack-demo-")
        memory_path = str(Path(temp_dir) / "memory.sqlite3")
    provider = McpToolProvider(
        "demo",
        sys.executable,
        ["-m", "expert_pack.builtin.mcp_demo_server"],
        timeout=20.0,
    )
    try:
        baseline = _run_arm("baseline", tasks, NullStore(), provider, seed)
        store = SqliteExperienceStore(memory_path)
        try:
            memory = _run_arm("memory", tasks, store, provider, seed)
            stats = store.stats()
        finally:
            store.close()
    finally:
        provider.close()
    return DemoReport(
        tasks=tasks,
        baseline=baseline,
        memory=memory,
        memory_stats=stats,
        memory_path=str(memory_path),
    )
