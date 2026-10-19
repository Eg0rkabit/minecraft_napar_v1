"""Replace only the Minecraft body, preserving brain configuration and provider pause."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile

BASE = Path('/opt/napar-next')
GAME = BASE/'server'


def run(*args):
    subprocess.run(args, check=True, timeout=120)


def main():
    ref = sys.argv[1]
    if os.geteuid() or len(ref) != 40 or any(c not in '0123456789abcdef' for c in ref):
        raise ValueError('Expected root and immutable release SHA')
    with urllib.request.urlopen(f'https://codeload.github.com/Eg0rkabit/minecraft_napar_v1/zip/{ref}', timeout=45) as response:
        payload = response.read(20_000_001)
    if len(payload) > 20_000_000:
        raise ValueError('Release too large')
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        prefix = archive.namelist()[0].split('/')[0]+'/'
        manifest = json.loads(archive.read(prefix+'deploy/release-0.2.json'))
        encoded = ''.join(archive.read(prefix+part).decode().strip() for part in manifest['parts'])
        body = base64.b64decode(encoded, validate=True)
    digest = hashlib.sha256(body).hexdigest()
    if digest != manifest['body_sha256']:
        raise ValueError('Body checksum mismatch')
    mods = list((GAME/'mods').glob('*napar*.jar'))
    if len(mods) != 1:
        raise ValueError('Expected exactly one body')
    mod = mods[0]
    backup = BASE/('backup-body-'+time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()))
    backup.mkdir(mode=0o700)
    shutil.copy2(mod, backup/'body.jar')
    (backup/'rollback.py').write_text(
        'import subprocess,shutil\n'
        'subprocess.run(["systemctl","stop","napar-next-game"],check=True,timeout=120)\n'
        f'shutil.copy2({str(backup/"body.jar")!r},{str(mod)!r})\n'
        'subprocess.run(["systemctl","start","napar-next-game"],check=True,timeout=120)\n')
    run('systemctl', 'stop', 'napar-next-game')
    try:
        temporary = mod.with_suffix('.upgrade')
        temporary.write_bytes(body)
        account = pwd.getpwnam('napar-next')
        os.chown(temporary, account.pw_uid, account.pw_gid)
        temporary.chmod(0o644)
        os.replace(temporary, mod)
        started = time.time()
        run('systemctl', 'start', 'napar-next-game')
        for _ in range(110):
            log = GAME/'logs/latest.log'
            if log.exists() and log.stat().st_mtime >= started and 'Napar runtime loaded.' in log.read_text(errors='replace'):
                break
            time.sleep(1)
        else:
            raise TimeoutError('Body did not become ready')
        run('systemctl', 'is-active', 'napar-next-game', 'napar-next-brain')
        result = dict(ready=True, body_sha256=digest, commit=ref, backup=str(backup),
                      brain_configuration_changed=False, paid_test_requests=0)
        (BASE/'body-update-result.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2), flush=True)
    except BaseException:
        run(str(BASE/'brain/.venv/bin/python'), str(backup/'rollback.py'))
        raise


if __name__ == '__main__':
    main()
