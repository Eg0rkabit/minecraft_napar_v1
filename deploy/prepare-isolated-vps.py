"""Prepare only /opt/napar-next; never stop or modify the existing Minecraft service."""
from pathlib import Path
import hashlib
import os
import pwd
import secrets
import shutil
import subprocess
import urllib.request

base = Path('/opt/napar-next')
brain = base / 'brain'
server = base / 'server'
assert os.geteuid() == 0
assert base.resolve() == base and not base.is_symlink()
assert (brain / 'src/napar/app.py').is_file()
assert (brain / '.venv/bin/napar').is_file()
try:
    account = pwd.getpwnam('napar-next')
except KeyError:
    subprocess.run(['useradd','--system','--no-create-home','--home-dir',str(base),'--shell','/usr/sbin/nologin','napar-next'],check=True)
    account = pwd.getpwnam('napar-next')
os.chown(base,0,account.pw_gid)
base.chmod(0o750)
data = brain / 'data'
data.mkdir(exist_ok=True)
os.chown(data,account.pw_uid,account.pw_gid)
data.chmod(0o750)
config = brain / '.env'
if not config.exists():
    with config.open('x') as handle:
        handle.write('NAPAR_BRIDGE_TOKEN='+secrets.token_urlsafe(32)+'\n')
        handle.write('NAPAR_DATABASE=data/napar.db\nNAPAR_LLM_BACKEND=disabled\nNAPAR_OWNER_NAME=MrHobet\n')
    config.chmod(0o600)
    os.chown(config,account.pw_uid,account.pw_gid)

def download(url, destination, checksum=None):
    if destination.exists():
        content=destination.read_bytes()
    else:
        with urllib.request.urlopen(url,timeout=60) as response:
            content=response.read()
        if checksum and hashlib.sha256(content).hexdigest()!=checksum:
            raise RuntimeError('Checksum mismatch')
        destination.write_bytes(content)
    if checksum and hashlib.sha256(content).hexdigest()!=checksum:
        raise RuntimeError('Existing checksum mismatch')

(server/'mods').mkdir(parents=True,exist_ok=True)
download('https://github.com/gnembon/fabric-carpet/releases/download/v26.2/fabric-carpet-26.2%2Bv260616.jar',
         server/'mods/carpet-26.2.jar','f6ada912af65c91536d4b0d80adf26cc438253252ddaf259f2c6617ae471311c')
download('https://maven.fabricmc.net/net/fabricmc/fabric-api/fabric-api/0.161.0+26.2/fabric-api-0.161.0+26.2.jar',
         server/'mods/fabric-api-0.161.0+26.2.jar')
download('https://meta.fabricmc.net/v2/versions/loader/26.2/0.19.5/1.1.2/server/jar',
         server/'fabric-server-launch.jar')
properties=server/'server.properties'
if not properties.exists():
    properties.write_text('server-ip=127.0.0.1\nserver-port=25575\nonline-mode=true\nview-distance=4\nsimulation-distance=4\nmax-players=4\nmotd=NAPAR isolated test\n',encoding='utf-8')
for directory, dirs, files in os.walk(server):
    os.chown(directory,account.pw_uid,account.pw_gid)
    for name in files:
        os.chown(Path(directory)/name,account.pw_uid,account.pw_gid)
unit=Path('/etc/systemd/system/napar-next-brain.service')
if unit.exists() and 'WorkingDirectory=/opt/napar-next/brain' not in unit.read_text():
    raise RuntimeError('Unrelated existing service')
unit.write_text('''[Unit]
Description=NAPAR prototype brain (isolated)
After=network-online.target

[Service]
User=napar-next
Group=napar-next
WorkingDirectory=/opt/napar-next/brain
EnvironmentFile=/opt/napar-next/brain/.env
ExecStart=/opt/napar-next/brain/.venv/bin/napar
Restart=on-failure
RestartSec=3
MemoryMax=256M
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/napar-next/brain/data

[Install]
WantedBy=multi-user.target
''')
subprocess.run(['systemctl','daemon-reload'],check=True)
subprocess.run(['systemctl','start','napar-next-brain'],check=True)
print('Prepared isolated server files; brain started with LLM disabled. Existing Minecraft unchanged.')
