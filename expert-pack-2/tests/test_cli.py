"""CLI 测试：参数解析、子命令输出、退出码与错误输出。"""

from __future__ import annotations

import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

import json
import unittest
import uuid

from _support import EXPECTED_TOOL_COUNT, TESTS_DIR, Capture

import pms_cli


def run_main(argv) -> tuple[int, str, str]:
    with Capture() as capture:
        try:
            code = pms_cli.main(argv)
        except SystemExit as exc:  # argparse 的 --version / 错误退出
            code = int(exc.code or 0)
    return code, capture.stdout.getvalue(), capture.stderr.getvalue()


class ParserTest(unittest.TestCase):
    def test_list_tools_parsed(self) -> None:
        args = pms_cli.build_parser().parse_args(["list-tools"])
        self.assertEqual(args.command, "list-tools")
        self.assertIs(args.func, pms_cli.cmd_list_tools)
        self.assertIsNone(args.group)

    def test_describe_parsed(self) -> None:
        args = pms_cli.build_parser().parse_args(["describe", "get_asset_by_id"])
        self.assertEqual(args.tool, "get_asset_by_id")
        self.assertIs(args.func, pms_cli.cmd_describe)

    def test_call_parsed(self) -> None:
        args = pms_cli.build_parser().parse_args(
            ["call", "get_asset_by_id", "--params", '{"assetId":"AST-102-0001"}']
        )
        self.assertEqual(args.command, "call")
        self.assertEqual(args.tool, "get_asset_by_id")
        self.assertEqual(args.params, '{"assetId":"AST-102-0001"}')
        self.assertIs(args.func, pms_cli.cmd_call)

    def test_serve_and_doctor_parsed(self) -> None:
        self.assertIs(pms_cli.build_parser().parse_args(["serve"]).func, pms_cli.cmd_serve)
        doctor = pms_cli.build_parser().parse_args(["doctor"])
        self.assertIs(doctor.func, pms_cli.cmd_doctor)
        self.assertFalse(doctor.no_probe)

    def test_global_options_before_and_after_subcommand(self) -> None:
        before = pms_cli.build_parser().parse_args(["--auth-mode", "mock", "list-tools"])
        self.assertEqual(before.auth_mode, "mock")
        after = pms_cli.build_parser().parse_args(["list-tools", "--auth-mode", "mock"])
        self.assertEqual(after.auth_mode, "mock")

    def test_global_options_default_to_unset(self) -> None:
        args = pms_cli.build_parser().parse_args(["list-tools"])
        for name in ("spec", "auth_mode", "base_url", "timeout", "retry", "compact"):
            self.assertFalse(hasattr(args, name), f"{name} 不应有默认值，以便回落到环境变量")

    def test_invalid_auth_mode_rejected(self) -> None:
        with Capture():
            with self.assertRaises(SystemExit) as ctx:
                pms_cli.build_parser().parse_args(["list-tools", "--auth-mode", "oauth"])
        self.assertEqual(ctx.exception.code, 2)

    def test_version(self) -> None:
        with Capture() as capture:
            with self.assertRaises(SystemExit) as ctx:
                pms_cli.build_parser().parse_args(["--version"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn("pms-gateway-mcp", capture.stdout.getvalue())


class ListToolsCommandTest(unittest.TestCase):
    def test_list_tools_prints_26(self) -> None:
        code, stdout, stderr = run_main(["list-tools"])
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertEqual(payload["count"], EXPECTED_TOOL_COUNT)
        self.assertEqual(payload["totalTools"], EXPECTED_TOOL_COUNT)
        self.assertEqual(len(payload["tools"]), EXPECTED_TOOL_COUNT)
        self.assertEqual(len(payload["groups"]), 6)
        first = payload["tools"][0]
        for key in ("name", "title", "code", "group", "method", "path", "required"):
            self.assertIn(key, first)

    def test_list_tools_filter_group(self) -> None:
        code, stdout, _ = run_main(["list-tools", "--group", "asset-ledger"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["count"], 5)
        self.assertTrue(all(tool["group"] == "asset-ledger" for tool in payload["tools"]))

    def test_list_tools_invalid_group(self) -> None:
        code, stdout, stderr = run_main(["list-tools", "--group", "nope"])
        self.assertEqual(code, pms_cli.EXIT_USAGE_ERROR)
        self.assertEqual(stdout, "")
        self.assertEqual(json.loads(stderr)["error"]["code"], "USAGE_ERROR")

    def test_compact_output_is_single_line(self) -> None:
        code, stdout, _ = run_main(["list-tools", "--compact"])
        self.assertEqual(code, 0)
        self.assertEqual(len(stdout.strip().splitlines()), 1)
        self.assertEqual(json.loads(stdout)["count"], EXPECTED_TOOL_COUNT)


class DescribeCommandTest(unittest.TestCase):
    def test_describe_asset_tool(self) -> None:
        code, stdout, _ = run_main(["describe", "get_asset_by_id"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["name"], "get_asset_by_id")
        self.assertEqual(payload["code"], "pgp-102-2411-00102")
        self.assertEqual(payload["inputSchema"]["required"], ["assetId"])
        self.assertEqual(payload["exampleParams"]["assetId"], "AST-102-0001")
        self.assertIn("cliExample", payload)

    def test_describe_paged_tool(self) -> None:
        code, stdout, _ = run_main(["describe", "inquire_defect"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["method"], "POST")
        self.assertIn("list", payload["responseHint"].get("listKey", "list"))
        self.assertTrue(payload["typicalQuestions"])

    def test_describe_unknown_tool(self) -> None:
        code, stdout, stderr = run_main(["describe", "no_such_tool"])
        self.assertEqual(code, pms_cli.EXIT_RUNTIME_ERROR)
        self.assertEqual(stdout, "")
        self.assertEqual(json.loads(stderr)["error"]["code"], "UNKNOWN_TOOL")


class CallCommandTest(unittest.TestCase):
    def test_call_get_asset_by_id(self) -> None:
        code, stdout, stderr = run_main(
            ["call", "get_asset_by_id", "--params", '{"assetId":"AST-102-0001"}']
        )
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertEqual(payload["code"], 0)
        self.assertEqual(payload["data"]["assetName"], "1号主变")
        self.assertEqual(payload["meta"]["mode"], "mock")

    def test_call_without_params_for_optional_tool(self) -> None:
        code, stdout, _ = run_main(["call", "get_device_tree_root"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["data"]["nodeId"], "ROOT")

    def test_call_with_items(self) -> None:
        code, stdout, _ = run_main(["call", "list_psr_by_filters", "--with-items", "--params", '{"pageSize":1}'])
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["total"], 2)
        self.assertEqual(len(payload["items"]), 1)

    def test_call_compact(self) -> None:
        code, stdout, _ = run_main(
            ["call", "get_asset_by_id", "--params", '{"assetId":"AST-102-0001"}', "--compact"]
        )
        self.assertEqual(code, 0)
        self.assertEqual(len(stdout.strip().splitlines()), 1)

    def test_call_bad_json_exit_2(self) -> None:
        code, stdout, stderr = run_main(["call", "get_asset_by_id", "--params", "{oops}"])
        self.assertEqual(code, pms_cli.EXIT_USAGE_ERROR)
        self.assertEqual(stdout, "")
        self.assertEqual(json.loads(stderr)["error"]["code"], "USAGE_ERROR")

    def test_call_non_object_params_exit_2(self) -> None:
        code, _, stderr = run_main(["call", "get_asset_by_id", "--params", "[1,2]"])
        self.assertEqual(code, pms_cli.EXIT_USAGE_ERROR)
        self.assertIn("JSON 对象", json.loads(stderr)["error"]["message"])

    def test_call_missing_required_exit_1(self) -> None:
        code, stdout, stderr = run_main(["call", "get_asset_by_id", "--params", "{}"])
        self.assertEqual(code, pms_cli.EXIT_RUNTIME_ERROR)
        self.assertEqual(stdout, "")
        payload = json.loads(stderr)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "INVALID_PARAM")
        self.assertIn("assetId", payload["error"]["message"])

    def test_call_unknown_tool_exit_1(self) -> None:
        code, _, stderr = run_main(["call", "bogus", "--params", "{}"])
        self.assertEqual(code, pms_cli.EXIT_RUNTIME_ERROR)
        self.assertEqual(json.loads(stderr)["error"]["code"], "UNKNOWN_TOOL")

    def test_call_params_file(self) -> None:
        params_file = TESTS_DIR / f"_tmp_params_{uuid.uuid4().hex}.json"
        params_file.write_text('{"assetId": "AST-102-0001"}', encoding="utf-8")
        try:
            code, stdout, _ = run_main(["call", "get_asset_by_id", "--params-file", str(params_file)])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(stdout)["data"]["assetId"], "AST-102-0001")
        finally:
            params_file.unlink(missing_ok=True)

    def test_call_params_and_file_conflict(self) -> None:
        code, _, stderr = run_main(
            ["call", "get_asset_by_id", "--params", "{}", "--params-file", "x.json"]
        )
        self.assertEqual(code, pms_cli.EXIT_USAGE_ERROR)
        self.assertIn("二选一", json.loads(stderr)["error"]["message"])

    def test_call_missing_params_file(self) -> None:
        code, _, stderr = run_main(["call", "get_asset_by_id", "--params-file", "no_such_file.json"])
        self.assertEqual(code, pms_cli.EXIT_USAGE_ERROR)


class DoctorCommandTest(unittest.TestCase):
    def test_doctor_ok(self) -> None:
        code, stdout, _ = run_main(["doctor"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["toolCount"], EXPECTED_TOOL_COUNT)
        self.assertEqual(payload["config"]["authMode"], "mock")
        self.assertEqual(payload["mockProbe"]["total"], EXPECTED_TOOL_COUNT)
        self.assertEqual(payload["mockProbe"]["ok"], EXPECTED_TOOL_COUNT)
        self.assertEqual(payload["mockProbe"]["failed"], [])
        self.assertEqual(payload["problems"], [])

    def test_doctor_no_probe(self) -> None:
        code, stdout, _ = run_main(["doctor", "--no-probe"])
        self.assertEqual(code, 0)
        self.assertIsNone(json.loads(stdout)["mockProbe"])

    def test_doctor_token_mode_without_credentials_fails(self) -> None:
        code, stdout, _ = run_main(["--auth-mode", "token", "doctor", "--no-probe"])
        self.assertEqual(code, pms_cli.EXIT_RUNTIME_ERROR)
        payload = json.loads(stdout)
        self.assertFalse(payload["ok"])
        self.assertTrue(any("PMS_TOKEN" in problem for problem in payload["problems"]))

    def test_doctor_explicit_spec_path(self) -> None:
        from _support import SPEC_PATH

        code, stdout, _ = run_main(["--spec", str(SPEC_PATH), "doctor", "--no-probe"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["spec"]["toolCount"], EXPECTED_TOOL_COUNT)


class MainUsageTest(unittest.TestCase):
    def test_no_command_exit_2(self) -> None:
        code, stdout, stderr = run_main([])
        self.assertEqual(code, pms_cli.EXIT_USAGE_ERROR)
        self.assertEqual(stdout, "")
        self.assertIn("usage", stderr.lower())

    def test_serve_dispatch_is_not_executed_on_import(self) -> None:
        # 只验证 serve 子命令指向正确的处理函数，不在测试中真的阻塞监听
        args = pms_cli.build_parser().parse_args(["serve"])
        self.assertIs(args.func, pms_cli.cmd_serve)


if __name__ == "__main__":
    unittest.main()
