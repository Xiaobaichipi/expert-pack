import re
p=r'research/cli/cli/skills_store_cli.py'
s=open(p,encoding='utf-8',errors='replace').read()
i=s.find('def install_zip_to_target')
print(s[i:i+3000])
