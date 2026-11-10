# -*- coding: utf-8 -*-
"""技能内容自检：frontmatter 可解析、name 与目录一致、行数上限、工具名/参数/接口编码与 spec 一致性。"""
import io
import json
import os
import re
import sys

ROOT = r"F:\work\2026年\10月\专家包"
SKILLS = os.path.join(ROOT, "expert-pack", "skills")
SPEC = os.path.join(ROOT, "expert-pack", "spec", "interfaces.json")

GROUP_OF_SLUG = {
    "substation-asset-ledger": "asset-ledger",
    "substation-device-tree": "device-tree",
    "substation-om-health": "om-health",
    "substation-maintenance-test": "maintenance-test",
    "substation-reliability": "reliability",
    "substation-resource-topology": "resource-topology",
    "substation-qa-orchestrator": None,
}

with io.open(SPEC, "r", encoding="utf-8") as f:
    spec = json.load(f)
spec_tools = {t["name"]: t for t in spec["tools"]}
spec_params = {t["name"]: set(p["name"] for p in t["params"]) for t in spec["tools"]}
spec_codes = set(t["code"] for t in spec["tools"])
spec_code_of = {t["name"]: t["code"] for t in spec["tools"]}


def unquote(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        return v[1:-1]
    return v


def parse_frontmatter(text):
    """极简 YAML 解析：key: value / key: >- 折叠块 / 嵌套 map / 列表项（均为缩进式）。"""
    if not text.startswith("---"):
        raise ValueError("缺少 frontmatter 起始 ---")
    lines = text.split("\n")
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        raise ValueError("缺少 frontmatter 结束 ---")
    body = lines[1:end]

    root = {}
    stack = [(0, root)]  # (child_key_indent, container)
    i = 0
    while i < len(body):
        raw = body[i]
        if not raw.strip():
            i += 1
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        s = raw.strip()
        while len(stack) > 1 and indent < stack[-1][0]:
            stack.pop()
        container = stack[-1][1]

        if s.startswith("- "):
            item = unquote(s[2:].strip())
            if not isinstance(container, list):
                raise ValueError("列表项不在列表中（缩进 %d）: %s" % (indent, s))
            container.append(item)
            i += 1
            continue

        if ":" not in s:
            raise ValueError("无法解析的行: %s" % s)
        key, _, val = s.partition(":")
        key = key.strip()
        val = val.strip()
        if isinstance(container, list):
            raise ValueError("map 键出现在列表中: %s" % s)

        if val in (">-", ">", "|", "|-"):
            buf = []
            i += 1
            while i < len(body):
                nxt = body[i]
                if nxt.strip() and (len(nxt) - len(nxt.lstrip(" "))) <= indent:
                    break
                buf.append(nxt.strip())
                i += 1
            container[key] = " ".join(x for x in buf if x)
            continue

        if val == "":
            # 依下一非空行判断是 map 还是 list
            nxt_indent = None
            nxt_is_item = False
            j = i + 1
            while j < len(body):
                if body[j].strip():
                    nxt_indent = len(body[j]) - len(body[j].lstrip(" "))
                    nxt_is_item = body[j].strip().startswith("- ")
                    break
                j += 1
            if nxt_is_item and nxt_indent is not None and nxt_indent > indent:
                lst = []
                container[key] = lst
                stack.append((nxt_indent, lst))
            else:
                d = {}
                container[key] = d
                child_indent = nxt_indent if (nxt_indent is not None and nxt_indent > indent) else indent + 2
                stack.append((child_indent, d))
            i += 1
            continue

        container[key] = unquote(val)
        i += 1
    return root


def json_examples(text):
    """抽取 {"tool": ..., "arguments": {...}} 形式的调用示例。"""
    pat = re.compile(
        r'\{\s*"tool"\s*:\s*"([A-Za-z_][A-Za-z0-9_]*)"\s*,\s*"arguments"\s*:\s*\{([^{}]*)\}\s*\}'
    )
    return [(m.group(1), m.group(2)) for m in pat.finditer(text)]


ok = True
report = []
all_used = set()

try:
    import yaml
    HAS_YAML = True
except Exception:
    HAS_YAML = False


def yaml_frontmatter(text):
    """用 PyYAML 严格解析 frontmatter（若可用）。"""
    lines = text.split("\n")
    if lines[0].strip() != "---":
        raise ValueError("首行不是 ---")
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        raise ValueError("缺少结束 ---")
    return yaml.safe_load("\n".join(lines[1:end]))

for slug, group in GROUP_OF_SLUG.items():
    path = os.path.join(SKILLS, slug, "SKILL.md")
    if not os.path.isfile(path):
        report.append("[缺失] %s" % path)
        ok = False
        continue
    with io.open(path, "r", encoding="utf-8") as f:
        text = f.read()
    line_count = text.count("\n") + (0 if text.endswith("\n") else 1)
    try:
        fm = parse_frontmatter(text)
    except Exception as e:
        report.append("[FM-解析失败] %s -> %s" % (slug, e))
        ok = False
        continue

    yaml_err = None
    if HAS_YAML:
        try:
            fm_yaml = yaml_frontmatter(text)
            if not isinstance(fm_yaml, dict):
                yaml_err = "PyYAML 结果不是 dict"
            else:
                # 以 PyYAML 结果为准做二次校验
                if fm_yaml.get("name") != fm.get("name"):
                    yaml_err = "PyYAML 与自研解析 name 不一致"
                if not isinstance(fm_yaml.get("metadata"), dict):
                    yaml_err = "PyYAML: metadata 不是 map"
                fm = fm_yaml
        except Exception as e:
            yaml_err = "PyYAML 解析失败: %s" % e
    if yaml_err:
        report.append("[FM-YAML-FAIL] %s -> %s" % (slug, yaml_err))
        ok = False
        continue

    errs = []
    args_bad = []
    if fm.get("name") != slug:
        errs.append("name=%r 与目录不一致" % fm.get("name"))
    if fm.get("version") != "1.0.0":
        errs.append("version=%r" % fm.get("version"))
    desc = fm.get("description")
    if not isinstance(desc, str) or len(desc) < 80:
        errs.append("description 缺失或过短")
    elif "也适用于" not in desc:
        errs.append("description 缺「也适用于用户要求…」句式")
    md = fm.get("metadata")
    if not isinstance(md, dict):
        errs.append("metadata 不是嵌套 map: %r" % type(md).__name__)
    else:
        for k in ("author", "package_type", "display_name", "category", "tags"):
            if k not in md:
                errs.append("metadata 缺 %s" % k)
        if md.get("package_type") != "skill":
            errs.append("package_type=%r" % md.get("package_type"))
        if not isinstance(md.get("tags"), list) or len(md.get("tags") or []) < 2:
            errs.append("tags 不是列表或条数<2: %r" % (md.get("tags"),))
    if line_count > 250:
        errs.append("行数 %d > 250" % line_count)

    # 工具名 / 参数 / 接口编码 与 spec 的一致性
    found = re.findall(r"`([a-z][a-z0-9_]{3,})`", text)  # 正文反引号内的标识符
    tool_mentions = set(found) & set(spec_tools)
    known_tool_like = set(re.findall(r'"tool"\s*:\s*"([A-Za-z_][A-Za-z0-9_]*)"', text))
    bad_tools = sorted(t for t in known_tool_like if t not in spec_tools)
    if bad_tools:
        errs.append("非 spec 工具: %s" % bad_tools)
    for name, body in json_examples(text):
        if name not in spec_tools:
            continue
        keys = set(re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"\s*:', body))
        extra = keys - spec_params[name]
        if extra:
            args_bad.append((name, sorted(extra)))
    if args_bad:
        errs.append("参数不在 spec: %s" % args_bad)
    codes = set(re.findall(r"pgp-\d{3}-\d{4}-\d{5}", text))
    bad_codes = sorted(codes - spec_codes)
    if bad_codes:
        errs.append("非 spec 接口编码: %s" % bad_codes)

    # 业务技能必须覆盖本域全部工具
    owned = sorted(n for n, t in spec_tools.items() if t["group"] == group) if group else []
    missing_owned = sorted(set(owned) - tool_mentions)
    if missing_owned:
        errs.append("未提及本域工具: %s" % missing_owned)

    # 正文必备要素
    for kw in ("结论", "数据表", "口径", "来源", "局限", "Mock"):
        if kw not in text:
            errs.append("缺要素: %s" % kw)

    used = sorted(tool_mentions)
    all_used |= set(used)
    status = "OK  " if not errs else "FAIL"
    if errs:
        ok = False
    report.append("[%s] %-32s 行数=%3d name=%-30s 工具=%d 编码=%d desc=%d字" % (
        status, slug, line_count, fm.get("name"), len(used), len(codes), len(desc) if isinstance(desc, str) else 0))
    for e in errs:
        report.append("        ! %s" % e)

# references 文件检查
REFS = {slug: ["queries.md"] for slug in GROUP_OF_SLUG}
REFS["substation-qa-orchestrator"] = ["routing.md", "metrics.md", "queries.md"]
report.append("")
for slug, files in REFS.items():
    for fn in files:
        p = os.path.join(SKILLS, slug, "references", fn)
        if not os.path.isfile(p):
            ok = False
            report.append("[缺失] %s" % p)
            continue
        with io.open(p, "r", encoding="utf-8") as f:
            t = f.read()
        q = len(re.findall(r"^### 问数", t, re.M))
        illegal = sorted(set(re.findall(r'"tool"\s*:\s*"([A-Za-z_][A-Za-z0-9_]*)"', t)) - set(spec_tools))
        bad_codes = sorted(set(re.findall(r"pgp-\d{3}-\d{4}-\d{5}", t)) - spec_codes)
        line_n = t.count("\n") + 1
        msg = "    ref %-46s 行=%3d 问数=%2d" % (slug + "/" + fn, line_n, q)
        if illegal:
            ok = False
            msg += " 非spec工具=%s" % illegal
        if bad_codes:
            ok = False
            msg += " 非spec编码=%s" % bad_codes
        report.append(msg)

# 编排技能不应直接持有工具（正文允许提及领域工具，但需声明不直接持有）
with io.open(os.path.join(SKILLS, "substation-qa-orchestrator", "SKILL.md"), "r", encoding="utf-8") as f:
    orch = f.read()
if "不直接持有" not in orch:
    ok = False
    report.append("[FAIL] 编排技能缺「不直接持有工具」权限说明")

report.append("")
report.append("spec 工具数=%d 接口编码数=%d；正文覆盖工具数=%d" % (len(spec_tools), len(spec_codes), len(all_used)))
report.append("frontmatter 校验方式: PyYAML=%s + 自研最小解析器" % ("可用" if HAS_YAML else "不可用"))
report.append("未覆盖的 spec 工具: %s" % (sorted(set(spec_tools) - all_used) or "无"))
report.append("总体结论: %s" % ("PASS" if ok else "FAIL"))
out = "\n".join(report)
print(out)
with io.open(os.path.join(ROOT, "work", "skill_selfcheck_report.txt"), "w", encoding="utf-8") as f:
    f.write(out + "\n")
sys.exit(0 if ok else 1)
