"""Read-only post-update checks on the VPS; no model requests or secrets printed."""
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request

from dotenv import dotenv_values

base=Path('/opt/napar-next')
values=dotenv_values(base/'brain/.env')
request=urllib.request.Request('http://127.0.0.1:8000/v1/status',headers={
    'Authorization':'Bearer '+values['NAPAR_BRIDGE_TOKEN']})
with urllib.request.urlopen(request,timeout=5) as response:status=json.load(response)
assert status['connected'] and len(status['capabilities'])==21,status
assert status['limits']['daily_calls']==status['limits']['steps']==0,status['limits']
properties=dict(line.split('=',1) for line in (base/'server/server.properties').read_text().splitlines()
                if '=' in line and not line.startswith('#'))
assert properties['difficulty']=='normal' and properties['view-distance']=='16'
installed=json.loads((base/'upgrade-0.2-result.json').read_text())
mods=list((base/'server/mods').glob('*napar*.jar'))
assert len(mods)==1
assert hashlib.sha256(mods[0].read_bytes()).hexdigest()==installed['body_sha256']
services={}
for name in ('napar-next-brain','napar-next-game'):
    def systemctl(*args):return subprocess.check_output(['systemctl',*args,name],text=True,timeout=10).strip()
    assert systemctl('is-active')=='active'
    assert systemctl('is-enabled')=='enabled'
    memory=int(systemctl('show','-p','MemoryCurrent','--value'))
    services[name]={'active':True,'enabled':True,'memory_mib':round(memory/1048576)}
result={'passed':True,'commit':installed['commit'],'body_sha256':installed['body_sha256'],
        'connected':True,'game_tools':len(status['capabilities']),'limits':status['limits'],
        'difficulty':properties['difficulty'],'view_distance':int(properties['view-distance']),
        'services':services,'backup':installed['backup']}
(base/'runtime-0.2-result.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))
print('READY: Minecraft Java 26.2 / 77.110.105.165:25565 / MrHobet')

