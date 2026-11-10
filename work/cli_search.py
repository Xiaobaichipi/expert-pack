import re
p=r'research/cli/cli/skills_store_cli.py'
s=open(p,encoding='utf-8',errors='replace').read()
out=[]
for kw in ['mcp','manifest','expert','skillset','SKILL.md','skill_slug']:
    idx=[m.start() for m in re.finditer(kw,s,re.I)]
    out.append(f'### {kw}: {len(idx)}')
    for i in idx[:3]:
        out.append(s[max(0,i-250):i+400].replace('\r',''))
open('work/cli_hits.txt','w',encoding='utf-8').write('\n'.join(out))
print('ok')
