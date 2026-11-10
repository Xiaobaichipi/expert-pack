import io, json
from docx import Document
d = Document(r"变电智能问数_26接口功能说明.docx")
out=[]
out.append("=== PARAGRAPHS ===")
for i,p in enumerate(d.paragraphs):
    t=p.text.strip()
    if t: out.append(f"[{i}][{p.style.name}] {t}")
out.append("=== TABLES ===")
for ti,tb in enumerate(d.tables):
    out.append(f"--- table {ti} rows={len(tb.rows)} cols={len(tb.columns)}")
    for r in tb.rows:
        out.append(" | ".join(c.text.strip().replace("\n"," / ") for c in r.cells))
open("work/docx_dump.txt","w",encoding="utf-8").write("\n".join(out))
print("ok", len(out))
