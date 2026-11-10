# -*- coding: utf-8 -*-
import io, json, os, re
ROOT = r"F:\work\2026年\10月\专家包"
SPEC = os.path.join(ROOT, "expert-pack", "spec", "interfaces.json")
SK = os.path.join(ROOT, "expert-pack", "skills")
spec = json.load(io.open(SPEC, encoding="utf-8"))
params = {t["name"]: set(p["name"] for p in t["params"]) for t in spec["tools"]}
ownercode = {t["name"]: t["code"] for t in spec["tools"]}
bad = []
n_examples = 0
for dirpath, _, files in os.walk(SK):
    if "pms-gateway-mcp" in dirpath:
        continue
    for fn in files:
        if not fn.endswith(".md"):
            continue
        p = os.path.join(dirpath, fn)
        text = io.open(p, encoding="utf-8").read()
        for m in re.finditer(r'\{\s*"tool"\s*:\s*"([A-Za-z_][A-Za-z0-9_]*)"\s*,\s*"arguments"\s*:\s*\{([^{}]*)\}\s*\}', text):
            name, body = m.group(1), m.group(2)
            n_examples += 1
            if name not in params:
                bad.append((p, name, "NOT_IN_SPEC"))
                continue
            keys = set(re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"\s*:', body))
            extra = keys - params[name]
            if extra:
                bad.append((p, name, sorted(extra)))
print("JSON 调用示例总数:", n_examples)
for b in bad:
    print("BAD:", b[0].replace(SK + os.sep, ""), b[1], b[2])
print("ARG-CHECK:", "PASS" if not bad else "FAIL")
