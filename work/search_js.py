import re,sys
for f in [r'research/skill-hub.js', r'research/skill-hub-raw.js']:
    s=open(f,encoding='utf-8',errors='replace').read()
    print('=====',f,len(s))
    for kw in ['skillset','manifestVersion','mcpServers','identify.md','SUITE.yaml','swarm']:
        idx=[m.start() for m in re.finditer(kw,s)]
        print(f'-- {kw}: {len(idx)} hits')
        for i in idx[:4]:
            print('   ...',s[max(0,i-200):i+260].replace('\n',' ')[:460])
