"""Atomic, reversible 0.2 update of the existing NAPAR installation. Run as root."""
import argparse
import atexit
import base64
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import pwd
import shutil
import socket
import sqlite3
import struct
import subprocess
import time
import urllib.request
import zipfile

from dotenv import dotenv_values, set_key

BASE=Path('/opt/napar-next')
BRAIN=BASE/'brain'
GAME=BASE/'server'
PYTHON=BRAIN/'.venv/bin/python'


def run(*command, **kwargs):
    return subprocess.run(command,check=True,timeout=120,**kwargs)


def fetch(url):
    with urllib.request.urlopen(url,timeout=45) as response:
        data=response.read(20_000_001)
        if len(data)>20_000_000:raise ValueError('Release exceeds download limit')
        return data


def nbt_player(path):
    """Read vanilla player NBT only to preserve presence across the first upgrade."""
    with gzip.open(path,'rb') as stream:
        data=stream.read(8_000_001)
    if len(data)>8_000_000:raise ValueError('Player data exceeds limit')
    source=io.BytesIO(data)
    def number(fmt):
        size=struct.calcsize(fmt)
        return struct.unpack(fmt,source.read(size))[0]
    def text():return source.read(number('>H')).decode('utf-8')
    def value(kind,depth=0):
        if depth>64:raise ValueError('NBT depth limit')
        if kind in (1,2,3,4,5,6):return number({1:'>b',2:'>h',3:'>i',4:'>q',5:'>f',6:'>d'}[kind])
        if kind==8:return text()
        if kind==9:
            subtype=number('>B');length=number('>i')
            if length<0 or length>100000:raise ValueError('NBT list limit')
            return [value(subtype,depth+1) for _ in range(length)]
        if kind==10:
            out={}
            for _ in range(100000):
                subtype=number('>B')
                if subtype==0:return out
                name=text();out[name]=value(subtype,depth+1)
            raise ValueError('NBT compound limit')
        if kind in (7,11,12):
            length=number('>i')
            if length<0 or length>1000000:raise ValueError('NBT array limit')
            size={7:1,11:4,12:8}[kind]
            source.read(length*size)
            return None
        raise ValueError('Unknown NBT tag')
    if number('>B')!=10:raise ValueError('Expected compound root')
    text()
    return value(10)


def prepare_presence(account):
    destination=GAME/'napar-runtime.json'
    if destination.exists():return
    cache=json.loads((GAME/'usercache.json').read_text())
    profile=next((entry for entry in cache if entry['name'].lower()=='napar'),None)
    if not profile:raise ValueError('No saved NAPAR profile; refusing to invent its position')
    player=nbt_player(GAME/'world-napar/players/data'/f'{profile["uuid"]}.dat')
    point=player['Pos']
    record={'world':(GAME/'napar-world-id.txt').read_text().strip(),
            'dimension':player.get('Dimension','minecraft:overworld'),
            'position':dict(zip(('x','y','z'),point)),
            'yaw':player.get('Rotation',[0,0])[0],'pitch':player.get('Rotation',[0,0])[1],
            'health':max(.5,float(player.get('Health',20)))}
    destination.write_text(json.dumps(record))
    os.chown(destination,account.pw_uid,account.pw_gid)
    destination.chmod(0o600)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--ref',required=True)
    args=parser.parse_args()
    if len(args.ref)!=40 or any(char not in '0123456789abcdef' for char in args.ref):raise ValueError('Use an immutable commit SHA')
    if os.geteuid()!=0 or BASE.resolve()!=BASE or not (BRAIN/'.env').is_file():raise ValueError('Unexpected installation or user')
    account=pwd.getpwnam('napar-next')
    stage=BASE/'releases'/('0.2-'+args.ref[:12])
    stage.mkdir(parents=True,exist_ok=True)
    stage.chmod(0o750)
    payload=fetch(f'https://codeload.github.com/Eg0rkabit/minecraft_napar_v1/zip/{args.ref}')
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names=archive.namelist();prefix=names[0].split('/')[0]+'/'
        for name in names:
            relative=name.removeprefix(prefix)
            if name.endswith('/') or '..' in Path(relative).parts:continue
            allowed=(relative.startswith(('src/napar/','tests/')) and relative.endswith('.py')) or relative in ('pyproject.toml','brain.py','deploy/release-0.2.json')
            if allowed:
                destination=stage/relative;destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(archive.read(name))
        manifest=json.loads((stage/'deploy/release-0.2.json').read_text())
        encoded=''.join(archive.read(prefix+part).decode().strip() for part in manifest['parts'])
        body=base64.b64decode(encoded,validate=True)
    if hashlib.sha256(body).hexdigest()!=manifest['body_sha256']:raise ValueError('Body checksum mismatch')
    values=dotenv_values(BRAIN/'.env')
    database=Path(values.get('NAPAR_DATABASE') or 'data/napar.db')
    if not database.is_absolute():database=BRAIN/database
    database=database.resolve()
    if not database.is_relative_to(BRAIN):raise ValueError('Database is outside the expected installation')
    mods=list((GAME/'mods').glob('*napar*.jar'))
    if len(mods)!=1:raise ValueError('Expected exactly one installed NAPAR mod')
    if shutil.disk_usage(BASE).free<200_000_000:raise ValueError('Not enough room for a safe backup')
    mod=mods[0]
    test_env=os.environ.copy();test_env['PYTHONPATH']=str(stage/'src')
    print('Checking staged brain with no paid API requests...',flush=True)
    run(str(PYTHON),'-m','pytest',str(stage/'tests'),'-q','-p','no:cacheprovider','--basetemp',str(stage/('test-'+str(time.time_ns()))),cwd=stage,env=test_env)
    print('Staged tests passed. Saving Minecraft and stopping services for the update.',flush=True)
    guard={'required':True}
    def ensure_running():
        if guard['required']:
            subprocess.run(['systemctl','start','napar-next-brain','napar-next-game'],timeout=120,check=False)
    atexit.register(ensure_running)
    run('systemctl','stop','napar-next-game')
    run('systemctl','stop','napar-next-brain')
    backup=BASE/('backup-before-0.2-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime()))
    backup.mkdir(mode=0o700)
    files=[file for file in stage.rglob('*.py') if file.relative_to(stage).parts[0] in ('src','tests') or file.parent==stage]
    mapping={}
    for source in files:
        relative=source.relative_to(stage);destination=BRAIN/relative
        if destination.exists():
            copy=backup/'code'/relative;copy.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(destination,copy)
            mapping[str(destination)]=str(copy)
    shutil.copy2(BRAIN/'.env',backup/'environment');(backup/'environment').chmod(0o600)
    if database.exists():
        with sqlite3.connect(database) as source, sqlite3.connect(backup/'brain.db') as destination:source.backup(destination)
    shutil.copy2(mod,backup/'body.jar')
    runtime=GAME/'napar-runtime.json'
    if runtime.exists():shutil.copy2(runtime,backup/'presence.json')
    plan={'files':mapping,'new_files':[str(BRAIN/file.relative_to(stage)) for file in files if str(BRAIN/file.relative_to(stage)) not in mapping],
          'database':str(database),'mod':str(mod),'had_presence':(backup/'presence.json').exists()}
    (backup/'rollback.json').write_text(json.dumps(plan))
    rollback='''import json,os,shutil,sqlite3,subprocess,time
from pathlib import Path
b=Path(__file__).resolve().parent
p=json.loads((b/'rollback.json').read_text())
subprocess.run(['systemctl','stop','napar-next-game','napar-next-brain'],check=True,timeout=120)
failed=b/('failed-'+str(time.time_ns()));failed.mkdir(mode=0o700)
for target,source in p['files'].items():shutil.copy2(source,target)
for target in p['new_files']:
 t=Path(target)
 if t.exists():shutil.move(t,failed/(str(time.time_ns())+'-'+t.name))
shutil.copy2(b/'environment','/opt/napar-next/brain/.env')
database=Path(p['database'])
for suffix in ('','-wal','-shm'):
 t=Path(str(database)+suffix)
 if t.exists():shutil.move(t,failed/t.name)
if (b/'brain.db').exists():shutil.copy2(b/'brain.db',database)
shutil.copy2(b/'body.jar',p['mod'])
presence=Path('/opt/napar-next/server/napar-runtime.json')
if p['had_presence']:shutil.copy2(b/'presence.json',presence)
elif presence.exists():shutil.move(presence,failed/'presence.json')
import pwd
a=pwd.getpwnam('napar-next')
for target in [database,Path('/opt/napar-next/brain/.env'),Path(p['mod'])]:
 if target.exists():os.chown(target,a.pw_uid,a.pw_gid)
subprocess.run(['systemctl','start','napar-next-brain','napar-next-game'],check=True)
print('Previous working build, settings and memory restored. Failed-version data preserved in '+str(failed))
'''
    (backup/'rollback.py').write_text(rollback)
    try:
        prepare_presence(account)
        for source in files:
            destination=BRAIN/source.relative_to(stage);destination.parent.mkdir(parents=True,exist_ok=True)
            temporary=destination.with_suffix('.upgrade');temporary.write_bytes(source.read_bytes());os.chown(temporary,account.pw_uid,account.pw_gid);temporary.chmod(0o640);os.replace(temporary,destination)
        temporary=mod.with_suffix('.upgrade');temporary.write_bytes(body);os.chown(temporary,account.pw_uid,account.pw_gid);temporary.chmod(0o644);os.replace(temporary,mod)
        temporary=BRAIN/'.env.upgrade';shutil.copy2(BRAIN/'.env',temporary)
        for key,value in {'NAPAR_INITIATIVE_SECONDS':'60','NAPAR_MAX_STEPS':'8','NAPAR_ACTION_TIMEOUT':'35'}.items():set_key(temporary,key,value)
        os.chown(temporary,account.pw_uid,account.pw_gid);temporary.chmod(0o600);os.replace(temporary,BRAIN/'.env')
        started=time.time();run('systemctl','start','napar-next-brain','napar-next-game')
        headers={'Authorization':'Bearer '+values['NAPAR_BRIDGE_TOKEN']}
        until=time.monotonic()+110
        while time.monotonic()<until:
            try:
                with urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=2) as response:health=json.load(response)
                log=GAME/'logs/latest.log'
                if health.get('version')=='0.2.0' and health['connected'] and log.stat().st_mtime>=started and 'Napar runtime loaded.' in log.read_text(errors='replace'):
                    request=urllib.request.Request('http://127.0.0.1:8000/v1/status',headers=headers)
                    with urllib.request.urlopen(request,timeout=3) as response:status=json.load(response)
                    if all(tool in status['capabilities'] for tool in ('mine','craft','attack','sleep','follow_player')):
                        with socket.create_connection(('127.0.0.1',25565),timeout=2):pass
                        break
            except (OSError,ValueError,KeyError):pass
            time.sleep(1)
        else:raise TimeoutError('Updated services did not become ready')
        run('systemctl','is-active','napar-next-brain','napar-next-game')
        result={'version':'0.2.0','body_sha256':manifest['body_sha256'],'commit':args.ref,'health':health,'status':status,'backup':str(backup),'rollback':str(backup/'rollback.py')}
        (BASE/'upgrade-0.2-result.json').write_text(json.dumps(result,indent=2))
        print('READY: NAPAR 0.2, separate player restored, '+str(len(status['capabilities']))+' game tools. Daily budget unchanged.',flush=True)
        print('Rollback: '+str(PYTHON)+' '+str(backup/'rollback.py'),flush=True)
        guard['required']=False
    except BaseException:
        guard['required']=False
        print('Update failed. Restoring previous working version; data is preserved.',flush=True)
        run(str(PYTHON),str(backup/'rollback.py'))
        raise


if __name__=='__main__':main()
