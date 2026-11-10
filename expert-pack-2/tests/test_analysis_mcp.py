"""substation-analysis-mcp MCP 协议测试。

覆盖：initialize / ping / tools/list（与 spec/analysis-tools.json 逐字段一致）/
tools/call（7 个工具）/ 通知无响应 / 错误码 -32700/-32600/-32601/-32602/-32603 /
stdio 循环 stdout 纯协议；业务错误走 isError 信封。
"""

from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path

_PACK = Path(__file__).resolve().parents[1]
_SKILL = _PACK / "skills" / "substation-analysis-mcp"
_SCRIPTS = _SKILL / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import analysis_mcp  # noqa: E402
from analysis_mcp import AnalysisMcpServer  # noqa: E402

SPEC_PATH = _PACK / "spec" / "analysis-tools.json"
DEMO_PATH = _SKILL / "assets" / "demo_bundle.json"


def load_spec() -> dict:
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


def demo_bundle() -> dict:
    return json.loads(DEMO_PATH.read_text(encoding="utf-8"))


class McpServerTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.server = AnalysisMcpServer()
        self.spec = load_spec()

    def rpc(self, payload) -> dict:
        raw = self.server.handle_line(json.dumps(payload, ensure_ascii=False))
        self.assertIsNotNone(raw)
        return json.loads(raw)

    def call_tool(self, name: str, arguments: dict) -> dict:
        response = self.rpc(
            {
                "jsonrpc": "2.0",
                "id": 99,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )
        self.assertIn("result", response, response)
        return response["result"]

    def tool_payload(self, result: dict) -> dict:
        self.assertFalse(result["isError"], result)
        return json.loads(result["content"][0]["text"])


class InitializeTest(McpServerTestBase):
    def test_initialize(self) -> None:
        response = self.rpc(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "clientInfo": {"name": "unittest", "version": "0.0.1"},
                },
            }
        )
        result = response["result"]
        self.assertEqual(result["protocolVersion"], "2024-11-05")
        self.assertEqual(result["capabilities"], {"tools": {}})
        self.assertEqual(result["serverInfo"]["name"], "substation-analysis-mcp")
        self.assertEqual(result["serverInfo"]["version"], "1.1.0")

    def test_ping(self) -> None:
        response = self.rpc({"jsonrpc": "2.0", "id": 2, "method": "ping"})
        self.assertEqual(response["result"], {})

    def test_initialized_notification_has_no_response(self) -> None:
        self.assertIsNone(
            self.server.handle_line(
                json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
            )
        )
        self.assertTrue(self.server.initialized)

    def test_request_without_id_is_treated_as_notification(self) -> None:
        self.assertIsNone(self.server.handle_line(json.dumps({"jsonrpc": "2.0", "method": "ping"})))


class ToolsListTest(McpServerTestBase):
    def setUp(self) -> None:
        super().setUp()
        self.tools = self.rpc({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})["result"]["tools"]

    def test_tool_count_is_seven(self) -> None:
        self.assertEqual(len(self.tools), 7)

    def test_tool_names_match_spec(self) -> None:
        self.assertEqual([tool["name"] for tool in self.tools], [tool["name"] for tool in self.spec["tools"]])

    def test_tools_match_spec_exactly(self) -> None:
        for actual, expected in zip(self.tools, self.spec["tools"]):
            with self.subTest(tool=expected["name"]):
                self.assertEqual(actual["name"], expected["name"])
                self.assertEqual(actual["description"], expected["desc"])
                self.assertEqual(set(actual), {"name", "description", "inputSchema"})
                expected_params = {param["name"]: param for param in expected["params"]}
                schema = actual["inputSchema"]
                self.assertEqual(schema["type"], "object")
                self.assertEqual(set(schema["properties"]), set(expected_params))
                self.assertEqual(
                    schema["required"],
                    [param["name"] for param in expected["params"] if param.get("required")],
                )
                for name, param in expected_params.items():
                    prop = schema["properties"][name]
                    self.assertEqual(prop["type"], param["type"], f"{expected['name']}.{name}")
                    self.assertTrue(prop["description"])
                    if "default" in param:
                        self.assertEqual(prop["default"], param["default"], f"{expected['name']}.{name}")
                    if "enum" in param:
                        self.assertEqual(prop["enum"], param["enum"], f"{expected['name']}.{name}")

    def test_tool_names_unique(self) -> None:
        names = [tool["name"] for tool in self.tools]
        self.assertEqual(len(names), len(set(names)))


class ToolsCallTest(McpServerTestBase):
    def test_assess_device_health(self) -> None:
        result = self.call_tool("assess_device_health", {"bundle": demo_bundle()})
        payload = self.tool_payload(result)
        self.assertEqual(
            set(payload),
            {
                "score",
                "grade",
                "gradeLabel",
                "risk",
                "dimensions",
                "deductions",
                "completeness",
                "confidence",
                "summary",
                "knowledgeQueries",
                "dataGaps",
                "asOf",
            },
        )
        self.assertEqual(payload["grade"], "C")

    def test_assess_station_health(self) -> None:
        result = self.call_tool(
            "assess_station_health",
            {
                "bundles": [demo_bundle()],
                "station_meta": {"stationName": "220kV 郑州变电站"},
                "top_n": 3,
            },
        )
        payload = self.tool_payload(result)
        self.assertEqual(payload["station"]["deviceCount"], 1)
        self.assertIn("aggregate", payload)

    def test_diagnose_equipment(self) -> None:
        payload = self.tool_payload(
            self.call_tool("diagnose_equipment", {"bundle": demo_bundle(), "max_hypotheses": 2})
        )
        self.assertLessEqual(len(payload["hypotheses"]), 2)
        self.assertIn("patterns", payload)
        self.assertIn("missingEvidence", payload)

    def test_detect_defect_patterns(self) -> None:
        bundle = demo_bundle()
        payload = self.tool_payload(
            self.call_tool(
                "detect_defect_patterns",
                {
                    "defects": bundle["defects"],
                    "device_meta": bundle["device"],
                    "window_days": 365,
                    "family_min_count": 3,
                },
            )
        )
        self.assertEqual(payload["summary"]["duplicateClusterCount"], 1)

    def test_compute_device_metrics(self) -> None:
        payload = self.tool_payload(self.call_tool("compute_device_metrics", {"bundle": demo_bundle()}))
        self.assertEqual(payload["metrics"]["loadRate"], 70.0)
        self.assertIn("denominators", payload)
        self.assertIsInstance(payload["dataGaps"], list)

    def test_generate_report(self) -> None:
        health = self.tool_payload(self.call_tool("assess_device_health", {"bundle": demo_bundle()}))
        payload = self.tool_payload(
            self.call_tool(
                "generate_report",
                {
                    "report_type": "device_profile",
                    "payload": {"device": demo_bundle()["device"], "health": health},
                    "citations": [
                        {"title": "运行规程", "source": "DL/T 572", "snippet": "套管介损要求", "kbId": "KB-1"}
                    ],
                    "title": "MCP 报告",
                },
            )
        )
        self.assertEqual(payload["reportType"], "device_profile")
        self.assertEqual(payload["title"], "MCP 报告")
        self.assertIn("运行规程", payload["markdown"])
        self.assertNotIn("{{", payload["markdown"])

    def test_list_report_types(self) -> None:
        payload = self.tool_payload(self.call_tool("list_report_types", {}))
        self.assertEqual(len(payload["reportTypes"]), 3)


class ProtocolErrorTest(McpServerTestBase):
    def test_unknown_method(self) -> None:
        response = self.server.handle_line(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "no/such/method"})
        )
        self.assertEqual(json.loads(response)["error"]["code"], -32601)

    def test_resources_not_supported(self) -> None:
        response = self.server.handle_line(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "resources/list"})
        )
        self.assertEqual(json.loads(response)["error"]["code"], -32602)

    def test_unknown_tool(self) -> None:
        response = self.rpc(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "no_such_tool", "arguments": {}},
            }
        )
        self.assertEqual(response["error"]["code"], -32602)

    def test_missing_required_argument(self) -> None:
        response = self.rpc(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "assess_device_health", "arguments": {}},
            }
        )
        self.assertEqual(response["error"]["code"], -32602)
        self.assertIn("bundle", response["error"]["message"])

    def test_invalid_enum(self) -> None:
        response = self.rpc(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "generate_report",
                    "arguments": {"report_type": "weekly", "payload": {}},
                },
            }
        )
        self.assertEqual(response["error"]["code"], -32602)

    def test_invalid_argument_type(self) -> None:
        response = self.rpc(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "assess_device_health", "arguments": {"bundle": "not-an-object"}},
            }
        )
        self.assertEqual(response["error"]["code"], -32602)

    def test_arguments_must_be_object(self) -> None:
        response = self.rpc(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "list_report_types", "arguments": "bad"},
            }
        )
        self.assertEqual(response["error"]["code"], -32602)

    def test_tools_call_params_must_be_object(self) -> None:
        response = self.rpc(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": ["not", "object"],
            }
        )
        self.assertEqual(response["error"]["code"], -32602)

    def test_parse_error(self) -> None:
        raw = self.server.handle_line("{this is not json")
        response = json.loads(raw)
        self.assertEqual(response["error"]["code"], -32700)

    def test_invalid_request_not_object(self) -> None:
        response = json.loads(self.server.handle_line(json.dumps(1)))
        self.assertEqual(response["error"]["code"], -32600)

    def test_invalid_request_missing_jsonrpc(self) -> None:
        response = json.loads(self.server.handle_line(json.dumps({"id": 1, "method": "ping"})))
        self.assertEqual(response["error"]["code"], -32600)

    def test_missing_method(self) -> None:
        response = json.loads(
            self.server.handle_line(json.dumps({"jsonrpc": "2.0", "id": 1, "params": {}}))
        )
        self.assertEqual(response["error"]["code"], -32600)


class BusinessErrorTest(McpServerTestBase):
    def test_invalid_bundle_returns_is_error(self) -> None:
        result = self.call_tool("assess_device_health", {"bundle": {"device": {}}})
        self.assertTrue(result["isError"])
        body = json.loads(result["content"][0]["text"])
        self.assertEqual(body["error"]["code"], "BUNDLE_INVALID")
        self.assertIn("name", body["error"]["message"])

    def test_unknown_scorecard_returns_is_error(self) -> None:
        result = self.call_tool(
            "assess_device_health",
            {"bundle": demo_bundle(), "scorecard_profile": "no_such"},
        )
        self.assertTrue(result["isError"])
        body = json.loads(result["content"][0]["text"])
        self.assertEqual(body["error"]["code"], "CONFIG_INVALID")


class StdioLoopTest(unittest.TestCase):
    def test_serve_stdio_outputs_only_protocol_lines(self) -> None:
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "assess_device_health", "arguments": {"bundle": demo_bundle()}},
            },
            "{broken json",
        ]
        stdin = [
            json.dumps(requests[0], ensure_ascii=False) + "\n",
            json.dumps(requests[1], ensure_ascii=False) + "\n",
            json.dumps(requests[2], ensure_ascii=False) + "\n",
            json.dumps(requests[3], ensure_ascii=False) + "\n",
            "{broken json\n",
        ]
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = analysis_mcp.serve_stdio(
            stdin=stdin, stdout=stdout, stderr=stderr
        )
        self.assertEqual(code, 0)
        lines = [line for line in stdout.getvalue().splitlines() if line.strip()]
        self.assertEqual(len(lines), 4)  # initialize / tools/list / tools/call / parse error
        for line in lines:
            message = json.loads(line)
            self.assertEqual(message["jsonrpc"], "2.0")
            self.assertIn("id", message)
            self.assertTrue("result" in message or "error" in message)
        self.assertIn("initialize", stderr.getvalue())
        self.assertIn("JSON 解析失败", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
