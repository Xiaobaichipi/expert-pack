import re
s=open(r'research/skill-hub.js',encoding='utf-8',errors='replace').read()
out=[]
for kw in ['getIdentityMarkdown','skillSlugs']:
    out.append('##### '+kw)
    for m in list(re.finditer(re.escape(kw), s))[:4]:
        i=m.start(); seg=s[max(0,i-700):i+1000]
        seg=re.sub(r'(?<=[;{}])', '\n', seg)
        out.append(f'--- off {i}\n{seg[:2000]}')
open('work/identity_pretty.txt','w',encoding='utf-8').write('\n'.join(out))
print('done')
