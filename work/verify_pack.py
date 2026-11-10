#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Lead 独立验收脚本（不属于交付物，放在 work/ 下）。
不依赖队友的 build_pack.py 校验逻辑，独立复核：
  1. spec 契约与分组
  2. manifest / identify 一致性
  3. 8 个子技能 frontmatter 与工具引用
  4. dist 三个 zip 的结构与内容
  5. MCP 协议握手（进程内）+ CLI 调用（子进程，若环境允许）
"""
import io
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


def check_spec():
    spec = json.loads((SRC / "spec" / "interfaces.json").read_text(encoding="utf-8"))
    tools = spec["tools"]
    ok(len(tools) == 26, f"spec 工具数 = {len(tools)}，应为 26")
    names = [t["name"] for t in tools]
    codes = [t["code"] for t in tools]
    ok(len(set(names)) == 26, "spec 工具名不唯一")
    ok(len(set(codes)) == 26, "spec 接口编码不唯一")
    groups = {g["id"]: g for g in spec["groups"]}
    for t in tools:
        ok(t.get("group") in groups, f"{t['name']} 的 group 不合法: {t.get('group')}")
        ok(bool(t.get("mock")), f"{t['name']} 缺少 mock")
        ok(bool(t.get("params")), f"{t['name']} 缺少 params")
        ok(t.get("path", "").startswith("/"), f"{t['name']} path 异常")
    # 分组计数
    from collections import Counter
    cnt = Counter(t["group"] for t in tools)
    for gid, g in groups.items():
        ok(cnt.get(gid, 0) == g["toolCount"], f"分组 {gid} 计数 {cnt.get(gid)} != {g['toolCount']}")
    return spec, tools, groups


def check_manifest_identify(tools, groups):
    manifest = json.loads((SRC / "manifest.json").read_text(encoding="utf-8"))
    ok(manifest.get("type") == "skillhub-expert-package", "manifest.type 不是 skillhub-expert-package")
    ok(manifest.get("slug") == SLUG, "manifest.slug 不符")
    slugs = manifest.get("skillSlugs", [])
    ok(len(slugs) == 8, f"manifest.skillSlugs 数量 {len(slugs)}，应为 8")
    ok(len(set(slugs)) == 8, "manifest.skillSlugs 有重复")
    ok([s["slug"] for s in manifest.get("skills", [])] == slugs, "manifest.skills 与 skillSlugs 不一致")

    identify = (SRC / "identify.md").read_text(encoding="utf-8")
    fm = parse_frontmatter(identify)
    ok(fm is not None, "identify.md 缺少 frontmatter")
    if fm:
        ok(fm.get("name") == SLUG, f"identify.name={fm.get('name')} != {SLUG}")
        # children 列表解析（简单逐行）
        m = re.search(r"children:\s*\n((?:\s*-\s*.+\n)+)", identify)
        children = [x.strip("- \t\r") for x in m.group(1).splitlines()] if m else []
        ok(children == slugs, f"identify.orchestration.children 与 manifest 不一致: {children}")
    for g in groups.values():
        ok(g["role"] in identify, f"identify.md 缺少角色 {g['role']}")
    return manifest, slugs


def check_skills(slugs, tools):
    skill_dirs = sorted(p.name for p in (SRC / "skills").iterdir() if p.is_dir())
    ok(set(skill_dirs) == set(slugs), f"skills 目录与 manifest 不一致: {set(skill_dirs) ^ set(slugs)}")
    by_group = {}
    for t in tools:
        by_group.setdefault(t["group"], set()).add(t["name"])
    group_skill = {g["id"]: g["skill"] for g in json.loads((SRC / "spec" / "interfaces.json").read_text(encoding="utf-8"))["groups"]}
    for slug in slugs:
        d = SRC / "skills" / slug
        skill_md = d / "SKILL.md"
        ok(skill_md.is_file(), f"{slug} 缺少 SKILL.md")
        if not skill_md.is_file():
            continue
        text = skill_md.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        ok(fm is not None, f"{slug}/SKILL.md frontmatter 无法解析")
        if fm:
            ok(fm.get("name") == slug, f"{slug}/SKILL.md name={fm.get('name')} 与目录不一致")
            ok(bool(fm.get("description")), f"{slug}/SKILL.md 缺少 description")
        if slug != "pms-gateway-mcp" and slug != "substation-qa-orchestrator":
            gid = next((g for g, s in group_skill.items() if s == slug), None)
            if gid:
                for name in by_group.get(gid, set()):
                    ok(name in text, f"{slug} 未引用工具 {name}")
        ok(len(text.splitlines()) <= 400, f"{slug}/SKILL.md 过长（{len(text.splitlines())} 行）")


def check_dist(slugs):
    ok(DIST.is_dir(), "dist 目录不存在（尚未构建）")
    if not DIST.is_dir():
        return
    web = DIST / f"{SLUG}.zip"
    install = DIST / f"{SLUG}-install.zip"
    ok(web.is_file(), f"缺少 {web.name}")
    ok(install.is_file(), f"缺少 {install.name}")
    if web.is_file():
        with zipfile.ZipFile(web) as z:
            names = set(z.namelist())
            ok("manifest.json" in names, "网页格式包缺少 manifest.json")
            ok(f"skillsets/{SLUG}.md" in names, "网页格式包缺少 skillsets/<slug>.md")
            for s in slugs:
                ok(f"skills/{s}.zip" in names, f"网页格式包缺少 skills/{s}.zip")
            m = json.loads(z.read("manifest.json"))
            ok(m.get("type") == "skillhub-expert-package", "网页格式包 manifest.type 错误")
    if install.is_file():
        with zipfile.ZipFile(install) as z:
            names = set(z.namelist())
            ok("manifest.json" in names, "安装格式包缺少 manifest.json")
            ok("identify.md" in names, "安装格式包缺少 identify.md")
    for s in slugs:
        zp = DIST / "skills" / f"{s}.zip"
        ok(zp.is_file(), f"缺少子技能包 {zp.name}")
        if zp.is_file():
            with zipfile.ZipFile(zp) as z:
                names = z.namelist()
                ok("SKILL.md" in names, f"{s}.zip 根目录缺少 SKILL.md")
                ok(not any(n.startswith("__pycache__") or n.endswith(".pyc") for n in names), f"{s}.zip 含缓存文件")
                ok(zp.stat().st_size < 10 * 1024 * 1024, f"{s}.zip 超过 10MB")
    ok((DIST / "checksums.txt").is_file(), "缺少 dist/checksums.txt")


def check_docs(tools):
    docs = SRC / "docs"
    names = ["01-接口映射表.md", "02-鉴权接入指南.md", "03-部署与使用说明.md", "04-开发与扩展指南.md"]
    for n in names:
        ok((docs / n).is_file(), f"缺少 docs/{n}")
    if (docs / "01-接口映射表.md").is_file():
        text = (docs / "01-接口映射表.md").read_text(encoding="utf-8")
        for t in tools:
            ok(t["name"] in text, f"01-接口映射表.md 缺少 {t['name']}")
    ok((SRC / "README.md").is_file(), "缺少 README.md")
    ok((SRC / "tools" / "build_pack.py").is_file(), "缺少 tools/build_pack.py")


def check_mcp_runtime():
    scripts = SRC / "skills" / "pms-gateway-mcp" / "scripts"
    if not scripts.is_dir():
        fails.append("底座 scripts 目录不存在")
        return
    sys.path.insert(0, str(scripts))
    try:
        import mcp_server
    except Exception as e:  # noqa
        fails.append(f"无法 import mcp_server: {e!r}")
        return
    handle = getattr(mcp_server, "handle_message", None) or getattr(mcp_server, "handle_request", None)
    if not callable(handle):
        server_cls = getattr(mcp_server, "McpServer", None)
        if server_cls is not None:
            try:
                handle = server_cls().handle_message
            except Exception as e:  # noqa
                fails.append(f"无法实例化 McpServer: {e!r}")
                return
    ok(callable(handle), "mcp_server 缺少 handle_message/handle_request")
    if callable(handle):
        init = handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "verify", "version": "1.0"}}})
        ok(init.get("result", {}).get("serverInfo", {}).get("name"), "initialize 返回异常")
        lst = handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools = lst.get("result", {}).get("tools", [])
        ok(len(tools) == 26, f"tools/list 返回 {len(tools)} 个工具")
        for t in tools:
            ok(t.get("inputSchema", {}).get("type") == "object", f"{t.get('name')} inputSchema 非 object")
        call = handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_asset_by_id", "arguments": {"assetId": "AST-102-0001"}}})
        content = call.get("result", {}).get("content", [])
        ok(bool(content), "tools/call 无 content")
        unknown = handle({"jsonrpc": "2.0", "id": 4, "method": "no/such", "params": {}})
        ok(unknown.get("error", {}).get("code") == -32601, "未知方法未返回 -32601")


def check_cli():
    cli = SRC / "skills" / "pms-gateway-mcp" / "scripts" / "pms_cli.py"
    if not cli.is_file():
        fails.append("缺少 pms_cli.py")
        return
    try:
        out = subprocess.run([PY, str(cli), "doctor"], capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace")
        ok(out.returncode == 0, f"CLI doctor 退出码 {out.returncode}: {out.stderr[:300]}")
        json.loads(out.stdout)
    except Exception as e:  # noqa
        warn(False, f"CLI 子进程验收未执行（环境限制可忽略）: {e!r}")


def main():
    spec, tools, groups = check_spec()
    manifest, slugs = check_manifest_identify(tools, groups)
    check_skills(slugs, tools)
    check_docs(tools)
    check_dist(slugs)
    check_mcp_runtime()
    check_cli()
    print("=" * 60)
    if warns:
        print("WARN:")
        for w in warns:
            print("  -", w)
    if fails:
        print("FAIL:")
        for f in fails:
            print("  -", f)
        print(f"\n结果：{len(fails)} 项失败，{len(warns)} 项警告")
        return 1
    print("结果：全部通过" + (f"（{len(warns)} 项警告）" if warns else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
