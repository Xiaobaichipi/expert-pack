"""把查询结果渲染成结构化报告（缺陷分析、运行概况等）。

当前支持：
* defect_report：某站缺陷汇总报告；
* station_report：某站运行概况报告。
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from expert_pack.contracts import ToolResult, ToolSpec


class PmsReportProvider:
    """包装 PMS 工具，生成 Markdown 报告。"""

    name = "pms-report"

    def __init__(self, pms: Any) -> None:
        self._pms = pms

    def list_tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                provider=self.name,
                name="defect_report",
                description="生成某站缺陷汇总报告（Markdown）",
                input_schema={
                    "type": "object",
                    "properties": {
                        "stationId": {"type": "string"},
                    },
                    "required": ["stationId"],
                },
            ),
            ToolSpec(
                provider=self.name,
                name="station_report",
                description="生成某站运行概况报告（Markdown）",
                input_schema={
                    "type": "object",
                    "properties": {
                        "stationId": {"type": "string"},
                    },
                    "required": ["stationId"],
                },
            ),
        ]

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> ToolResult:
        try:
            if name == "defect_report":
                return self._defect_report(str(arguments.get("stationId", "")))
            if name == "station_report":
                return self._station_report(str(arguments.get("stationId", "")))
            return ToolResult(ok=False, content="", error=f"unknown report tool {name!r}")
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, content="", error=f"report tool failed: {exc}")

    def _query(self, tool: str, args: dict[str, Any]) -> list[dict[str, Any]]:
        result = self._pms.call_tool(tool, args)
        if not result.ok:
            return []
        try:
            payload = json.loads(result.content)
            data = payload.get("data", payload)
            items = data.get("list") if isinstance(data, dict) else None
            return [item for item in items or [] if isinstance(item, dict)]
        except json.JSONDecodeError:
            return []

    def _defect_report(self, station_id: str) -> ToolResult:
        defects = self._query("inquire_defect", {"stationId": station_id, "pageSize": 100})
        station_info = self._query("query_station_scale_analysis", {"stationId": station_id, "pageSize": 1})
        station_name = station_info[0].get("stationName", station_id) if station_info else station_id

        lines = [f"# {station_name} 缺陷汇总报告", ""]
        lines.append(f"**统计时间**: 2026-11-16")
        lines.append(f"**缺陷总数**: {len(defects)}")
        lines.append("")

        by_level: dict[str, list[dict[str, Any]]] = {}
        for d in defects:
            by_level.setdefault(d.get("defectLevel", "未知"), []).append(d)

        for level in ("危急", "严重", "一般", "未知"):
            items = by_level.get(level, [])
            if not items:
                continue
            lines.append(f"## {level}缺陷（{len(items)} 条）")
            for d in items:
                lines.append(
                    f"- **{d.get('defectId')}** {d.get('deviceName', '')} {d.get('part', '')}：{d.get('defectDesc', '')[:60]}（状态：{d.get('status', '')}）"
                )
            lines.append("")

        if not defects:
            lines.append("当前无在册缺陷。")

        report = "\n".join(lines)
        return ToolResult(ok=True, content=report, data={"report": report, "stationId": station_id, "count": len(defects)})

    def _station_report(self, station_id: str) -> ToolResult:
        # get_station_by_id 不在 26 接口中，用 reliability + capacity 推断站信息
        reliability = self._query("query_station_scale_analysis", {"stationId": station_id, "pageSize": 1})
        capacity = self._query("query_open_capacity", {"stationId": station_id, "pageSize": 100})
        defects = self._query("inquire_defect", {"stationId": station_id, "pageSize": 100})

        rel = reliability[0] if reliability else {}
        station_name = rel.get("stationName", station_id)

        lines = [f"# {station_name} 运行概况报告", ""]
        lines.append(f"**电压等级**: {rel.get('voltageLevel', '')}")
        lines.append(f"**主变数量**: {len(capacity)}")
        lines.append(f"**可用率**: {rel.get('availabilityRate', '')}%")
        lines.append(f"**停电次数**: {rel.get('outageCount', '')}")
        lines.append(f"**在册缺陷**: {len(defects)} 条")
        lines.append("")

        if capacity:
            lines.append("## 主变负载")
            for c in capacity:
                lines.append(
                    f"- {c.get('deviceName', '')}：{c.get('loadRate', '')}%（{c.get('currentLoadMVA', '')}/{c.get('ratedCapacityMVA', '')} MVA）"
                )
            lines.append("")

        if defects:
            lines.append("## 主要缺陷")
            for d in defects[:5]:
                lines.append(
                    f"- {d.get('defectLevel', '')} {d.get('deviceName', '')}：{d.get('defectDesc', '')[:50]}"
                )

        report = "\n".join(lines)
        return ToolResult(ok=True, content=report, data={"report": report, "stationId": station_id})

    def close(self) -> None:
        return None
