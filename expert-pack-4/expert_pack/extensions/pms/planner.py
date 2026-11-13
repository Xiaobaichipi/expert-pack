"""P0 用的脚本规划器：故意“先选错工具”，让 JitRL 记忆有机会翻转决策。

它不调用真实 LLM，只用来验证「记忆流 → 动作分数 → 决策」链路是否成立；
正式实验应换成 `expert_pack.adapters.model_openai:from_config`。
"""

from __future__ import annotations

import json
import re
from typing import Any

from expert_pack.contracts import ModelMessage, ModelReply

_TASK = re.compile(r"TASK ID:\s*(.*)")
_GOAL = re.compile(r"GOAL:\s*(.*)")
_OBS_HEADER = re.compile(r"CURRENT OBSERVATION \(kind=([^,]+), ok=(True|False)\):")
_LAST_STEP = re.compile(r"^- (.*?) -> ok=")
_ID_PATTERNS = {
    "asset": re.compile(r"AST-\d{3}-\d{4}"),
    "psr": re.compile(r"PSR-\d{3}-\d{4}"),
    "station": re.compile(r"STA-\d{3}-\d{2}"),
    "defect": re.compile(r"DF-\d{4}-\d{4}"),
}
_FAMILY_ALIASES = {
    "ledger-model": "ledger_model",
    "defect-level": "defect_level",
    "capacity-load": "capacity_load",
    "reliability-availability": "reliability_availability",
    "topology-source": "topology_source",
    "maintenance-plan": "maintenance_plan",
}

# 每个意图族：先给一个“成功但答错”的工具（高置信度），再给正确工具（低置信度）。
_FAMILY_ACTIONS: dict[str, tuple[str, str]] = {
    "ledger_model": ("tool:pms/get_psr_by_id", "tool:pms/get_asset_by_id"),
    "defect_level": ("tool:pms/list_patrol_record", "tool:pms/view_defect"),
    "capacity_load": ("tool:pms/query_station_scale_analysis", "tool:pms/query_open_capacity"),
    "reliability_availability": ("tool:pms/query_open_capacity", "tool:pms/query_station_scale_analysis"),
    "topology_source": ("tool:pms/get_psr_by_id", "tool:pms/search_power_path"),
    "maintenance_plan": ("tool:pms/list_patrol_plan", "tool:pms/get_repair_plan"),
}


class PmsScriptedPlanner:
    name = "pms-scripted-planner"

    def complete(
        self,
        messages: list[ModelMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> ModelReply:
        prompt = next(
            (message.content for message in reversed(messages) if "CURRENT OBSERVATION" in message.content),
            messages[-1].content if messages else "",
        )
        task_id = _first(_TASK, prompt)
        goal = _first(_GOAL, prompt)
        obs_kind, obs_ok, obs_text = _observation(prompt)
        ids = {key: _first(pattern, goal) for key, pattern in _ID_PATTERNS.items()}
        family = _family(task_id)
        last_action = _last_action(prompt)

        if obs_kind == "start":
            candidates = self._start_candidates(family, ids)
        elif last_action and last_action == _FAMILY_ACTIONS.get(family, ("", ""))[1] and obs_ok:
            answer = _answer_from_observation(last_action, obs_text)
            candidates = [self._answer_candidate(answer)]
        else:
            candidates = [self._answer_candidate("unknown")]

        payload = {"thought": "pms scripted planner", "candidates": candidates}
        return ModelReply(text=json.dumps(payload, ensure_ascii=False), usage={"calls": 1})

    def _start_candidates(self, family: str, ids: dict[str, str]) -> list[dict[str, Any]]:
        bad, good = _FAMILY_ACTIONS.get(family, ("", ""))
        return [
            {
                "action": bad,
                "arguments": self._arguments(bad, ids),
                "confidence": 0.9,
                "why": "stubborn prior: pick the plausible but wrong tool first",
            },
            {
                "action": good,
                "arguments": self._arguments(good, ids),
                "confidence": 0.4,
                "why": "correct tool, currently under-confident",
            },
        ]

    @staticmethod
    def _arguments(action: str, ids: dict[str, str]) -> dict[str, Any]:
        name = action.split("/", 1)[-1]
        if name == "get_psr_by_id":
            return {"psrId": ids.get("psr") or "PSR-220-0001"}
        if name == "get_asset_by_id":
            return {"assetId": ids.get("asset") or "AST-102-0001"}
        if name == "list_patrol_record":
            return {"stationId": ids.get("station") or "STA-220-01"}
        if name == "view_defect":
            return {"defectId": ids.get("defect") or "DF-2026-0001"}
        if name == "query_station_scale_analysis":
            return {"stationId": ids.get("station") or "STA-220-01"}
        if name == "query_open_capacity":
            return {"deviceId": ids.get("asset") or "AST-102-0001"}
        if name == "search_power_path":
            return {"psrId": ids.get("psr") or "PSR-220-0001"}
        if name == "list_patrol_plan":
            return {"stationId": ids.get("station") or "STA-220-01"}
        if name == "get_repair_plan":
            return {"deviceId": ids.get("asset") or "AST-102-0001"}
        return {}

    @staticmethod
    def _answer_candidate(answer: Any) -> dict[str, Any]:
        return {
            "action": "answer",
            "arguments": {"answer": str(answer)},
            "confidence": 0.9,
            "why": "submit the parsed result",
        }


def _first(pattern: re.Pattern[str], text: str) -> str:
    match = pattern.search(text)
    if not match:
        return ""
    return (match.group(1) if pattern.groups else match.group(0)).strip()


def _family(task_id: str) -> str:
    prefix = re.sub(r"-\d+(-v\d+)?$", "", task_id.strip())
    return _FAMILY_ALIASES.get(prefix, prefix.replace("-", "_"))


def _observation(prompt: str) -> tuple[str, bool, str]:
    lines = prompt.splitlines()
    for index, line in enumerate(lines):
        match = _OBS_HEADER.match(line)
        if not match:
            continue
        kind = match.group(1).strip()
        ok = match.group(2) == "True"
        collected: list[str] = []
        for candidate in lines[index + 1 :]:
            if not candidate.strip():
                break
            collected.append(candidate)
        return kind, ok, "\n".join(collected).strip()
    return "start", True, ""


def _last_action(prompt: str) -> str:
    actions = []
    for line in prompt.splitlines():
        match = _LAST_STEP.match(line)
        if match:
            actions.append(match.group(1).split("{")[0].strip())
    return actions[-1] if actions else ""


def _payload(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _data(payload: dict[str, Any]) -> Any:
    return payload.get("data") if "data" in payload else payload


def _answer_from_observation(action: str, text: str) -> Any:
    payload = _payload(text)
    data = _data(payload)
    name = action.split("/", 1)[-1]
    try:
        if name == "get_asset_by_id" and isinstance(data, dict):
            return data.get("model") or "unknown"
        if name == "view_defect" and isinstance(data, dict):
            return data.get("defectLevel") or "unknown"
        if name == "query_open_capacity":
            items = data.get("list") if isinstance(data, dict) else None
            if items:
                return items[0].get("loadRate")
        if name == "query_station_scale_analysis":
            items = data.get("list") if isinstance(data, dict) else None
            if items:
                return items[0].get("availabilityRate")
        if name == "search_power_path" and isinstance(data, dict):
            return data.get("sourceName") or "unknown"
        if name == "get_repair_plan":
            items = data.get("list") if isinstance(data, dict) else None
            if items:
                return items[0].get("planTime")
    except (AttributeError, IndexError, TypeError):
        return "unknown"
    return "unknown"


def from_config(**kwargs: Any) -> PmsScriptedPlanner:
    """装配工厂（P0 离线演示用；正式实验请换真实模型适配器）。"""

    return PmsScriptedPlanner()

