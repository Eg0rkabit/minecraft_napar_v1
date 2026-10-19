"""Enable the existing GPT provider for owner messages, with background reasoning off."""
from pathlib import Path
import compileall
import json
import os
import pwd
import shutil
import sqlite3
import subprocess
import time
import urllib.request
from dotenv import dotenv_values,set_key

base=Path('/opt/napar-next')
brain=base/'brain'
app=brain/'src/napar/app.py'
env=brain/'.env'
assert os.geteuid()==0 and env.is_file()
text=app.read_text()
needle='if (engine.paid_available() and bridge.connected and not inbox.full() and time.monotonic()-last_incident>=60'
replacement='if (settings.initiative_seconds and engine.paid_available() and bridge.connected and not inbox.full() and time.monotonic()-last_incident>=60'
assert text.count(needle)==1 or replacement in text,'Unexpected application version'
updated=text.replace(needle,replacement)
if "'observation':" not in updated:
    updated=updated.replace("            'paid_enabled':settings.paid_enabled,", "            'observation':bridge.observe() if bridge.connected else None,\n            'paid_enabled':settings.paid_enabled,")
compile(updated,str(app),'exec')
backup=base/('backup-before-enable-chat-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime()))
backup.mkdir(mode=0o700)
shutil.copy2(app,backup/'app.py');shutil.copy2(env,backup/'environment')
subprocess.run(['systemctl','stop','napar-next-brain'],check=True,timeout=120)
values=dotenv_values(env)
database=Path(values.get('NAPAR_DATABASE') or 'data/napar.db')
if not database.is_absolute():database=brain/database
db=sqlite3.connect(database)
row=db.execute('SELECT value FROM runtime_flags WHERE key=?',('provider_pause',)).fetchone()
old_pause=row[0] if row else None
(backup/'pause.json').write_text(json.dumps(old_pause))
try:
    app.write_text(updated)
    for key,value in {'NAPAR_LLM_BACKEND':'openai','NAPAR_PAID_ENABLED':'true','NAPAR_INITIATIVE_SECONDS':'0'}.items():set_key(env,key,value)
    account=pwd.getpwnam("napar-next")
    os.chown(env,account.pw_uid,account.pw_gid);env.chmod(0o600)
    db.execute('INSERT OR REPLACE INTO runtime_flags VALUES(?,?)',('provider_pause',''));db.commit()
    subprocess.run(['systemctl','start','napar-next-brain'],check=True,timeout=120)
    headers={'Authorization':'Bearer '+values['NAPAR_BRIDGE_TOKEN']}
    until=time.monotonic()+25
    while time.monotonic()<until:
        try:
            with urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=2) as response:health=json.load(response)
            request=urllib.request.Request('http://127.0.0.1:8000/v1/status',headers=headers)
            with urllib.request.urlopen(request,timeout=2) as response:status=json.load(response)
            if health['llm']=='openai' and status['paid_enabled'] and not status['provider_pause'] and status['limits']['initiative_seconds']==0:break
        except (OSError,ValueError,KeyError):pass
        time.sleep(.5)
    else:raise RuntimeError('Enabled brain failed its configuration check')
    result={'enabled':True,'model':values['NAPAR_LLM_MODEL'],'background_reasoning':False,
            'provider_pause':status['provider_pause'],'usage':status['usage'],'backup':str(backup),
            'paid_test_requests':0}
    (base/'enabled-owner-chat-result.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))
    print('READY: GPT enabled for owner chat; free controls unchanged; no model test request sent.')
except BaseException:
    subprocess.run(['systemctl','stop','napar-next-brain'],check=True,timeout=120)
    shutil.copy2(backup/'app.py',app);shutil.copy2(backup/'environment',env)
    account=pwd.getpwnam('napar-next');os.chown(env,account.pw_uid,account.pw_gid);env.chmod(0o600)
    if old_pause is None:db.execute('DELETE FROM runtime_flags WHERE key=?',('provider_pause',))
    else:db.execute('INSERT OR REPLACE INTO runtime_flags VALUES(?,?)',('provider_pause',old_pause))
    db.commit()
    subprocess.run(['systemctl','start','napar-next-brain'],check=True,timeout=120)
    raise
finally:db.close()

