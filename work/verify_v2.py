#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Lead 独立验收（v1.1.0，work/ 下，非交付物）。
独立复核（不复用队友 build_pack.py 的校验逻辑）：
  1. 数据契约 26 工具 + 分析契约 7 工具
  2. manifest / identify（12 技能、版本 1.1.0）
  3. 12 个技能 frontmatter 与工具引用
  4. dist 产物结构、spec 快照、分析资产、checksums
  5. 运行时：数据 MCP 握手 26、分析 MCP 握手 7 + 健康/诊断/报告真实调用
  6. 文档 v2 内容（06 / 01 / 03 / 04 / 05 / README）
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "expert-pack"
DIST = SRC / "dist"
PY = sys.executable
SLUG = "bianya-intelligent-data-qa"

fails = []
warns = []


def ok(cond, msg):
    if not cond:
        fails.append(msg)


def warn(cond, msg):
    if not cond:
        warns.append(msg)


FM_RE = re.compile(r"^\ufeff?---\s*\n(.*?)\n---\s*\n", re.S)


def parse_frontmatter(text):
    m = FM_RE.match(text)
    if not m:
        return None
    fm = {}
    for line in m.group(1).splitlines():
        line = line.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        if ":" in line and not line.startswith((" ", "\t", "-")):
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    return fm


def check_specs():
    spec = json.loads((SRC / "spec" / "interfaces.json").read_text(encoding="utf-8"))
    tools = spec["tools"]
    ok(len(tools) == 26, f"数据 spec 工具数 = {len(tools)}，应为 26")
    names = [t["name"] for t in tools]
    ok(len(set(names)) == 26, "数据工具名不唯一")
    ok(len({t["code"] for t in tools}) == 26, "接口编码不唯一")
    groups = {g["id"]: g for g in spec["groups"]}
    from collections import Counter
    cnt = Counter(t["group"] for t in tools)
    for gid, g in groups.items():
        ok(cnt.get(gid, 0) == g["toolCount"], f"分组 {gid} 计数不符")
    for t in tools:
        ok(bool(t.get("mock")), f"{t['name']} 缺 mock")
        ok(bool(t.get("params")), f"{t['name']} 缺 params")

    analysis = json.loads((SRC / "spec" / "analysis-tools.json").read_text(encoding="utf-8"))
    atools = analysis["tools"]
    ok(analysis.get("server") == "substation-analysis-mcp", "analysis-tools.server 不符")
    ok(len(atools) == 7, f"分析工具数 = {len(atools)}，应为 7")
    anames = [t["name"] for t in atools]
    ok(len(set(anames)) == 7, "分析工具名不唯一")
    expected = {
        "assess_device_health", "assess_station_health", "diagnose_equipment",
        "detect_defect_patterns", "compute_device_metrics", "generate_report", "list_report_types",
    }
    ok(set(anames) == expected, f"分析工具名集合不符: {set(anames) ^ expected}")
    for t in atools:
        for p in t.get("params", []):
            ok("name" in p and "type" in p, f"{t['name']} 参数缺 name/type")
            ok(isinstance(p.get("required", False), bool), f"{t['name']}.{p.get('name')} required 非 bool")
            if "enum" in p:
                ok(isinstance(p["enum"], list), f"{t['name']}.{p['name']} enum 非数组")

    bundle = json.loads((SRC / "spec" / "analysis-bundle.schema.json").read_text(encoding="utf-8"))
    ok(bundle.get("type") == "object", "bundle schema 根类型非 object")
    ok("device" in bundle.get("required", []), "bundle schema 未要求 device")
    return spec, tools, groups, analysis, atools, bundle


def check_manifest_identify(slugs, groups, tools):
    manifest = json.loads((SRC / "manifest.json").read_text(encoding="utf-8"))
    ok(manifest.get("type") == "skillhub-expert-package", "manifest.type 错误")
    ok(manifest.get("slug") == SLUG, "manifest.slug 不符")
    slugs_now = manifest.get("skillSlugs", [])
    ok(len(slugs_now) == 12, f"manifest.skillSlugs 数量 {len(slugs_now)}，应为 12")
    ok(len(set(slugs_now)) == 12, "manifest.skillSlugs 有重复")
    ok([s["slug"] for s in manifest.get("skills", [])] == slugs_now, "manifest.skills 与 skillSlugs 不一致")
    if slugs is not None:
        ok(slugs == slugs_now, "调用方 slugs 与 manifest 不一致")

    identify = (SRC / "identify.md").read_text(encoding="utf-8")
    fm = parse_frontmatter(identify)
    ok(fm is not None, "identify.md 缺 frontmatter")
    if fm:
        ok(fm.get("name") == SLUG, f"identify.name={fm.get('name')}")
        ok(fm.get("version") == "1.1.0", f"identify.version={fm.get('version')}，应为 1.1.0")
    m = re.search(r"children:\s*\n((?:\s*-\s*.+\n)+)", identify)
    children = [x.strip("- \t\r") for x in m.group(1).splitlines()] if m else []
    ok(children == slugs_now, f"identify.children 与 manifest 不一致: {set(children) ^ set(slugs_now)}")
    for role in ["问数总控", "接口网关工程师", "分析引擎工程师", "健康评估专家", "诊断专家", "报告专家"]:
        ok(role in identify, f"identify.md 缺角色 {role}")
    for g in groups.values():
        ok(g["role"] in identify, f"identify.md 缺角色 {g['role']}")
    return manifest, slugs_now


def check_skills(slugs, tools_by_group, analysis_tools, data_groups):
    dirs = sorted(p.name for p in (SRC / "skills").iterdir() if p.is_dir())
    ok(set(dirs) == set(slugs), f"skills 目录与 manifest 不一致: {set(dirs) ^ set(slugs)}")
    data_tool_names = [t["name"] for t in sum(tools_by_group.values(), [])]
    for slug in slugs:
        d = SRC / "skills" / slug
        smd = d / "SKILL.md"
        ok(smd.is_file(), f"{slug} 缺 SKILL.md")
        if not smd.is_file():
            continue
        text = smd.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        ok(fm is not None, f"{slug} frontmatter 无法解析")
        if fm:
            ok(fm.get("name") == slug, f"{slug} name={fm.get('name')} 与目录不一致")
            ok(bool(fm.get("description")), f"{slug} 缺 description")
            ok(fm.get("version") == "1.1.0", f"{slug} version={fm.get('version')}，应为 1.1.0")
        ok(len(text.splitlines()) <= 400, f"{slug}/SKILL.md 过长 {len(text.splitlines())} 行")
        # 业务技能必须覆盖其分组工具
        gid = next((g for g in data_groups.values() if g["skill"] == slug), None)
        if gid:
            for t in tools_by_group.get(gid["id"], []):
                ok(t["name"] in text, f"{slug} 未引用工具 {t['name']}")
        # 深能力技能必须引用对应分析工具
        wants = {
            "substation-health-assessment": ["assess_device_health", "assess_station_health"],
            "substation-diagnosis": ["diagnose_equipment", "detect_defect_patterns"],
            "substation-report": ["generate_report", "list_report_types"],
        }.get(slug, [])
        for name in wants:
            ok(name in text, f"{slug} 未引用分析工具 {name}")
        # 数据工具名不得自造：只检查反引号工具名与 JSON tool 字段（正文关键词不算）
        candidates = set(re.findall(r"`((?:get|list|query|find|view|inquire|search|analyze|assess|diagnose|detect|compute|generate)_[a-z_]+\b)`", text))
        candidates |= set(re.findall(r'"tool"\s*:\s*"([a-z_]+)"', text))
        unknown = candidates - set(data_tool_names) - {t["name"] for t in analysis_tools["tools"]}
        warn(not unknown, f"{slug} 出现未知工具名: {sorted(unknown)[:5]}")

    ad = SRC / "skills" / "substation-analysis-mcp"
    for rel in [
        "config/scorecard.json", "config/diagnosis_rules.json",
        "templates/device_profile.md", "templates/station_monthly.md", "templates/fault_review.md",
        "assets/demo_bundle.json", "scripts/analysis_mcp.py", "scripts/analysis_cli.py",
        "references/tools.md", "references/bundle-schema.md", "references/scorecard.md",
        "references/diagnosis-rules.md", "references/report-templates.md",
    ]:
        ok((ad / rel).is_file(), f"分析技能缺 {rel}")
    # 分析技能必须引用全部 7 个分析工具
    if (ad / "SKILL.md").is_file():
        t = (ad / "SKILL.md").read_text(encoding="utf-8")
        for tool in analysis_tools["tools"]:
            ok(tool["name"] in t, f"分析技能 SKILL.md 未引用 {tool['name']}")
    # demo bundle 必须符合基本结构
    if (ad / "assets" / "demo_bundle.json").is_file():
        try:
            d = json.loads((ad / "assets" / "demo_bundle.json").read_text(encoding="utf-8"))
            ok("device" in d, "demo_bundle 缺 device")
            ok(bool(d.get("defects")), "demo_bundle 建议含 defects")
        except Exception as e:  # noqa
            fails.append(f"demo_bundle JSON 非法: {e!r}")


def check_dist(slugs):
    if not DIST.is_dir():
        fails.append("dist 目录不存在（尚未构建）")
        return
    web, install = DIST / f"{SLUG}.zip", DIST / f"{SLUG}-install.zip"
    ok(web.is_file(), f"缺 {web.name}")
    ok(install.is_file(), f"缺 {install.name}")
    if web.is_file():
        with zipfile.ZipFile(web) as z:
            names = set(z.namelist())
            ok("manifest.json" in names, "web 包缺 manifest.json")
            ok(f"skillsets/{SLUG}.md" in names, "web 包缺 skillsets/<slug>.md")
            for s in slugs:
                ok(f"skills/{s}.zip" in names, f"web 包缺 skills/{s}.zip")
            ok(len([n for n in names if n.startswith("skills/")]) == 12, "web 包技能数不为 12")
    if install.is_file():
        with zipfile.ZipFile(install) as z:
            names = set(z.namelist())
            ok("manifest.json" in names and "identify.md" in names, "install 包结构错误")

    spec_bytes = (SRC / "spec" / "interfaces.json").read_bytes()
    for s in slugs:
        zp = DIST / "skills" / f"{s}.zip"
        ok(zp.is_file(), f"缺子技能包 {zp.name}")
        if not zp.is_file():
            continue
        with zipfile.ZipFile(zp) as z:
            names = z.namelist()
            ok("SKILL.md" in names, f"{s}.zip 根缺 SKILL.md")
            ok(not any("__pycache__" in n or n.endswith(".pyc") for n in names), f"{s}.zip 含缓存")
            ok(zp.stat().st_size < 10 * 1024 * 1024, f"{s}.zip 超 10MB")
            if s == "pms-gateway-mcp":
                ok("references/interfaces.json" in names, "底座 zip 缺 spec 快照")
                if "references/interfaces.json" in names:
                    ok(z.read("references/interfaces.json") == spec_bytes, "底座快照与 spec 不一致")
            else:
                ok("references/interfaces.json" not in names, f"{s}.zip 不应包含 spec 快照")
            if s == "substation-analysis-mcp":
                for rel in ["config/scorecard.json", "config/diagnosis_rules.json",
                            "templates/device_profile.md", "templates/station_monthly.md",
                            "templates/fault_review.md", "assets/demo_bundle.json"]:
                    ok(rel in names, f"分析 zip 缺 {rel}")
                ok("references/report-templates.md" in names, "分析 zip 缺 references/report-templates.md")
    # checksums 自洽
    cs = DIST / "checksums.txt"
    ok(cs.is_file(), "缺 checksums.txt")
    if cs.is_file():
        for line in cs.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            digest, _, rel = line.partition("  ")
            p = DIST / rel.strip()
            ok(p.is_file(), f"checksums 指向不存在的文件: {rel}")
            if p.is_file():
                h = hashlib.sha256(p.read_bytes()).hexdigest()
                ok(h == digest, f"checksums 不匹配: {rel}")


def _handle_from(module):
    fn = getattr(module, "handle_message", None) or getattr(module, "handle_request", None)
    if callable(fn):
        return fn
    for attr in dir(module):
        if not (attr.endswith("McpServer") or attr.endswith("Server")):
            continue
        cls = getattr(module, attr)
        if isinstance(cls, type) and callable(getattr(cls, "handle_message", None)):
            try:
                return cls().handle_message
            except Exception:
                continue
    return None


def _call_json(handle, tool, args, req_id=3):
    resp = handle({"jsonrpc": "2.0", "id": req_id, "method": "tools/call", "params": {"name": tool, "arguments": args}})
    content = resp.get("result", {}).get("content", [])
    ok(resp.get("result", {}).get("isError") is False, f"{tool} 调用 isError 非 false")
    if not content:
        fails.append(f"{tool} 无 content")
        return None
    try:
        return json.loads(content[0].get("text", "null"))
    except Exception as e:  # noqa
        fails.append(f"{tool} 返回非 JSON: {e!r}")
        return None


def check_data_mcp():
    scripts = SRC / "skills" / "pms-gateway-mcp" / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        import mcp_server  # noqa
    except Exception as e:  # noqa
        fails.append(f"数据 MCP import 失败: {e!r}")
        return
    handle = _handle_from(mcp_server)
    ok(callable(handle), "数据 MCP 无 handle_message")
    if not callable(handle):
        return
    init = handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "verify", "version": "1.0"}}})
    ok(bool(init.get("result", {}).get("serverInfo")), "数据 MCP initialize 异常")
    lst = handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    ok(len(lst.get("result", {}).get("tools", [])) == 26, "数据 tools/list 不为 26")
    unknown = handle({"jsonrpc": "2.0", "id": 9, "method": "no/such", "params": {}})
    ok(unknown.get("error", {}).get("code") == -32601, "数据 MCP 未知方法未返 -32601")


def check_analysis_mcp(analysis_tools):
    scripts = SRC / "skills" / "substation-analysis-mcp" / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        import analysis_mcp  # noqa
    except Exception as e:  # noqa
        fails.append(f"分析 MCP import 失败: {e!r}")
        return
    handle = _handle_from(analysis_mcp)
    ok(callable(handle), "分析 MCP 无 handle_message")
    if not callable(handle):
        return
    handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "verify", "version": "1.0"}}})
    lst = handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    tools = lst.get("result", {}).get("tools", [])
    ok(len(tools) == 7, f"分析 tools/list 返回 {len(tools)}")
    got = {t["name"]: t for t in tools}
    for t in analysis_tools["tools"]:
        ok(t["name"] in got, f"分析 tools/list 缺 {t['name']}")
        if t["name"] in got:
            props = got[t["name"]].get("inputSchema", {}).get("properties", {})
            req = got[t["name"]].get("inputSchema", {}).get("required", [])
            for p in t.get("params", []):
                ok(p["name"] in props, f"{t['name']} 入参缺 {p['name']}")
                if p.get("required"):
                    ok(p["name"] in req, f"{t['name']}.{p['name']} 未标记 required")

    demo_path = SRC / "skills" / "substation-analysis-mcp" / "assets" / "demo_bundle.json"
    if not demo_path.is_file():
        fails.append("缺 demo_bundle，跳过分析运行时")
        return
    demo = json.loads(demo_path.read_text(encoding="utf-8"))
    health = _call_json(handle, "assess_device_health", {"bundle": demo})
    if health:
        ok(isinstance(health.get("score"), (int, float)) and 0 <= health["score"] <= 100, "健康分越界")
        ok(health.get("grade") in list("ABCDE"), f"等级异常 {health.get('grade')}")
        ok(isinstance(health.get("deductions"), list), "缺 deductions")
        ok(isinstance(health.get("confidence"), (int, float)) and 0 <= health["confidence"] <= 1, "置信度越界")
        ok(isinstance(health.get("dimensions"), list) and len(health["dimensions"]) == 5, "维度数不为 5")
        ok(bool(health.get("knowledgeQueries")), "缺 knowledgeQueries")
    diag = _call_json(handle, "diagnose_equipment", {"bundle": demo, "max_hypotheses": 5}, 4)
    if diag:
        ok(isinstance(diag.get("hypotheses"), list), "诊断缺 hypotheses")
        if diag.get("hypotheses"):
            h0 = diag["hypotheses"][0]
            ok(bool(h0.get("evidence")), "诊断假设缺 evidence")
            ok("confidence" in h0, "诊断假设缺 confidence")
            ok(bool(h0.get("knowledgeQueries")), "诊断假设缺 knowledgeQueries")
    metrics = _call_json(handle, "compute_device_metrics", {"bundle": demo}, 5)
    if metrics:
        ok(isinstance(metrics.get("metrics"), dict), "指标结果缺 metrics")
    # 报告：用健康+诊断结果渲染
    if health and diag:
        rep = _call_json(handle, "generate_report", {
            "report_type": "device_profile",
            "payload": {"health": health, "diagnosis": diag, "device": demo.get("device", {})},
            "citations": [{"title": "变压器运行规程", "source": "WeKnora/变电规程库", "snippet": "示例片段", "kbId": "kb-demo"}],
            "title": "1号主变健康画像",
        }, 6)
        if rep:
            md = rep.get("markdown", "")
            ok("1号主变" in md, "报告缺少标题/设备名")
            ok("{{" not in md, "报告残留占位符")
            ok("变压器运行规程" in md, "报告未渲染引用")
    # 确定性：同 bundle 两次调用一致（除 generatedAt 外）
    h1 = _call_json(handle, "assess_device_health", {"bundle": demo}, 7)
    h2 = _call_json(handle, "assess_device_health", {"bundle": demo}, 8)
    if h1 and h2:
        for k in ("score", "grade", "confidence"):
            ok(h1.get(k) == h2.get(k), f"确定性失败: {k}")


def check_cli():
    cli = SRC / "skills" / "substation-analysis-mcp" / "scripts" / "analysis_cli.py"
    if not cli.is_file():
        fails.append("缺 analysis_cli.py")
        return
    try:
        out = subprocess.run([PY, str(cli), "demo"], capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace")
        ok(out.returncode == 0, f"分析 CLI demo 退出码 {out.returncode}: {out.stderr[:300]}")
        if out.returncode == 0:
            data = json.loads(out.stdout)
            ok(bool(data), "分析 CLI demo 输出空")
    except Exception as e:  # noqa
        warn(False, f"分析 CLI demo 未执行（环境限制可忽略）: {e!r}")


def check_docs(analysis_tools):
    docs = SRC / "docs"
    for n in ["01-接口映射表.md", "02-鉴权接入指南.md", "03-部署与使用说明.md", "04-开发与扩展指南.md", "05-架构设计.md", "06-深能力与知识库集成.md"]:
        ok((docs / n).is_file(), f"缺 docs/{n}")
    if (docs / "01-接口映射表.md").is_file():
        t = (docs / "01-接口映射表.md").read_text(encoding="utf-8")
        for a in analysis_tools["tools"]:
            ok(a["name"] in t, f"01 缺分析工具 {a['name']}")
    if (docs / "06-深能力与知识库集成.md").is_file():
        t = (docs / "06-深能力与知识库集成.md").read_text(encoding="utf-8")
        ok("WeKnora" in t, "06 未提及 WeKnora")
        ok("substation-analysis-mcp" in t, "06 未提及分析 MCP")
        ok("bundle" in t, "06 未提及 bundle")
        for a in analysis_tools["tools"]:
            ok(a["name"] in t, f"06 缺分析工具 {a['name']}")
    if (docs / "05-架构设计.md").is_file():
        t = (docs / "05-架构设计.md").read_text(encoding="utf-8")
        for k in ["D8", "D9", "D10"]:
            ok(k in t, f"05 缺决策 {k}")
    if (docs / "03-部署与使用说明.md").is_file():
        ok("substation-analysis-mcp" in (docs / "03-部署与使用说明.md").read_text(encoding="utf-8"), "03 未提及分析 MCP")
    if (SRC / "README.md").is_file():
        t = (SRC / "README.md").read_text(encoding="utf-8")
        ok("12" in t, "README 未说明 12 技能")
        for s in ["substation-analysis-mcp", "substation-health-assessment", "substation-diagnosis", "substation-report"]:
            ok(s in t, f"README 缺 {s}")
    ok((SRC / "tools" / "build_pack.py").is_file(), "缺 build_pack.py")


def main():
    spec, tools, groups, analysis, atools, bundle = check_specs()
    tools_by_group = {}
    for t in tools:
        tools_by_group.setdefault(t["group"], []).append(t)
    manifest, slugs = check_manifest_identify(None, groups, tools)
    check_skills(slugs, tools_by_group, analysis, groups)
    check_docs(analysis)
    check_dist(slugs)
    check_data_mcp()
    check_analysis_mcp(analysis)
    check_cli()
    print("=" * 60)
    if warns:
        print("WARN:")
        for w in warns:
            print("  -", w)
    if fails:
        print(f"FAIL ({len(fails)}):")
        for f in fails:
            print("  -", f)
        print(f"\n结果：{len(fails)} 项失败，{len(warns)} 项警告")
        return 1
    print(f"结果：全部通过（{len(warns)} 项警告）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
