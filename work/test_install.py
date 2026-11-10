#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Lead 独立「安装后」验收：把 dist 的 8 个技能包解压成真实安装布局，
在清空所有 PMS_* 环境变量后验证：doctor、mock 过滤、MCP 握手。"""
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "expert-pack" / "dist"
SPEC = ROOT / "expert-pack" / "spec" / "interfaces.json"
TMP = ROOT / "work" / "install-test"
PY = sys.executable

fails = []


def ok(cond, msg):
    if not cond:
        fails.append(msg)
    print(("PASS " if cond else "FAIL ") + msg)


def clean_env():
    env = {k: v for k, v in os.environ.items() if not k.startswith("PMS_")}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def main():
    if TMP.exists():
        shutil.rmtree(TMP)
    (TMP / "skills").mkdir(parents=True)
    zips = sorted((DIST / "skills").glob("*.zip"))
    ok(len(zips) == 8, f"dist/skills 有 {len(zips)} 个技能包")
    for z in zips:
        slug = z.stem
        target = TMP / "skills" / slug
        with zipfile.ZipFile(z) as zf:
            zf.extractall(target)
        ok((target / "SKILL.md").is_file(), f"{slug} 解压后根目录有 SKILL.md")
        names = [n for n in zipfile.ZipFile(z).namelist()]
        ok(not any("__pycache__" in n or n.endswith(".pyc") for n in names), f"{slug} 包内无缓存文件")

    base = TMP / "skills" / "pms-gateway-mcp"
    snapshot = base / "references" / "interfaces.json"
    ok(snapshot.is_file(), "底座包含 references/interfaces.json 快照")
    if snapshot.is_file():
        ok(snapshot.read_bytes() == SPEC.read_bytes(), "快照与 spec 字节一致")

    env = clean_env()
    ok("PMS_SPEC_PATH" not in env, "PMS_SPEC_PATH 已清空")

    cli = base / "scripts" / "pms_cli.py"
    doctor = subprocess.run([PY, str(cli), "doctor"], capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(TMP), timeout=120)
    ok(doctor.returncode == 0, f"解压后 doctor 退出码 {doctor.returncode}")
    try:
        data = json.loads(doctor.stdout)
    except Exception as e:  # noqa
        fails.append(f"doctor 输出非 JSON: {e!r}; stderr={doctor.stderr[:300]}")
        data = {}
    ok(data.get("ok") is True, "doctor ok=true")
    ok(data.get("spec", {}).get("toolCount") == 26, "doctor toolCount=26")
    spec_path = str(data.get("spec", {}).get("specPath", ""))
    ok(spec_path.endswith(os.path.join("references", "interfaces.json")), f"specPath 指向内置快照: {spec_path}")
    ok(data.get("problems") == [], "doctor problems 为空")
    mock_probe = data.get("mockProbe", {})
    ok(mock_probe.get("ok") == 26 and mock_probe.get("failed") == [], f"mockProbe 26/26: {mock_probe}")

    # mock 过滤：inquire_defect stationId=STA-220-01 + defectLevel=严重
    call = subprocess.run(
        [PY, str(cli), "call", "inquire_defect", "--params", json.dumps({"stationId": "STA-220-01", "defectLevel": "严重"}, ensure_ascii=False)],
        capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(TMP), timeout=120,
    )
    ok(call.returncode == 0, f"inquire_defect 调用退出码 {call.returncode}")
    payload = json.loads(call.stdout) if call.returncode == 0 else {}
    data_obj = payload.get("data", {})
    ok(isinstance(data_obj.get("list"), list) and len(data_obj.get("list")) == 1, f"mock 过滤命中 1 条缺陷: {data_obj.get('total')}")

    # MCP 握手：stdio 管道 initialize -> tools/list -> tools/call
    mcp = base / "scripts" / "mcp_server.py"
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "lead-install-test", "version": "1.0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_manufs".replace("get_manufs", "get_manufacturer_infos"), "arguments": {}}},
    ]
    stdin = "".join(json.dumps(m, ensure_ascii=False) + "\n" for m in msgs)
    proc = subprocess.run([PY, str(mcp)], input=stdin, capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(TMP), timeout=120)
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    ok(len(lines) == 3, f"stdout 仅 3 行协议响应（通知无响应），实际 {len(lines)}")
    responses = {}
    for ln in lines:
        try:
            obj = json.loads(ln)
        except ValueError:
            fails.append(f"stdout 非 JSON 协议行: {ln[:120]}")
            continue
        responses[obj.get("id")] = obj
    init = responses.get(1, {}).get("result", {})
    ok(init.get("protocolVersion") == "2024-11-05", "initialize 协议版本正确")
    tools = responses.get(2, {}).get("result", {}).get("tools", [])
    ok(len(tools) == 26, f"tools/list 返回 26 个，实际 {len(tools)}")
    call_res = responses.get(3, {}).get("result", {})
    ok(call_res.get("isError") is False, "tools/call isError=false")
    ok(bool(call_res.get("content")), "tools/call 返回 content")
    if proc.stderr:
        ok("Traceback" not in proc.stderr, "stderr 无异常栈（日志可以有）")

    print("\n" + ("安装后验收：全部通过" if not fails else f"安装后验收失败 {len(fails)} 项"))
    for f in fails:
        print(" -", f)
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
