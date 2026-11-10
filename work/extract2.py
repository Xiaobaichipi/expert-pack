import re
s=open(r'research/skill-hub.js',encoding='utf-8',errors='replace').read()
i=s.find('skillhub-expert-package')
seg=s[i-3000:i+2500]
seg=re.sub(r'(?<=[;{}])', '\n', seg)
open('work/export_pretty.txt','w',encoding='utf-8').write(seg)
print(len(seg))
