"""VPS-only reversible provider switch. Enter an existing key via hidden input."""
import asyncio
import getpass
import io
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
import zipfile

from dotenv import dotenv_values, set_key
from openai import APIError

BASE = Path('/opt/napar-next')
BRAIN = BASE/'brain'
MODEL = 'gemini-3.8-flash-free'
URL = 'https://direct.beatapi.io/v1'


def service(operation):
    subprocess.run(['systemctl', operation, 'napar-next-brain'], check=True, timeout=120)


async def probe(key, stage):
    sys.path.insert(0, str(stage/'src'))
    from napar.config import Settings
    from napar.llm import OpenAIBackend
    from napar.toolbox import LOCAL, REMOTE, strict_schema
    backend = OpenAIBackend(Settings(_env_file=None, bridge_token='x'*40,
        llm_api_key=key, llm_base_url=URL, llm_min_interval_seconds=61))
    backend.next_request = 0  # No generation has been sent with this free setup probe yet.
    try:
        models = await backend.client.models.list()
        if MODEL not in {item.id for item in models.data}:
            print('Requested model absent from listing. Checking the documented ID once.',flush=True)
            print('Gemini IDs:',[item.id[:120] for item in models.data if 'gemini' in item.id.lower()][:20],flush=True)
        tools = [{'type':'function','function':{'name':'napar_connection_check',
            'description':'Harmless connection test: confirm that tools work. No game action.',
            'parameters':{'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok']}}}]
        tools += [{'type':'function','function':{'name':name,'description':description,
            'strict':True,'parameters':strict_schema(schema.model_json_schema())}}
            for name,(schema,description) in (LOCAL|REMOTE).items()]
        messages = [{'role':'user','content':'Connection test only: call napar_connection_check with ok=true. Do not call any game tools. After its result, say only: Готов.'}]
        first = await backend.decide(messages, tools, model=MODEL, max_tokens=1536)
        if len(first.tool_calls)!=1 or first.tool_calls[0]['name']!='napar_connection_check':
            raise ValueError('Model did not complete the tool test; no configuration changed')
        call = first.tool_calls[0]
        if json.loads(call['arguments']) != {'ok':True}:
            raise ValueError('Tool test arguments invalid; no configuration changed')
        messages.append(first.assistant_message)
        messages.append({'role':'tool','tool_call_id':call['id'],'content':'{"ok":true}'})
        print('First free request succeeded. Waiting 61 seconds for the free-model window before tool-result check.',flush=True)
        second = await backend.decide(messages, tools, model=MODEL, max_tokens=1536)
        if second.tool_calls or not second.text.strip():
            raise ValueError('Model did not finish the tool-result round trip; no configuration changed')
        return {'calls':2,'tokens':first.tokens+second.tokens,'tool_roundtrip':True,'reply_available':True}
    finally:
        await backend.close()


def main():
    ref = sys.argv[1]
    if os.geteuid()!=0 or len(ref)!=40 or any(c not in '0123456789abcdef' for c in ref):
        raise ValueError('Expected root and immutable release SHA')
    stage = BASE/'releases'/('beatapi-'+ref[:12])
    stage.mkdir(parents=True,exist_ok=True)
    with urllib.request.urlopen(f'https://codeload.github.com/Eg0rkabit/minecraft_napar_v1/zip/{ref}',timeout=45) as response:
        payload=response.read(20_000_001)
    if len(payload)>20_000_000:
        raise ValueError('Release too large')
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        prefix=archive.namelist()[0].split('/')[0]+'/'
        for name in archive.namelist():
            relative=name.removeprefix(prefix)
            if not relative.startswith('src/napar/') or not relative.endswith('.py') or '..' in Path(relative).parts:
                continue
            destination=stage/relative
            destination.parent.mkdir(parents=True,exist_ok=True)
            destination.write_bytes(archive.read(name))
    key = getpass.getpass('BeatAPI key (hidden): ').strip()
    if not re.fullmatch(r'sk-[A-Za-z0-9_-]{20,}', key):
        raise ValueError('Invalid key format; configuration unchanged')
    checked = asyncio.run(probe(key, stage))
    values = dotenv_values(BRAIN/'.env')
    database = Path(values.get('NAPAR_DATABASE') or 'data/napar.db')
    if not database.is_absolute():
        database = BRAIN/database
    database = database.resolve()
    if not database.is_relative_to(BRAIN):
        raise ValueError('Unexpected database path')
    backup = BASE/('backup-beatapi-'+time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()))
    backup.mkdir(mode=0o700)
    account = pwd.getpwnam('napar-next')
    service('stop')
    pause = ''
    try:
        shutil.copy2(BRAIN/'.env', backup/'environment')
        (backup/'environment').chmod(0o600)
        for name in ('llm.py','engine.py','config.py'):
            shutil.copy2(BRAIN/'src/napar'/name, backup/name)
        with sqlite3.connect(database) as db:
            row=db.execute('SELECT value FROM runtime_flags WHERE key=?',('provider_pause',)).fetchone()
            pause=row[0] if row else ''
        (backup/'provider_pause.json').write_text(json.dumps(pause))
        temporary=BRAIN/'.env.switch'
        shutil.copy2(BRAIN/'.env',temporary)
        settings={'NAPAR_LLM_API_KEY':key,'NAPAR_LLM_BASE_URL':URL,'NAPAR_LLM_MODEL':MODEL,
                  'NAPAR_LLM_BACKEND':'openai','NAPAR_PAID_ENABLED':'true',
                  'NAPAR_INITIATIVE_SECONDS':'0','NAPAR_MAX_OUTPUT_TOKENS':'1536',
                  'NAPAR_LLM_MIN_INTERVAL_SECONDS':'61'}
        for name,value in settings.items():
            set_key(temporary,name,value)
        os.chown(temporary,account.pw_uid,account.pw_gid)
        temporary.chmod(0o600)
        os.replace(temporary,BRAIN/'.env')
        for name in ('llm.py','engine.py','config.py'):
            destination=BRAIN/'src/napar'/name
            shutil.copy2(stage/'src/napar'/name,destination)
            os.chown(destination,account.pw_uid,account.pw_gid)
        with sqlite3.connect(database) as db:
            db.execute('INSERT OR REPLACE INTO runtime_flags VALUES(?,?)',('provider_pause',''))
        service('start')
        headers={'Authorization':'Bearer '+values['NAPAR_BRIDGE_TOKEN']}
        for _ in range(30):
            try:
                with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8000/v1/status',headers=headers),timeout=2) as response:
                    status=json.load(response)
                if status['paid_enabled'] and status['limits']['initiative_seconds']==0:
                    break
            except (OSError,ValueError):
                pass
            time.sleep(1)
        else:
            raise TimeoutError('Brain did not become ready')
        result=dict(ready=True,model=MODEL,base_url=URL,background_reasoning=False,min_interval_seconds=61,
                    provider_pause=status['provider_pause'],connected=status['connected'],probe=checked,backup=str(backup))
        (BASE/'beatapi-result.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result,indent=2),flush=True)
    except BaseException:
        service('stop')
        if (backup/'environment').exists():
            shutil.copy2(backup/'environment',BRAIN/'.env')
            os.chown(BRAIN/'.env',account.pw_uid,account.pw_gid)
        for name in ('llm.py','engine.py','config.py'):
            if (backup/name).exists():
                shutil.copy2(backup/name,BRAIN/'src/napar'/name)
                os.chown(BRAIN/'src/napar'/name,account.pw_uid,account.pw_gid)
        with sqlite3.connect(database) as db:
            db.execute('INSERT OR REPLACE INTO runtime_flags VALUES(?,?)',('provider_pause',pause))
        service('start')
        raise


if __name__=='__main__':
    try:
        main()
    except APIError as exc:
        body=exc.body if isinstance(exc.body,dict) else {}
        error=body.get('error',body)
        code=error.get('code','') if isinstance(error,dict) else ''
        code=code if isinstance(code,str) and re.fullmatch(r'[a-zA-Z0-9_.-]{1,80}',code) else ''
        print('BeatAPI rejected the check. HTTP',getattr(exc,'status_code',None),
              'code',code,'No automatic retry; previous configuration preserved.',flush=True)
        raise SystemExit(1)
