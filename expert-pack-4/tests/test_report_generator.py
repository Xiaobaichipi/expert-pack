from __future__ import annotations

import json
import unittest
from typing import Any

from expert_pack.contracts import ToolResult
from expert_pack.extensions.pms.report_generator import PmsReportProvider


class FakePms:
    name = "pms"

    def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        if name == "inquire_defect":
            payload = {"code": 0, "data": {"list": [
                {"defectId": "DF-1", "defectLevel": "严重", "deviceName": "1号主变", "part": "套管", "defectDesc": "渗油", "status": "处理中"},
                {"defectId": "DF-2", "defectLevel": "一般", "deviceName": "2号主变", "part": "本体", "defectDesc": "轻微", "status": "已消除"},
            ]}}
        elif name == "query_station_scale_analysis" and arguments.get("pageSize") == 1:
            payload = {"code": 0, "data": {"list": [{"stationId": "STA-1", "stationName": "测试站", "availabilityRate": 99.95, "outageCount": 2}]}}
        elif name == "query_station_scale_analysis":
            payload = {"code": 0, "data": {"list": [{"stationId": "STA-1", "availabilityRate": 99.95, "outageCount": 2}]}}
        elif name == "query_open_capacity":
            payload = {"code": 0, "data": {"list": [{"deviceName": "1号主变", "loadRate": 88.0, "currentLoadMVA": 211.2, "ratedCapacityMVA": 240}]}}
        else:
            return ToolResult(ok=False, content="", error="unknown")
        return ToolResult(ok=True, content=json.dumps(payload, ensure_ascii=False))


class ReportGeneratorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = PmsReportProvider(FakePms())

    def test_defect_report(self) -> None:
        result = self.provider.call_tool("defect_report", {"stationId": "STA-1"})
        self.assertTrue(result.ok)
        self.assertIn("缺陷汇总报告", result.content)
        self.assertIn("严重", result.content)
        self.assertIn("DF-1", result.content)

    def test_station_report(self) -> None:
        result = self.provider.call_tool("station_report", {"stationId": "STA-1"})
        self.assertTrue(result.ok)
        self.assertIn("运行概况报告", result.content)
        self.assertIn("99.95", result.content)
        self.assertIn("88.0", result.content)

    def test_unknown_tool(self) -> None:
        result = self.provider.call_tool("nope", {})
        self.assertFalse(result.ok)


if __name__ == "__main__":
    unittest.main()
