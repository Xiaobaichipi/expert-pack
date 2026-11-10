from docx import Document
d = Document(r"变电智能问数_26接口功能说明.docx")
print("=== PARAGRAPHS ===")
for i,p in enumerate(d.paragraphs):
    t=p.text.strip()
    if t:
        print(f"[{i}][{p.style.name}] {t}")
print("=== TABLES ===")
for ti,tb in enumerate(d.tables):
    print(f"--- table {ti} rows={len(tb.rows)} cols={len(tb.columns)}")
    for r in tb.rows:
        print(" | ".join(c.text.strip().replace("\n"," / ") for c in r.cells))
