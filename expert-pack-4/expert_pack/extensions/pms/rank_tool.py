"""确定性比较辅助工具：把“跨记录比较”交给代码，而不是模型心算。

只在 P3 实验中由 harness 绑定，不属于 PMS 26 个正式接口。
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from expert_pack.contracts import ToolProvider, ToolResult, ToolSpec


class PmsRankProvider:
    """包装 PMS 工具，提供 rank_stations / rank_devices 两个确定性排序工具。"""

    name = "pms-rank"

    def __init__(self, pms: ToolProvider) -> None:
        self._pms = pms

    def list_tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                provider=self.name,
                name="rank_stations",
                description="按可用率等字段对所有变电站排序，返回最小/最大值站。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "metric": {"type": "string", "default": "availabilityRate"},
                        "direction": {"type": "string", "enum": ["min", "max"], "default": "min"},
                    },
                },
            ),
            ToolSpec(
                provider=self.name,
                name="rank_devices",
                description="按负载率等字段对主变排序，返回最小/最大值设备。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "stationId": {"type": "string"},
                        "metric": {"type": "string", "default": "loadRate"},
                        "direction": {"type": "string", "enum": ["min", "max"], "default": "max"},
                    },
                },
            ),
        ]

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> ToolResult:
        try:
            if name == "rank_stations":
                return self._rank_stations(dict(arguments))
            if name == "rank_devices":
                return self._rank_devices(dict(arguments))
            return ToolResult(ok=False, content="", error=f"unknown rank tool {name!r}")
        except Exception as exc:  # noqa: BLE001 - surfaced as failed observation
            return ToolResult(ok=False, content="", error=f"rank tool failed: {exc}")

    def _rank_stations(self, args: dict[str, Any]) -> ToolResult:
        result = self._pms.call_tool("query_station_scale_analysis", {"pageSize": 100})
        if not result.ok:
            return result
        records = _records(result.content)
        metric = str(args.get("metric") or "availabilityRate")
        direction = str(args.get("direction") or "min")
        winner = _pick(records, metric, direction)
        payload = {"metric": metric, "direction": direction, "winner": winner, "count": len(records)}
        return ToolResult(ok=True, content=json.dumps(payload, ensure_ascii=False), data=payload)

    def _rank_devices(self, args: dict[str, Any]) -> ToolResult:
        query: dict[str, Any] = {"pageSize": 100}
        station = str(args.get("stationId") or "").strip()
        if station:
            query["stationId"] = station
        result = self._pms.call_tool("query_open_capacity", query)
        if not result.ok:
            return result
        records = _records(result.content)
        metric = str(args.get("metric") or "loadRate")
        direction = str(args.get("direction") or "max")
        winner = _pick(records, metric, direction)
        payload = {"metric": metric, "direction": direction, "winner": winner, "count": len(records)}
        return ToolResult(ok=True, content=json.dumps(payload, ensure_ascii=False), data=payload)

    def close(self) -> None:
        return None


def _records(content: str) -> list[dict[str, Any]]:
    payload = json.loads(content)
    data = payload.get("data", payload)
    items = data.get("list") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ValueError("rank tool: PMS response has no list")
    return [item for item in items if isinstance(item, dict)]


def _pick(records: list[dict[str, Any]], metric: str, direction: str) -> dict[str, Any] | None:
    if not records:
        return None
    key = lambda item: float(item.get(metric) or 0.0)
    ordered = sorted(records, key=key, reverse=(direction != "min"))
    return ordered[0]
