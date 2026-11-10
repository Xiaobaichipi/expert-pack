#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""expert-pack-3 · 离线验证独立拆分包（不访问外网、不需要真实 PMS 中台）。

检查项：
1. standalone/ 布局与 index.json；
2. 12 个技能包：SKILL.md frontmatter、mock/samples.json、接口工具名合法；
3. 2 个 MCP 包：pms spec 快照、CLI doctor、mock 客户端、本地 token 网关、stdio MCP 协议；
4. 分析 MCP：CLI demo、stdio MCP 协议、演示 bundle 健康分 75.8；
5. dist-standalone 上传包与 checksums.txt。

用法（在 expert-pack-3 根目录或 standalone/ 内均可）：
    python tools/verify_standalone.py
    python standalone/verify_offline.py
"""

from __future__ import annotations

import hashlib
import importlib
import io
import json
import os
import sys
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
STANDALONE = HERE if (HERE / "index.json").is_file() else HERE.parent / "standalone"
ROOT = STANDALONE.parent
DIST = ROOT / "dist-standalone"

PMS_SKILL = STANDALONE / "skills" / "pms-gateway-mcp"
ANALYSIS_SKILL = STANDALONE / "skills" / "substation-analysis-mcp"
PMS_SCRIPTS = PMS_SKILL / "scripts"
ANALYSIS_SCRIPTS = ANALYSIS_SKILL / "scripts"
SPEC_PATH = PMS_SKILL / "references" / "interfaces.json"

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, fn: Callable[[], None]) -> None:
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS.append((name, False, "%s: %s" % (type(exc).__name__, exc)))
    else:
        RESULTS.append((name, True, ""))


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_frontmatter(text: str) -> dict[str, str]:
    import re

    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not match:
        return {}
    result: dict[str, str] = {}
    for line in match.group(1).splitlines():
        item = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.+)$", line)
        if item:
            result[item.group(1)] = item.group(2).strip().strip("\"'")
    return result


# ---------------------------------------------------------------------------
# 1. 布局 / 技能包 / 模拟数据
# ---------------------------------------------------------------------------
def check_layout() -> None:
    index = read_json(STANDALONE / "index.json")
    skills = index["skills"]
    mcps = index["mcpServers"]
    assert_true(len(skills) == 12, "技能包数量应为 12，实际 %d" % len(skills))
    assert_true(len(mcps) == 2, "MCP 包数量应为 2，实际 %d" % len(mcps))
    for item in skills:
        skill_dir = STANDALONE / "skills" / item["slug"]
        assert_true(skill_dir.is_dir(), "缺少技能目录：%s" % skill_dir)
        assert_true((skill_dir / "SKILL.md").is_file(), "缺少 SKILL.md：%s" % item["slug"])
        assert_true((skill_dir / "mock" / "samples.json").is_file(), "缺少模拟样例：%s" % item["slug"])
    for item in mcps:
        mcp_dir = STANDALONE / "mcp-servers" / item["slug"]
        assert_true(mcp_dir.is_dir(), "缺少 MCP 目录：%s" % mcp_dir)
        assert_true((mcp_dir / "README.md").is_file(), "缺少 MCP README：%s" % item["slug"])


def check_frontmatter() -> None:
    index = read_json(STANDALONE / "index.json")
    for item in index["skills"]:
        text = (STANDALONE / "skills" / item["slug"] / "SKILL.md").read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        assert_true(fm.get("slug") == item["slug"], "%s：frontmatter slug 不一致" % item["slug"])
        assert_true(bool(fm.get("version")), "%s：缺少 version" % item["slug"])
        assert_true(bool(fm.get("displayName")), "%s：缺少 displayName" % item["slug"])


def check_mock_samples() -> None:
    spec = read_json(SPEC_PATH)
    tool_names = {tool["name"] for tool in spec["tools"]}
    index = read_json(STANDALONE / "index.json")
    for item in index["skills"]:
        sample = read_json(STANDALONE / "skills" / item["slug"] / "mock" / "samples.json")
        assert_true(sample.get("note"), "%s：模拟样例缺少声明" % item["slug"])
        if item["slug"] == "substation-analysis-mcp":
            results = sample.get("results") or {}
            assert_true(results.get("health", {}).get("score") == 75.8,
                        "%s：演示 bundle 健康分应为 75.8" % item["slug"])
            assert_true(len(results.get("diagnosis", {}).get("hypotheses", [])) >= 1,
                        "%s：诊断结果为空" % item["slug"])
        elif item["slug"] == "pms-gateway-mcp":
            calls = sample.get("calls") or []
            assert_true(len(calls) == 26, "%s：应覆盖 26 个接口，实际 %d" % (item["slug"], len(calls)))
        else:
            calls = sample.get("calls") or []
            assert_true(bool(calls), "%s：模拟样例为空" % item["slug"])
            for call in calls:
                assert_true(call.get("tool") in tool_names, "%s：未知工具 %s" % (item["slug"], call.get("tool")))
                assert_true(bool(call.get("response")), "%s：%s 返回为空" % (item["slug"], call.get("tool")))


# ---------------------------------------------------------------------------
# 2. PMS 独立 MCP
# ---------------------------------------------------------------------------
def ensure_pms_imports() -> None:
    for path in (str(PMS_SCRIPTS),):
        if path not in sys.path:
            sys.path.insert(0, path)


def check_pms_spec_snapshot() -> None:
    spec = read_json(SPEC_PATH)
    assert_true(len(spec["tools"]) == 26, "spec 工具数应为 26，实际 %d" % len(spec["tools"]))
    pack_spec = ROOT / "spec" / "interfaces.json"
    if pack_spec.is_file():
        assert_true(SPEC_PATH.read_bytes() == pack_spec.read_bytes(), "独立包 spec 与专家包快照不一致")


def check_pms_doctor() -> None:
    ensure_pms_imports()
    old_cwd = os.getcwd()
    old_env = {key: os.environ.get(key) for key in
               ("PMS_SPEC_PATH", "PMS_GATEWAY_BASE_URL", "PMS_AUTH_MODE", "PMS_TOKEN",
                "PMS_APP_KEY", "PMS_APP_SECRET")}
    stdout = io.StringIO()
    try:
        for key in old_env:
            os.environ.pop(key, None)
        os.environ["PMS_AUTH_MODE"] = "mock"
        os.chdir(str(PMS_SKILL))
        import pms_cli  # noqa: PLC0415

        with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
            code = pms_cli.main(["doctor", "--compact"])
        assert_true(code == 0, "pms_cli doctor 退出码 %s" % code)
        report = json.loads(stdout.getvalue())
        assert_true(report.get("ok") is True, "doctor 自检未通过：%s" % report.get("problems"))
        assert_true(report.get("toolCount") == 26, "doctor 工具数应为 26")
    finally:
        os.chdir(old_cwd)
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def check_pms_mock_client() -> None:
    ensure_pms_imports()
    from pms_client import PmsClient, PmsConfig  # noqa: PLC0415

    client = PmsClient(PmsConfig(base_url="", auth_mode="mock", spec_path=str(SPEC_PATH)))
    data = client.call_tool("get_asset_by_id", {"assetId": "AST-102-0001"})["data"]
    assert_true(data.get("assetName") == "1号主变", "mock 客户端返回设备不符")


def check_pms_gateway() -> None:
    ensure_pms_imports()
    from pms_client import ErrorCode, PmsClient, PmsConfig, PmsError  # noqa: PLC0415
    from mock_gateway.server import start_server  # noqa: PLC0415

    server = start_server("127.0.0.1", 0, "token")
    try:
        client = PmsClient(
            PmsConfig(base_url=server.base_url, auth_mode="token", token=server.auth.token,
                      spec_path=str(SPEC_PATH), timeout=5)
        )
        data = client.call_tool("get_asset_by_id", {"assetId": "AST-102-0001"})["data"]
        assert_true(data.get("assetName") == "1号主变", "本地网关返回设备不符")

        bad = PmsClient(
            PmsConfig(base_url=server.base_url, auth_mode="token", token="wrong-token",
                      spec_path=str(SPEC_PATH), timeout=5, retry=0)
        )
        try:
            bad.call_tool("get_asset_by_id", {"assetId": "AST-102-0001"})
        except PmsError as exc:
            assert_true(exc.code == ErrorCode.AUTH_FAILED, "错误 token 应返回 AUTH_FAILED，实际 %s" % exc.code)
        else:
            raise AssertionError("错误 token 未被拒绝")
    finally:
        server.stop()


def check_pms_mcp() -> None:
    ensure_pms_imports()
    from pms_client import PmsClient, PmsConfig  # noqa: PLC0415
    import mcp_server  # noqa: PLC0415

    server = mcp_server.McpServer(PmsClient(PmsConfig(base_url="", auth_mode="mock", spec_path=str(SPEC_PATH))))
    init = server.handle_message({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                   "clientInfo": {"name": "offline-verify", "version": "1.0"}},
    })
    assert_true(init["result"]["serverInfo"]["name"] == "pms-gateway-mcp", "MCP serverInfo 不符")
    tools = server.handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert_true(len(tools["result"]["tools"]) == 26, "MCP tools/list 应返回 26 个工具")
    call = server.handle_message({
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "get_asset_by_id", "arguments": {"assetId": "AST-102-0001"}},
    })
    assert_true(call["result"]["isError"] is False, "MCP tools/call 不应报错")
    payload = json.loads(call["result"]["content"][0]["text"])
    assert_true(payload["data"]["assetName"] == "1号主变", "MCP tools/call 数据不符")


# ---------------------------------------------------------------------------
# 3. 分析独立 MCP
# ---------------------------------------------------------------------------
def ensure_analysis_imports() -> None:
    if str(ANALYSIS_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(ANALYSIS_SCRIPTS))


def check_analysis_cli() -> None:
    ensure_analysis_imports()
    old_cwd = os.getcwd()
    stdout = io.StringIO()
    try:
        os.chdir(str(ANALYSIS_SKILL))
        import analysis_cli  # noqa: PLC0415

        with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
            code = analysis_cli.main(["demo"])
        assert_true(code == 0, "analysis_cli demo 退出码 %s" % code)
        assert_true("75.8" in stdout.getvalue(), "demo 输出未包含健康分 75.8")
    finally:
        os.chdir(old_cwd)


def check_analysis_mcp() -> None:
    ensure_analysis_imports()
    import analysis_mcp  # noqa: PLC0415

    bundle = read_json(ANALYSIS_SKILL / "assets" / "demo_bundle.json")
    server = analysis_mcp.AnalysisMcpServer()
    init = server.handle_message({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                   "clientInfo": {"name": "offline-verify", "version": "1.0"}},
    })
    assert_true(init["result"]["serverInfo"]["name"] == "substation-analysis-mcp", "MCP serverInfo 不符")
    tools = server.handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert_true(len(tools["result"]["tools"]) == 7, "分析 MCP tools/list 应返回 7 个工具")
    call = server.handle_message({
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "assess_device_health", "arguments": {"bundle": bundle}},
    })
    assert_true(call["result"]["isError"] is False, "分析 MCP tools/call 不应报错")
    payload = json.loads(call["result"]["content"][0]["text"])
    assert_true(payload["score"] == 75.8, "分析 MCP 健康分应为 75.8，实际 %s" % payload.get("score"))


# ---------------------------------------------------------------------------
# 4. 上传包 / 校验清单
# ---------------------------------------------------------------------------
def check_archives() -> None:
    index = read_json(STANDALONE / "index.json")
    for item in index["skills"]:
        path = ROOT / item["zip"]
        assert_true(path.is_file(), "缺少技能 zip：%s" % path)
        with zipfile.ZipFile(str(path)) as zf:
            assert_true("SKILL.md" in zf.namelist(), "%s：zip 内缺 SKILL.md" % path.name)
            assert_true("mock/samples.json" in zf.namelist(), "%s：zip 内缺模拟样例" % path.name)
    for item in index["mcpServers"]:
        path = ROOT / item["zip"]
        assert_true(path.is_file(), "缺少 MCP zip：%s" % path)
        with zipfile.ZipFile(str(path)) as zf:
            assert_true("README.md" in zf.namelist(), "%s：zip 内缺 README" % path.name)


def check_checksums() -> None:
    path = DIST / "checksums.txt"
    assert_true(path.is_file(), "缺少 checksums.txt")
    lines = [line.split() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert_true(len(lines) == 14, "校验项应为 12 技能 + 2 MCP = 14，实际 %d" % len(lines))
    for digest, name in lines:
        target = DIST / name
        assert_true(target.is_file(), "checksums 指向的文件不存在：%s" % name)
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        assert_true(actual == digest, "%s SHA256 不一致" % name)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main() -> int:
    check("布局与目录（12 技能 / 2 MCP）", check_layout)
    check("SKILL.md frontmatter（slug/version/displayName）", check_frontmatter)
    check("模拟数据（26 接口 / 分析 75.8 / 工具名合法）", check_mock_samples)
    check("PMS spec 快照（26 工具，与专家包一致）", check_pms_spec_snapshot)
    check("PMS CLI doctor（独立目录、无环境变量依赖）", check_pms_doctor)
    check("PMS mock 客户端（get_asset_by_id → 1号主变）", check_pms_mock_client)
    check("PMS 本地 token 网关（正确 token 200 / 错误 token 401）", check_pms_gateway)
    check("PMS MCP 协议（initialize / tools/list=26 / tools/call）", check_pms_mcp)
    check("分析 CLI demo（健康分 75.8）", check_analysis_cli)
    check("分析 MCP 协议（initialize / tools/list=7 / health=75.8）", check_analysis_mcp)
    check("上传包 zip（12 技能 + 2 MCP）", check_archives)
    check("checksums.txt（14 项 SHA256）", check_checksums)

    width = max(len(name) for name, _, _ in RESULTS)
    print("== expert-pack-3 · 独立拆分包离线验证 ==")
    for name, ok, detail in RESULTS:
        print("[%s] %-*s %s" % ("PASS" if ok else "FAIL", width, name, detail))
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print("\n结果：%d / %d 项通过" % (passed, len(RESULTS)))
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
