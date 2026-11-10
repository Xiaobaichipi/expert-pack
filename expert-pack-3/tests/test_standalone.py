#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""独立拆分包（standalone/）回归测试：布局、模拟数据、上传包、两个 MCP 协议。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import unittest
import zipfile
from pathlib import Path

from _support import PACK_DIR, PmsClient, PmsConfig, BaseTestCase

STANDALONE = PACK_DIR / "standalone"
DIST = PACK_DIR / "dist-standalone"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class StandaloneLayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = read_json(STANDALONE / "index.json")

    def test_layout_counts(self) -> None:
        self.assertEqual(self.index["skillCount"], 12)
        self.assertEqual(self.index["mcpCount"], 2)
        for item in self.index["skills"]:
            skill_dir = STANDALONE / "skills" / item["slug"]
            self.assertTrue((skill_dir / "SKILL.md").is_file(), item["slug"])
            self.assertTrue((skill_dir / "mock" / "samples.json").is_file(), item["slug"])
        for item in self.index["mcpServers"]:
            self.assertTrue((STANDALONE / "mcp-servers" / item["slug"] / "README.md").is_file())

    def test_skill_frontmatter(self) -> None:
        for item in self.index["skills"]:
            text = (STANDALONE / "skills" / item["slug"] / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("slug: " + item["slug"], text)
            self.assertIn("version: ", text)
            self.assertIn("displayName: ", text)


class StandaloneMockTest(unittest.TestCase):
    def test_mock_samples_are_usable(self) -> None:
        spec = read_json(PACK_DIR / "spec" / "interfaces.json")
        tool_names = {tool["name"] for tool in spec["tools"]}
        index = read_json(STANDALONE / "index.json")
        for item in index["skills"]:
            sample = read_json(STANDALONE / "skills" / item["slug"] / "mock" / "samples.json")
            self.assertIn("模拟数据", sample["note"])
            if item["slug"] == "substation-analysis-mcp":
                self.assertEqual(sample["results"]["health"]["score"], 75.8)
                continue
            calls = sample["calls"]
            self.assertTrue(calls, item["slug"])
            if item["slug"] == "pms-gateway-mcp":
                self.assertEqual(len(calls), 26)
            for call in calls:
                self.assertIn(call["tool"], tool_names, item["slug"])
                self.assertTrue(call["response"], call["tool"])

    def test_pms_spec_snapshot_matches_pack(self) -> None:
        standalone_spec = STANDALONE / "skills" / "pms-gateway-mcp" / "references" / "interfaces.json"
        self.assertEqual(standalone_spec.read_bytes(), (PACK_DIR / "spec" / "interfaces.json").read_bytes())


class StandaloneArchiveTest(unittest.TestCase):
    def test_zips_and_checksums(self) -> None:
        checksums = (DIST / "checksums.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(checksums), 14)
        for line in checksums:
            digest, name = line.split()
            target = DIST / name
            self.assertTrue(target.is_file(), name)
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), digest, name)

    def test_skill_zip_contains_skill_and_mock(self) -> None:
        index = read_json(STANDALONE / "index.json")
        for item in index["skills"]:
            path = PACK_DIR / item["zip"]
            with zipfile.ZipFile(str(path)) as zf:
                self.assertIn("SKILL.md", zf.namelist(), path.name)
                self.assertIn("mock/samples.json", zf.namelist(), path.name)


class StandaloneMcpTest(BaseTestCase):
    def test_pms_mcp_protocol(self) -> None:
        server_path = STANDALONE / "skills" / "pms-gateway-mcp" / "scripts" / "mcp_server.py"
        spec_path = STANDALONE / "skills" / "pms-gateway-mcp" / "references" / "interfaces.json"
        mcp_server = load_module("standalone_pms_mcp", server_path)
        client = PmsClient(PmsConfig(base_url="", auth_mode="mock", spec_path=str(spec_path)))
        server = mcp_server.McpServer(client)
        init = server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test"}},
            }
        )
        self.assertEqual(init["result"]["serverInfo"]["name"], "pms-gateway-mcp")
        tools = server.handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual(len(tools["result"]["tools"]), 26)
        call = server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "get_asset_by_id", "arguments": {"assetId": "AST-102-0001"}},
            }
        )
        self.assertFalse(call["result"]["isError"])
        payload = json.loads(call["result"]["content"][0]["text"])
        self.assertEqual(payload["data"]["assetName"], "1号主变")

    def test_analysis_mcp_protocol(self) -> None:
        analysis_scripts = STANDALONE / "skills" / "substation-analysis-mcp" / "scripts"
        if str(analysis_scripts) not in sys.path:
            sys.path.insert(0, str(analysis_scripts))
        mcp_path = analysis_scripts / "analysis_mcp.py"
        analysis_mcp = load_module("standalone_analysis_mcp", mcp_path)
        bundle = read_json(STANDALONE / "skills" / "substation-analysis-mcp" / "assets" / "demo_bundle.json")
        server = analysis_mcp.AnalysisMcpServer()
        init = server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test"}},
            }
        )
        self.assertEqual(init["result"]["serverInfo"]["name"], "substation-analysis-mcp")
        tools = server.handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual(len(tools["result"]["tools"]), 7)
        call = server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "assess_device_health", "arguments": {"bundle": bundle}},
            }
        )
        self.assertFalse(call["result"]["isError"])
        payload = json.loads(call["result"]["content"][0]["text"])
        self.assertEqual(payload["score"], 75.8)


if __name__ == "__main__":
    unittest.main()
