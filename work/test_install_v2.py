#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Lead 独立「安装后」验收 v1.1.0：把 dist 的 12 个技能包解压成真实安装布局，
清空 PMS_* 环境变量后验证：数据 MCP doctor、分析 CLI demo、分析 MCP 握手与真实调用。"""
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
TMP = ROOT / "work" / "install-test-v2"
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
    ok(len(zips) == 12, f"dist/skills 有 {len(zips)} 个技能包（应为 12）")
    for z in zips:
        slug = z.stem
        target = TMP / "skills" / slug
        with zipfile.ZipFile(z) as zf:
            zf.extractall(target)
        ok((target / "SKILL.md").is_file(), f"{slug} 解压后根目录有 SKILL.md")
        names = zipfile.ZipFile(z).namelist()
        ok(not any("__pycache__" in n or n.endswith(".pyc") for n in names), f"{slug} 包内无缓存")

    base = TMP / "skills" / "pms-gateway-mcp"
    snap = base / "references" / "interfaces.json"
    ok(snap.is_file(), "数据底座包含 references/interfaces.json 快照")
    if snap.is_file():
        ok(snap.read_bytes() == SPEC.read_bytes(), "数据底座快照与 spec 字节一致")

    ana = TMP / "skills" / "substation-analysis-mcp"
    for rel in ["config/scorecard.json", "config/diagnosis_rules.json",
                "templates/device_profile.md", "templates/station_monthly.md",
                "templates/fault_review.md", "assets/demo_bundle.json"]:
        ok((ana / rel).is_file(), f"分析底座安装后含 {rel}")

    env = clean_env()
    ok("PMS_SPEC_PATH" not in env, "PMS_SPEC_PATH 已清空")

    # 1) 数据 MCP doctor
    cli = base / "scripts" / "pms_cli.py"
    doctor = subprocess.run([PY, str(cli), "doctor"], capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(TMP), timeout=120)
    ok(doctor.returncode == 0, f"数据 doctor 退出码 {doctor.returncode}: {doctor.stderr[:200]}")
    if doctor.returncode == 0:
        d = json.loads(doctor.stdout)
        ok(d.get("ok") is True, "数据 doctor ok=true")
        ok(d.get("spec", {}).get("toolCount") == 26, "数据 doctor toolCount=26")
        ok(d.get("problems") == [], "数据 doctor problems 为空")
        ok(d.get("spec", {}).get("specPath", "").endswith(os.path.join("references", "interfaces.json")), "数据 specPath 指向内置快照")

    # 2) 分析 CLI demo（安装后、无仓库目录依赖）
    ana_cli = ana / "scripts" / "analysis_cli.py"
    demo = subprocess.run([PY, str(ana_cli), "demo"], capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(TMP), timeout=120)
    ok(demo.returncode == 0, f"分析 CLI demo 退出码 {demo.returncode}: {demo.stderr[:300]}")
    demo_json = {}
    if demo.returncode == 0:
        try:
            demo_json = json.loads(demo.stdout)
            ok(bool(demo_json), "分析 CLI demo 输出非空 JSON")
        except Exception as e:  # noqa
            fails.append(f"分析 CLI demo 输出非 JSON: {e!r}")

    # 3) 分析 MCP stdio 握手 + 实际调用
    ana_mcp = ana / "scripts" / "analysis_mcp.py"
    bundle = json.loads((ana / "assets" / "demo_bundle.json").read_text(encoding="utf-8"))
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "lead-install-v2", "version": "1.0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "assess_device_health", "arguments": {"bundle": bundle}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "diagnose_equipment", "arguments": {"bundle": bundle, "max_hypotheses": 3}}},
    ]
    stdin = "".join(json.dumps(m, ensure_ascii=False) + "\n" for m in msgs)
    proc = subprocess.run([PY, str(ana_mcp)], input=stdin, capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(TMP), timeout=120)
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    ok(len(lines) == 4, f"分析 MCP stdout 应仅 4 行协议响应（通知无响应），实际 {len(lines)}")
    responses = {}
    for ln in lines:
        try:
            obj = json.loads(ln)
        except ValueError:
            fails.append(f"分析 MCP stdout 非 JSON: {ln[:120]}")
            continue
        responses[obj.get("id")] = obj
    ok(responses.get(1, {}).get("result", {}).get("protocolVersion") == "2024-11-05", "分析 MCP initialize 协议版本正确")
    tools = responses.get(2, {}).get("result", {}).get("tools", [])
    ok(len(tools) == 7, f"分析 tools/list 返回 7 个，实际 {len(tools)}")
    call = responses.get(3, {}).get("result", {})
    ok(call.get("isError") is False, "assess_device_health isError=false")
    if call.get("content"):
        try:
            h = json.loads(call["content"][0]["text"])
            ok(isinstance(h.get("score"), (int, float)) and 0 <= h["score"] <= 100, f"健康分越界: {h.get('score')}")
            ok(h.get("grade") in list("ABCDE"), f"健康等级异常: {h.get('grade')}")
            ok(isinstance(h.get("deductions"), list), "健康结果缺 deductions")
        except Exception as e:  # noqa
            fails.append(f"assess_device_health 返回解析失败: {e!r}")
    diag = responses.get(4, {}).get("result", {})
    ok(diag.get("isError") is False, "diagnose_equipment isError=false")
    if diag.get("content"):
        try:
            dd = json.loads(diag["content"][0]["text"])
            ok(isinstance(dd.get("hypotheses"), list), "诊断结果缺 hypotheses")
        except Exception as e:  # noqa
            fails.append(f"diagnose_equipment 返回解析失败: {e!r}")
    ok("Traceback" not in (proc.stderr or ""), "分析 MCP stderr 无异常栈")

    print("\n" + ("v2 安装后验收：全部通过" if not fails else f"v2 安装后验收失败 {len(fails)} 项"))
    for f in fails:
        print(" -", f)
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
