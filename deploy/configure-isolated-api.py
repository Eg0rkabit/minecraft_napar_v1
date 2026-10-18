"""Run with /opt/napar-next/brain/.venv/bin/python as root; never print secrets."""
from pathlib import Path
import getpass
import os
import pwd
import subprocess
from dotenv import dotenv_values

path=Path('/opt/napar-next/brain/.env')
if os.geteuid()!=0 or path.is_symlink() or not path.is_file():
    raise SystemExit('Run as root after preparing the isolated installation')
values=dict(dotenv_values(path))
key=getpass.getpass('API key (hidden; empty cancels): ').strip()
if not key:
    raise SystemExit('Cancelled; configuration unchanged')
if any(c.isspace() for c in key) or not key.isascii():
    raise SystemExit('Invalid key; configuration unchanged')
model=input('Model [gpt-4o-mini]: ').strip() or 'gpt-4o-mini'
if not all(c.isalnum() or c in '-_./' for c in model):
    raise SystemExit('Invalid model; configuration unchanged')
values.update(NAPAR_LLM_BACKEND='openai',NAPAR_LLM_API_KEY=key,NAPAR_LLM_MODEL=model)
values.setdefault('NAPAR_LLM_BASE_URL','https://api.openai.com/v1')
account=pwd.getpwnam('napar-next')
temporary=path.with_suffix('.env.pending')
fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'w') as out:
    for name,value in values.items():
        if value is not None:
            if '\n' in value or '\r' in value: raise ValueError('Unexpected newline')
            out.write(name+'='+value+'\n')
os.chown(temporary,account.pw_uid,account.pw_gid)
os.replace(temporary,path)
subprocess.run(['systemctl','restart','napar-next-brain'],check=True)
print('API configuration saved; bridge token preserved. Check model access before gameplay.')
