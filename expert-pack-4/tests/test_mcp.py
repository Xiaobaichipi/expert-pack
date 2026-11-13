from __future__ import annotations

import os
import sys
import unittest

from expert_pack.adapters.mcp_stdio import McpStdioClient, McpToolProvider
from expert_pack.errors import McpError


def demo_provider(timeout: float = 15.0) -> McpToolProvider:
    return McpToolProvider(
        "demo",
        sys.executable,
        ["-m", "expert_pack.builtin.mcp_demo_server"],
        timeout=timeout,
        env={"PYTHONPATH": str(os.getcwd()), "PYTHONUTF8": "1"},
    )


class McpTest(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = demo_provider()

    def tearDown(self) -> None:
        self.provider.close()

    def test_list_tools(self) -> None:
        specs = self.provider.list_tools()
        self.assertEqual([spec.name for spec in specs], ["lookup", "calc"])
        self.assertEqual(specs[0].action_id, "tool:demo/lookup")
        self.assertIn("required", specs[0].input_schema)

    def test_call_tool(self) -> None:
        result = self.provider.call_tool("calc", {"expression": "42*3"})
        self.assertTrue(result.ok)
        self.assertEqual(result.content, "126")

    def test_tool_error_is_a_failed_result(self) -> None:
        result = self.provider.call_tool("lookup", {"item": "zeta"})
        self.assertFalse(result.ok)
        self.assertIn("unknown item", result.error)

    def test_missing_argument_error(self) -> None:
        result = self.provider.call_tool("calc", {})
        self.assertFalse(result.ok)
        self.assertIn("missing operand", result.error)

    def test_tool_listing_is_cached(self) -> None:
        first = self.provider.list_tools()
        second = self.provider.list_tools()
        self.assertEqual([s.name for s in first], [s.name for s in second])

    def test_bad_command_raises_mcp_error(self) -> None:
        provider = McpToolProvider("missing", "definitely-not-a-real-command-xyz")
        with self.assertRaises(McpError) as caught:
            provider.list_tools()
        self.assertIn("cannot start MCP server", str(caught.exception))
        provider.close()

    def test_raw_client_speaks_jsonrpc(self) -> None:
        client = McpStdioClient(
            sys.executable,
            ["-m", "expert_pack.builtin.mcp_demo_server"],
            timeout=15,
            env={"PYTHONPATH": str(os.getcwd()), "PYTHONUTF8": "1"},
        )
        try:
            with client:
                result = client.request("tools/list")
                self.assertEqual(len(result["tools"]), 2)
                self.assertEqual(client.server_info["name"], "expert-pack-demo")
        finally:
            client.close()

    def test_unknown_method_raises(self) -> None:
        client = McpStdioClient(
            sys.executable,
            ["-m", "expert_pack.builtin.mcp_demo_server"],
            timeout=15,
            env={"PYTHONPATH": str(os.getcwd()), "PYTHONUTF8": "1"},
        )
        try:
            with self.assertRaises(McpError) as caught:
                client.request("resources/list")
            self.assertIn("method not found", str(caught.exception))
        finally:
            client.close()


class DemoServerUnitTest(unittest.TestCase):
    """Exercise the server handler without a subprocess."""

    def test_handle_initialize(self) -> None:
        from expert_pack.builtin import mcp_demo_server as server

        response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        self.assertEqual(response["result"]["serverInfo"]["name"], "expert-pack-demo")

    def test_handle_notification_has_no_response(self) -> None:
        from expert_pack.builtin import mcp_demo_server as server

        self.assertEqual(server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}), {})

    def test_calc_is_safe(self) -> None:
        from expert_pack.builtin import mcp_demo_server as server

        text, is_error = server._call("calc", {"expression": "__import__('os').system('echo hi')"})
        self.assertTrue(is_error)
        self.assertIn("cannot evaluate", text)


if __name__ == "__main__":
    unittest.main()
