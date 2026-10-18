"""Update only the isolated brain and open a hidden ProxyAPI key prompt."""
import ast
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import urllib.request

base = Path('/opt/napar-next')
brain = base / 'brain'
assert os.geteuid() == 0 and base.resolve() == base
url = 'https://raw.githubusercontent.com/Eg0rkabit/minecraft_napar_v1/8ce5c14679b0bd04e6401ea94677e88f5336bde7/deploy/'
files = [('gpt5-llm.py', brain/'src/napar/llm.py'),
         ('test_model_api.py', brain/'tests/test_model_api.py'),
         ('configure-proxyapi-gpt5-checked.py', base/'configure-proxy-gpt5.py')]
staged = []
for remote, target in files:
    with urllib.request.urlopen(url + remote, timeout=30) as response:
        data = response.read()
    ast.parse(data)
    staged.append((target, data))
for target, data in staged:
    backup = target.with_suffix(target.suffix + '.before-gpt5')
    if target.exists() and not backup.exists():
        shutil.copy2(target, backup)
    temporary = target.with_suffix(target.suffix + '.gpt5-new')
    temporary.write_bytes(data)
    temporary.chmod(0o644)
    os.replace(temporary, target)
print('GPT-5 adapter installed. Running offline checks; no paid requests yet.', flush=True)
subprocess.run([str(brain/'.venv/bin/python'), '-m', 'pytest', '-q', '-p', 'no:cacheprovider'],
               cwd=brain, check=True)
print('Checks passed. Opening hidden input for ProxyAPI.', flush=True)
runpy.run_path(str(base/'configure-proxy-gpt5.py'), run_name='__main__')
