import re
s=open(r'research/skill-hub.js',encoding='utf-8',errors='replace').read()
i=s.find('skillhub-expert-package')
print('offset',i)
open('work/export_snippet.txt','w',encoding='utf-8').write(s[i-6000:i+4500])
# also find function names nearby
print(s[i-3000:i+200][:0])
