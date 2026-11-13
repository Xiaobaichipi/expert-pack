#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PMS × MCP 集成测试：26 工具、按参数过滤对象查询、任务集完整性。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[2]
PMS_SKILL = WORKSPACE / "expert-pack-3" / "skills" / "pms-gateway-mcp"
PMS_SCRIPTS = PMS_SKILL / "scripts"
MCP_SERVER = PMS_SCRIPTS / "mcp_server.py"

if str(PMS_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PMS_SCRIPTS))

HAVE_PMS = MCP_SERVER.is_file()


@unittest.skipUnless(HAVE_PMS, "需要同级的 expert-pack-3（PMS mock 网关）")
class PmsIntegrationTest(unittest.TestCase):
    def test_tools_are_loaded_and_object_query_filters_by_id(self) -> None:
        from expert_pack.adapters.mcp_stdio import McpToolProvider
        from mock_gateway.server import start_server

        server = start_server("127.0.0.1", 0, "token")
        provider = McpToolProvider(
            "pms",
            sys.executable,
            [str(MCP_SERVER)],
            cwd=str(PMS_SKILL),
            env={
                "PMS_AUTH_MODE": "token",
                "PMS_GATEWAY_BASE_URL": server.base_url,
                "PMS_TOKEN": server.auth.token,
            },
            timeout=20.0,
        )
        try:
            specs = provider.list_tools()
            self.assertEqual(len(specs), 26)
            result = provider.call_tool("get_asset_by_id", {"assetId": "AST-102-0003"})
            self.assertTrue(result.ok)
            self.assertIn("AST-102-0003", result.content)
            self.assertIn("SSZ11-50000/110", result.content)
        finally:
            provider.close()
            server.stop()


class PmsTaskTest(unittest.TestCase):
    def test_task_suite_shape(self) -> None:
        from expert_pack.extensions.pms.tasks import FAMILY_MAX_STEPS, PMS_FAMILIES, build_tasks

        tasks = build_tasks()
        self.assertEqual(len(tasks), 42)
        self.assertEqual(len({task.id for task in tasks}), len(tasks))
        for task in tasks:
            self.assertEqual(task.max_steps, FAMILY_MAX_STEPS[task.family], task.id)
        families = {task.family for task in tasks}
        self.assertEqual(families, set(PMS_FAMILIES))
        for task in tasks:
            self.assertTrue(task.context.get("expect"), task.id)
            self.assertTrue(task.family, task.id)

    def test_extended_task_suite_shape(self) -> None:
        from expert_pack.extensions.pms.tasks import build_extended_tasks

        tasks = build_extended_tasks()
        self.assertEqual(len(tasks), 66)
        self.assertEqual(len({task.id for task in tasks}), len(tasks))
        self.assertTrue(all(task.context.get("expect") for task in tasks))
        self.assertTrue(any("STA-220-11" in task.goal for task in tasks))

    def test_realistic_task_suite_shape(self) -> None:
        from expert_pack.extensions.pms.tasks_realistic import build_realistic_tasks

        tasks = build_realistic_tasks()
        self.assertEqual(len(tasks), 33)
        self.assertEqual(len({task.id for task in tasks}), len(tasks))
        self.assertTrue(all(task.context.get("expect") for task in tasks))
        self.assertTrue(any("STA-35-12" in task.goal for task in tasks))

    def test_complex_task_suite_shape(self) -> None:
        from expert_pack.extensions.pms.tasks_complex import build_complex_tasks

        tasks = build_complex_tasks()
        self.assertEqual(len(tasks), 26)
        self.assertEqual(len({task.id for task in tasks}), len(tasks))
        self.assertTrue(all(task.context.get("expect") for task in tasks))
        self.assertTrue(any("global" in task.id for task in tasks))


if __name__ == "__main__":
    unittest.main()
