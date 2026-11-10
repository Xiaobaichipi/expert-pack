import re
p=r'research/cli/cli/skills_store_cli.py'
lines=open(p,encoding='utf-8',errors='replace').read().splitlines()
for i,l in enumerate(lines,1):
    if re.match(r'^(def |class )', l) and any(k in l for k in ['pack','publish','front','manifest','skill','zip','soul','download']):
        print(i, l[:120])
print('total',len(lines))
