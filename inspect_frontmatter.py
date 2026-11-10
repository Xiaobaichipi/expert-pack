import json, pathlib, re
root = pathlib.Path(r"F:\work\2026年\10月\专家包\expert-pack\skills")
for d in sorted(root.iterdir()):
    md = d / "SKILL.md"
    if not md.is_file(): continue
    raw = md.read_bytes()
    has_bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    lines = text.split("\n")
    assert lines[0].strip()=="---", (d.name, lines[0])
    end = next(i for i in range(1,len(lines)) if lines[i].strip()=="---")
    fm = "\n".join(lines[1:end])
    # top-level keys
    keys=[l.split(":")[0].strip() for l in fm.split("\n") if re.match(r"^[A-Za-z_][A-Za-z0-9_]*:", l)]
    # metadata block display_name
    m = re.search(r"(?ms)^metadata:\n((?:[ \t]+.*\n?)*)", fm+"\n")
    disp = re.search(r"(?m)^[ \t]+display_name:\s*(.+)$", fm+"\n")
    print(d.name, "| bom=", has_bom, "| keys=", keys, "| display_name=", (disp.group(1).strip() if disp else None))
