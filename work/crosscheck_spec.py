import json,re
spec=json.load(open(r'expert-pack/spec/interfaces.json',encoding='utf-8'))
tools={t['code']:t for t in spec['tools']}
# parse docx dump table 0
text=open(r'work/docx_dump.txt',encoding='utf-8').read()
rows=[]
started=False
for line in text.splitlines():
    if line.startswith('--- table 0'): started=True; continue
    if started:
        if line.startswith('--- table 1'): break
        if '|' in line: rows.append([c.strip() for c in line.split('|')])
print('docx rows:',len(rows)-1)
problems=[]
for r in rows[1:]:
    code,name,path,center,domain,ver=r[:6]
    t=tools.get(code)
    if not t: problems.append(('missing in spec',code,name)); continue
    if t['path']!=path: problems.append(('path mismatch',code,t['path'],path))
    if t['title']!=name: problems.append(('title mismatch',code,t['title'],name))
print('mismatches:',problems if problems else 'none')
print('spec count',len(spec['tools']))
# check group counts
import collections
print(collections.Counter(t['group'] for t in spec['tools']))
# check every tool has mock + params + responseHint
for t in spec['tools']:
    for k in ['name','code','title','group','method','path','params','responseHint','mock','typicalQuestions']:
        if k not in t: print('MISSING FIELD',t.get('name'),k)
print('field check done')
