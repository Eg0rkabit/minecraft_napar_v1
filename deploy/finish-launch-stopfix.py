"""Install the final stop fix and verify one graceful service restart."""
import base64
import hashlib
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import time
import urllib.request

base = Path('/opt/napar-next')
server = base/'server'
source = 'https://raw.githubusercontent.com/Eg0rkabit/minecraft_napar_v1/cfdb33c3404542b0d8dc284afb603add73f76344/deploy/napar-launch-stopfix.jar.b64'
with urllib.request.urlopen(source,timeout=40) as response:
    data = base64.b64decode(response.read())
assert hashlib.sha256(data).hexdigest() == '57b503f5471a54e20d2ea62a6608035a1424011d90b9fcd09ffcce4aa56b6dd7'
targets = list((server/'mods').glob('*napar*.jar'))
assert len(targets) == 1
target = targets[0]
subprocess.run(['systemctl','stop','napar-next-game'],check=True,timeout=90)
backup = base/'napar-before-stopfix.jar'
if not backup.exists():
    shutil.copy2(target,backup)
account = pwd.getpwnam('napar-next')
temporary = target.with_suffix('.new')
temporary.write_bytes(data)
os.chown(temporary,account.pw_uid,account.pw_gid)
temporary.chmod(0o644)
os.replace(temporary,target)
started = time.time()
subprocess.run(['systemctl','start','napar-next-game'],check=True)
deadline = time.monotonic()+100
while time.monotonic() < deadline:
    log = server/'logs/latest.log'
    if log.exists() and log.stat().st_mtime >= started and 'Napar runtime loaded.' in log.read_text(errors='replace'):
        break
    time.sleep(1)
else:
    subprocess.run(['systemctl','stop','napar-next-game'],check=True,timeout=90)
    shutil.copy2(backup,target)
    subprocess.run(['systemctl','start','napar-next-game'],check=True)
    raise SystemExit('Final update failed; previous working NAPAR restored.')
subprocess.run(['systemctl','is-active','napar-next-brain','napar-next-game'],check=True)
subprocess.run(['systemctl','is-enabled','napar-next-brain','napar-next-game'],check=True)
print('PASS: graceful restart; final NAPAR build loaded; both services active and enabled.',flush=True)
print('JOIN: Minecraft Java 26.2, 77.110.105.165:25565, account MrHobet.',flush=True)
print('Old world retained at /opt/minecraft; rollback script /opt/napar-next/rollback-public-server.sh',flush=True)
