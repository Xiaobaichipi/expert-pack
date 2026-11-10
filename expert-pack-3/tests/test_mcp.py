"""MCP 协议测试：直接调用协议处理函数（不经 subprocess 管道）。"""

from __future__ import annotations

import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

import io
import json
import unittest
from types import SimpleNamespace

from _support import EXPECTED_TOOL_COUNT, BaseTestCase, shared_client
from pms_client import ErrorCode, PmsError

import mcp_server
from mcp_server import McpServer


def make_server(client=None) -> McpServer:
    return McpServer(client or shared_client())


def request(msg_id, method, params=None):
    message = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        message["params"] = params
    return message


class InitializeTest(BaseTestCase):
    def test_initialize_returns_protocol_contract(self) -> None:
        response = make_server().handle_message(
            request(
                1,
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "unit-test", "version": "0.0.1"},
                },
            )
        )
        self.assertEqual(response["jsonrpc"], "2.0")
        self.assertEqual(response["id"], 1)
        result = response["result"]
        self.assertEqual(result["protocolVersion"], "2024-11-05")
        self.assertEqual(result["protocolVersion"], mcp_server.PROTOCOL_VERSION)
        self.assertEqual(result["capabilities"], {"tools": {}})
        self.assertEqual(result["serverInfo"]["name"], "pms-gateway-mcp")
        self.assertTrue(result["serverInfo"]["version"])

    def test_initialize_without_params(self) -> None:
        response = make_server().handle_message(request(2, "initialize"))
        self.assertEqual(response["result"]["protocolVersion"], "2024-11-05")

    def test_notifications_initialized_has_no_response(self) -> None:
        server = make_server()
        self.assertIsNone(server.handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertTrue(server.initialized)

    def test_ping(self) -> None:
        response = make_server().handle_message(request(3, "ping"))
        self.assertEqual(response["result"], {})

    def test_any_notification_has_no_response(self) -> None:
        self.assertIsNone(make_server().handle_message({"jsonrpc": "2.0", "method": "notifications/cancelled"}))
        self.assertIsNone(make_server().handle_message({"jsonrpc": "2.0", "method": "notifications/bogus"}))


class ToolsListTest(BaseTestCase):
    def test_tools_list_has_26_tools(self) -> None:
        response = make_server().handle_message(request(10, "tools/list"))
        tools = response["result"]["tools"]
        self.assertEqual(len(tools), EXPECTED_TOOL_COUNT)
        self.assertEqual([tool["name"] for tool in tools], self.spec.tool_names)

    def test_tools_list_schema_matches_spec(self) -> None:
        response = make_server().handle_message(request(11, "tools/list"))
        tools = {tool["name"]: tool for tool in response["result"]["tools"]}
        asset_tool = tools["get_asset_by_id"]
        self.assertEqual(asset_tool["inputSchema"]["required"], ["assetId"])
        self.assertEqual(asset_tool["inputSchema"]["type"], "object")
        self.assertEqual(asset_tool["inputSchema"]["properties"]["assetId"]["type"], "string")
        self.assertNotIn("title", asset_tool)
        for name, tool in tools.items():
            self.assertTrue(tool["description"], f"{name} 缺少 description")
            self.assertEqual(tool["inputSchema"]["type"], "object")

    def test_tools_list_schema_required_matches_spec_for_all(self) -> None:
        response = make_server().handle_message(request(12, "tools/list"))
        for tool in response["result"]["tools"]:
            spec_tool = self.spec.get(tool["name"])
            self.assertEqual(tool["inputSchema"], spec_tool.input_schema())
            self.assertEqual(tool["description"], spec_tool.description())


class ToolsCallTest(BaseTestCase):
    def test_tools_call_success(self) -> None:
        response = make_server().handle_message(
            request(
                20,
                "tools/call",
                {"name": "get_asset_by_id", "arguments": {"assetId": "AST-102-0001"}},
            )
        )
        result = response["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(len(result["content"]), 1)
        self.assertEqual(result["content"][0]["type"], "text")
        payload = json.loads(result["content"][0]["text"])
        self.assertEqual(payload["code"], 0)
        self.assertEqual(payload["data"]["assetName"], "1号主变")

    def test_tools_call_without_arguments_uses_defaults(self) -> None:
        response = make_server().handle_message(
            request(21, "tools/call", {"name": "get_device_tree_root"})
        )
        result = response["result"]
        self.assertFalse(result["isError"])
        payload = json.loads(result["content"][0]["text"])
        self.assertEqual(payload["data"]["nodeId"], "ROOT")

    def test_tools_call_paged_tool(self) -> None:
        response = make_server().handle_message(
            request(
                22,
                "tools/call",
                {"name": "list_psr_by_filters", "arguments": {"deviceType": "变压器", "pageSize": 5}},
            )
        )
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(payload["data"]["total"], 1)
        self.assertEqual(payload["meta"]["paged"], True)

    def test_unknown_tool_is_invalid_params(self) -> None:
        response = make_server().handle_message(
            request(23, "tools/call", {"name": "no_such_tool", "arguments": {}})
        )
        self.assertEqual(response["error"]["code"], mcp_server.INVALID_PARAMS)
        self.assertIn("no_such_tool", response["error"]["message"])
        self.assertEqual(response["error"]["data"]["code"], ErrorCode.UNKNOWN_TOOL)

    def test_missing_required_argument_is_invalid_params(self) -> None:
        response = make_server().handle_message(
            request(24, "tools/call", {"name": "get_asset_by_id", "arguments": {}})
        )
        self.assertEqual(response["error"]["code"], mcp_server.INVALID_PARAMS)
        self.assertIn("assetId", response["error"]["message"])
        self.assertEqual(response["error"]["data"]["details"]["missing"], ["assetId"])
        self.assertEqual(response["error"]["data"]["code"], ErrorCode.INVALID_PARAM)

    def test_unknown_argument_is_invalid_params(self) -> None:
        response = make_server().handle_message(
            request(
                25,
                "tools/call",
                {"name": "get_asset_by_id", "arguments": {"assetId": "A1", "extra": 1}},
            )
        )
        self.assertEqual(response["error"]["code"], mcp_server.INVALID_PARAMS)

    def test_arguments_not_object(self) -> None:
        response = make_server().handle_message(
            request(26, "tools/call", {"name": "get_asset_by_id", "arguments": [1, 2]})
        )
        self.assertEqual(response["error"]["code"], mcp_server.INVALID_PARAMS)

    def test_missing_tool_name(self) -> None:
        response = make_server().handle_message(request(27, "tools/call", {"arguments": {}}))
        self.assertEqual(response["error"]["code"], mcp_server.INVALID_PARAMS)

    def test_tools_call_params_not_object(self) -> None:
        response = make_server().handle_message(request(28, "tools/call", ["nope"]))
        self.assertEqual(response["error"]["code"], mcp_server.INVALID_PARAMS)

    def test_business_error_is_returned_with_is_error(self) -> None:
        class BrokenClient:
            auth_mode = "token"
            spec = SimpleNamespace(tools=[], path="<stub>")

            def tool_schemas(self):
                return []

            def call_tool(self, name, params):
                raise PmsError(ErrorCode.NETWORK, "无法连接网关", retryable=True)

        response = make_server(BrokenClient()).handle_message(
            request(29, "tools/call", {"name": "get_asset_by_id", "arguments": {"assetId": "A1"}})
        )
        result = response["result"]
        self.assertTrue(result["isError"])
        error = json.loads(result["content"][0]["text"])["error"]
        self.assertEqual(error["code"], ErrorCode.NETWORK)
        self.assertTrue(error["retryable"])

    def test_unexpected_exception_does_not_break_process(self) -> None:
        class ExplodingClient:
            auth_mode = "mock"
            spec = SimpleNamespace(tools=[], path="<stub>")

            def tool_schemas(self):
                return []

            def call_tool(self, name, params):
                raise RuntimeError("boom")

        response = make_server(ExplodingClient()).handle_message(
            request(30, "tools/call", {"name": "get_asset_by_id", "arguments": {"assetId": "A1"}})
        )
        self.assertEqual(response["error"]["code"], mcp_server.INTERNAL_ERROR)


class ProtocolErrorTest(BaseTestCase):
    def test_unknown_method(self) -> None:
        response = make_server().handle_message(request(40, "resources/read"))
        self.assertEqual(response["error"]["code"], mcp_server.METHOD_NOT_FOUND)
        self.assertIn("resources/read", response["error"]["message"])

    def test_invalid_request(self) -> None:
        response = make_server().handle_message({"id": 41, "method": "ping"})
        self.assertEqual(response["error"]["code"], mcp_server.INVALID_REQUEST)
        self.assertEqual(response["id"], 41)

    def test_non_object_message(self) -> None:
        response = make_server().handle_message("hello")
        self.assertEqual(response["error"]["code"], mcp_server.INVALID_REQUEST)
        self.assertIsNone(response["id"])

    def test_missing_method(self) -> None:
        response = make_server().handle_message({"jsonrpc": "2.0", "id": 42})
        self.assertEqual(response["error"]["code"], mcp_server.INVALID_REQUEST)

    def test_parse_error_line(self) -> None:
        line = make_server().handle_line("this is not json")
        message = json.loads(line)
        self.assertEqual(message["error"]["code"], mcp_server.PARSE_ERROR)
        self.assertIsNone(message["id"])

    def test_parse_error_does_not_stop_following_requests(self) -> None:
        server = make_server()
        self.assertIsNotNone(server.handle_line("{bad json"))
        response = json.loads(server.handle_line(json.dumps(request(43, "ping"))))
        self.assertEqual(response["result"], {})

    def test_blank_line_ignored(self) -> None:
        server = make_server()
        self.assertIsNone(server.handle_line(""))
        self.assertIsNone(server.handle_line("   \r\n"))

    def test_batch_request(self) -> None:
        server = make_server()
        line = json.dumps([request(44, "ping"), {"jsonrpc": "2.0", "method": "notifications/initialized"}])
        response = json.loads(server.handle_line(line))
        self.assertIsInstance(response, list)
        self.assertEqual(len(response), 1)
        self.assertEqual(response[0]["result"], {})


class ServeStdioTest(BaseTestCase):
    def test_handshake_over_stdio(self) -> None:
        lines = [
            json.dumps(
                request(
                    1,
                    "initialize",
                    {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "t"}},
                )
            )
            + "\n",
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n",
            json.dumps(request(2, "tools/list")) + "\n",
            json.dumps(
                request(
                    3,
                    "tools/call",
                    {"name": "get_asset_by_id", "arguments": {"assetId": "AST-102-0001"}},
                )
            )
            + "\n",
        ]
        stdout = io.StringIO()
        stderr = io.StringIO()
        exit_code = mcp_server.serve_stdio(
            make_server(), stdin=io.StringIO("".join(lines)), stdout=stdout, stderr=stderr
        )
        self.assertEqual(exit_code, 0)
        output_lines = [line for line in stdout.getvalue().splitlines() if line.strip()]
        self.assertEqual(len(output_lines), 3)  # 通知无响应
        messages = [json.loads(line) for line in output_lines]
        self.assertEqual(messages[0]["id"], 1)
        self.assertEqual(messages[1]["result"]["tools"].__len__(), EXPECTED_TOOL_COUNT)
        self.assertEqual(messages[2]["id"], 3)
        self.assertFalse(messages[2]["result"]["isError"])
        # stdout 只能是协议消息；日志在 stderr
        self.assertIn("[pms-gateway-mcp]", stderr.getvalue())

    def test_serve_continues_after_bad_line(self) -> None:
        lines = [
            "not json\n",
            json.dumps(request(1, "ping")) + "\n",
            "\n",
            json.dumps(request(2, "ping")) + "\n",
        ]
        stdout = io.StringIO()
        stderr = io.StringIO()
        mcp_server.serve_stdio(make_server(), stdin=io.StringIO("".join(lines)), stdout=stdout, stderr=stderr)
        messages = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
        self.assertEqual(len(messages), 3)
        self.assertEqual(messages[0]["error"]["code"], mcp_server.PARSE_ERROR)
        self.assertEqual(messages[1]["id"], 1)
        self.assertEqual(messages[2]["id"], 2)
        self.assertTrue(stdout.getvalue().count("{") >= 3)

    def test_log_goes_to_stderr_only(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        mcp_server.serve_stdio(make_server(), stdin=io.StringIO(""), stdout=stdout, stderr=stderr)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("stdio 服务已启动", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
