#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P3-2：确定性比较工具 rank_stations / rank_devices 测试。"""

from __future__ import annotations

import json
import unittest

from expert_pack.contracts import ToolResult
from expert_pack.extensions.pms.rank_tool import PmsRankProvider


class FakePms:
    name = "pms"

    def list_tools(self):
        return []

    def call_tool(self, name, arguments):
        if name == "query_station_scale_analysis":
            payload = {
                "code": 0,
                "data": {
                    "list": [
                        {"stationName": "A站", "availabilityRate": 99.99},
                        {"stationName": "B站", "availabilityRate": 99.60},
                    ]
                },
            }
        elif name == "query_open_capacity":
            payload = {
                "code": 0,
                "data": {
                    "list": [
                        {"deviceName": "1号主变", "loadRate": 88.0, "deviceId": "AST-1"},
                        {"deviceName": "2号主变", "loadRate": 76.0, "deviceId": "AST-2"},
                    ]
                },
            }
        else:
            return ToolResult(ok=False, content="", error="unknown")
        return ToolResult(ok=True, content=json.dumps(payload, ensure_ascii=False))

    def close(self):
        return None


class PmsRankToolTest(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = PmsRankProvider(FakePms())

    def test_rank_stations_min(self) -> None:
        result = self.provider.call_tool("rank_stations", {"direction": "min"})
        self.assertTrue(result.ok)
        payload = json.loads(result.content)
        self.assertEqual(payload["winner"]["stationName"], "B站")

    def test_rank_devices_max(self) -> None:
        result = self.provider.call_tool("rank_devices", {"direction": "max"})
        self.assertTrue(result.ok)
        payload = json.loads(result.content)
        self.assertEqual(payload["winner"]["deviceName"], "1号主变")

    def test_unknown_tool_fails_cleanly(self) -> None:
        result = self.provider.call_tool("nope", {})
        self.assertFalse(result.ok)


if __name__ == "__main__":
    unittest.main()
