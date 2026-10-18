"""Switch the existing public Minecraft port to NAPAR, preserving rollback."""
import ast
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import socket
import subprocess
import time
import urllib.request
from uuid import uuid4

from dotenv import dotenv_values

BASE = Path('/opt/napar-next')
BRAIN = BASE/'brain'
SERVER = BASE/'server'
SOURCES = 'https://raw.githubusercontent.com/Eg0rkabit/minecraft_napar_v1/1772a7eaa58b10f7121cdd0f5726d280e3433c7a/deploy/'
JAR_SHA = 'ea1bb715dfdf8a72d6b71a6fceb26d1f62cd67c8e69925e6ec1352ec8e738306'


def systemctl(*args, check=True):
    return subprocess.run(['systemctl',*args],check=check,capture_output=True,text=True,timeout=180)


def fetch(name):
    with urllib.request.urlopen(SOURCES+name,timeout=40) as response:
        return response.read()


def ready(started_at):
    log = SERVER/'logs/latest.log'
    return systemctl('is-active','--quiet','napar-next-game',check=False).returncode == 0 and \
        log.exists() and log.stat().st_mtime >= started_at and 'Napar runtime loaded.' in log.read_text(errors='replace')


def main():
    assert os.geteuid() == 0 and BASE.resolve() == BASE and not BASE.is_symlink()
    assert (SERVER/'eula.txt').read_text().strip() == 'eula=true'
    config = dotenv_values(BRAIN/'.env')
    assert config['NAPAR_OWNER_NAME'] == 'MrHobet'
    assert config['NAPAR_LLM_MODEL'] == 'openai/gpt-5' and config['NAPAR_LLM_BACKEND'] == 'openai'
    assert config['NAPAR_LLM_BASE_URL'] == 'https://api.proxyapi.ru/v1'
    assert len(config['NAPAR_BRIDGE_TOKEN']) >= 32
    account = pwd.getpwnam('napar-next')
    jar = base64.b64decode(fetch('napar-launch-body.jar.b64'),validate=False)
    assert hashlib.sha256(jar).hexdigest() == JAR_SHA
    wrapper = fetch('serve-minecraft-vps.py')
    ast.parse(wrapper)
    old_active = systemctl('is-active','--quiet','minecraft',check=False).returncode == 0
    old_enabled = systemctl('is-enabled','minecraft',check=False).stdout.strip()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = BASE/('launch-backup-'+stamp)
    backup.mkdir(mode=0o700)
    for source in [SERVER/'server.properties',SERVER/'napar-world-id.txt',SERVER/'whitelist.json']:
        if source.exists():
            shutil.copy2(source,backup/source.name)
    for source in (SERVER/'mods').glob('*napar*.jar'):
        shutil.copy2(source,backup/source.name)
    state = {'old_active':old_active,'old_enabled':old_enabled,'old_world':'/opt/minecraft',
             'production_world':str(SERVER/'world-napar'),'backup':str(backup)}
    (backup/'state.json').write_text(json.dumps(state,indent=2))
    (BRAIN/'deploy/serve_minecraft.py').write_bytes(wrapper)
    (BRAIN/'deploy/serve_minecraft.py').chmod(0o644)
    # Replace the same NAPAR jar, preserving other installed mods.
    targets = list((SERVER/'mods').glob('*napar*.jar'))
    assert len(targets) == 1, 'Expected exactly one installed NAPAR mod'
    targets[0].write_bytes(jar)
    os.chown(targets[0],account.pw_uid,account.pw_gid)
    props = {}
    for line in (SERVER/'server.properties').read_text().splitlines():
        if line and not line.startswith('#') and '=' in line:
            key,value = line.split('=',1)
            props[key] = value
    fresh_world = props.get('level-name') != 'world-napar'
    props.update({'server-ip':'','server-port':'25565','online-mode':'true',
        'level-name':'world-napar','view-distance':'6','simulation-distance':'4',
        'max-players':'4','white-list':'true','enforce-whitelist':'true',
        'spawn-protection':'0','enable-rcon':'false','enable-query':'false',
        'enable-command-block':'false','motd':'NAPAR | MrHobet | Minecraft 26.2',
        'gamemode':'survival','difficulty':'normal'})
    (SERVER/'server.properties').write_text(''.join(k+'='+v+'\n' for k,v in props.items()))
    (SERVER/'whitelist.json').write_text(json.dumps([{
        'uuid':'55bf9e3c-7da0-4163-a4af-b9d23e9ca460','name':'MrHobet'}]))
    if fresh_world:
        (SERVER/'napar-world-id.txt').write_text(str(uuid4()))
    for name in ['server.properties','whitelist.json','napar-world-id.txt']:
        os.chown(SERVER/name,account.pw_uid,account.pw_gid)
    unit = Path('/etc/systemd/system/napar-next-game.service')
    if unit.exists():
        assert 'WorkingDirectory=/opt/napar-next/server' in unit.read_text()
        shutil.copy2(unit,backup/unit.name)
    unit.write_text('''[Unit]
Description=NAPAR Minecraft 26.2
Wants=network-online.target napar-next-brain.service
After=network-online.target napar-next-brain.service

[Service]
Type=simple
User=napar-next
Group=napar-next
WorkingDirectory=/opt/napar-next/server
ExecStart=/opt/napar-next/brain/.venv/bin/python /opt/napar-next/brain/deploy/serve_minecraft.py
RuntimeDirectory=napar-next-game
RuntimeDirectoryMode=0700
Restart=on-failure
RestartSec=5
KillMode=mixed
TimeoutStopSec=75
MemoryMax=3G
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/napar-next/server /run/napar-next-game

[Install]
WantedBy=multi-user.target
''')
    rollback = BASE/'rollback-public-server.sh'
    rollback.write_text('#!/bin/sh\nset -e\nsystemctl stop napar-next-game\nsystemctl disable napar-next-game\n'+
        ('systemctl enable minecraft\n' if old_enabled == 'enabled' else '')+
        ('systemctl start minecraft\n' if old_active else ''))
    rollback.chmod(0o700)
    systemctl('daemon-reload')
    print('Backup prepared:',backup,flush=True)
    print('Switching public port 25565 to NAPAR. Existing world stays in /opt/minecraft.',flush=True)
    try:
        if old_active:
            systemctl('stop','minecraft')
        systemctl('start','napar-next-brain')
        started_at = time.time()
        systemctl('start','napar-next-game')
        deadline = time.monotonic()+150
        while time.monotonic() < deadline:
            if ready(started_at):
                break
            time.sleep(1)
        else:
            raise RuntimeError('New server did not become ready')
        with socket.create_connection(('127.0.0.1',25565),timeout=5):
            pass
        systemctl('disable','minecraft')
        systemctl('enable','napar-next-brain','napar-next-game')
    except BaseException:
        systemctl('stop','napar-next-game',check=False)
        if old_enabled == 'enabled':
            systemctl('enable','minecraft')
        if old_active:
            systemctl('start','minecraft')
        print('Launch failed; previous public service restored.',flush=True)
        raise
    print('READY: Minecraft 26.2, port 25565. Whitelist: MrHobet. Authentication enabled.',flush=True)
    print('Brain and game enabled for boot. Napar appears on owner join. Rollback:',rollback,flush=True)


if __name__ == '__main__':
    main()
