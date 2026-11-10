# -*- coding: utf-8 -*-
"""Markdown 结构轻量检查：表格列数一致、代码围栏闭合、标题层级、尾随空格。"""
import io
import os
import re
import sys

ROOT = r"F:\work\2026年\10月\专家包\expert-pack\skills"
TARGETS = [
    "substation-asset-ledger/SKILL.md",
    "substation-asset-ledger/references/queries.md",
    "substation-device-tree/SKILL.md",
    "substation-device-tree/references/queries.md",
    "substation-om-health/SKILL.md",
    "substation-om-health/references/queries.md",
    "substation-maintenance-test/SKILL.md",
    "substation-maintenance-test/references/queries.md",
    "substation-reliability/SKILL.md",
    "substation-reliability/references/queries.md",
    "substation-resource-topology/SKILL.md",
    "substation-resource-topology/references/queries.md",
    "substation-qa-orchestrator/SKILL.md",
    "substation-qa-orchestrator/references/routing.md",
    "substation-qa-orchestrator/references/metrics.md",
    "substation-qa-orchestrator/references/queries.md",
]

problems = []
for rel in TARGETS:
    p = os.path.join(ROOT, rel.replace("/", os.sep))
    with io.open(p, "r", encoding="utf-8") as f:
        lines = f.read().split("\n")
    fence = 0
    block = []
    for idx, ln in enumerate(lines, 1):
        if ln.strip().startswith("```"):
            fence += 1
            # 结束上一个表格块
            block = []
            continue
        if fence % 2 == 1:
            continue
        if ln.strip().startswith("|"):
            block.append((idx, ln))
        else:
            if len(block) >= 2:
                counts = set()
                for bi, bl in block:
                    # 去掉行首尾竖线后统计分隔符数
                    inner = bl.strip()
                    n = inner.count("|")
                    counts.add(n)
                if len(counts) > 1:
                    problems.append("%s:%d-%d 表格列数不一致 %s" % (rel, block[0][0], block[-1][0], sorted(counts)))
            block = []
    if len(block) >= 2:
        counts = set(bl.strip().count("|") for _, bl in block)
        if len(counts) > 1:
            problems.append("%s 末尾表格列数不一致 %s" % (rel, sorted(counts)))
    if fence % 2 != 0:
        problems.append("%s 代码围栏未闭合（%d 个 ```）" % (rel, fence))
    # 标题层级跳级粗检
    heads = [(i, re.match(r"^(#+)\s", l).group(1)) for i, l in enumerate(lines, 1) if re.match(r"^#{1,6}\s", l)]
    for (i1, h1), (i2, h2) in zip(heads, heads[1:]):
        if len(h2) > len(h1) + 1:
            problems.append("%s:%d 标题层级跳级 %s -> %s" % (rel, i2, h1, h2))
    # 行尾空格
    for i, l in enumerate(lines, 1):
        if l != l.rstrip():
            problems.append("%s:%d 行尾空格" % (rel, i))
    # 全角/半角括号混用粗检（仅提示，跳过含代码片段/公式的行）
    body = "\n".join(l for l in lines if "`" not in l)
    if "（" in body and re.search(r"\([^)]*[\u4e00-\u9fff][^)]*\)", body):
        problems.append("%s 提示：存在半角括号包裹中文的写法，建议核对" % rel)

if problems:
    print("\n".join(problems))
    print("LINT: FAIL (%d)" % len(problems))
    sys.exit(1)
print("LINT: PASS (%d 个文件)" % len(TARGETS))
sys.exit(0)
