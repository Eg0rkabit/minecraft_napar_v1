"""Exercise the isolated Minecraft instance, without an LLM or any key output."""
from pathlib import Path
import json
import subprocess
import time
import urllib.request

BASE = Path('/opt/napar-next')
LOG = BASE / 'game-smoke.log'


def wait_for(check, seconds=75):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return
        if process.poll() is not None:
            raise RuntimeError('Test server exited; see game-smoke.log')
        time.sleep(0.5)
    raise TimeoutError('Test server check timed out; see game-smoke.log')


def command(text):
    process.stdin.write(text + '\n')
    process.stdin.flush()


def contains(text):
    return text in LOG.read_text(errors='replace')


def connected():
    try:
        with urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3) as response:
            return json.load(response)['connected'] is True
    except (OSError, ValueError, KeyError):
        return False


assert (BASE / 'server/eula.txt').read_text().strip() == 'eula=true'
assert 'server-ip=127.0.0.1' in (BASE / 'server/server.properties').read_text()
subprocess.run(['systemctl', 'is-active', '--quiet', 'minecraft'], check=True)
print('Starting isolated Minecraft smoke test; existing service stays active.', flush=True)
with LOG.open('w') as output:
    process = subprocess.Popen(
        ['runuser', '-u', 'napar-next', '--', str(BASE / 'brain/.venv/bin/python'),
         str(BASE / 'brain/deploy/run_minecraft.py'), str(BASE / 'server'), '--memory', '1G'],
        stdin=subprocess.PIPE, stdout=output, stderr=subprocess.STDOUT, text=True)
    try:
        wait_for(lambda: contains('Napar runtime loaded.'))
        command('forceload add 0 0')
        command('fill 0 249 0 10 249 10 minecraft:stone')
        wait_for(lambda: contains('Successfully filled'))
        command('execute positioned 0.5 250 0.5 run napar spawn')
        wait_for(lambda: contains('Napar joined the game'))
        command('napar status')
        wait_for(lambda: contains('Napar is present (server FakePlayer).'))
        wait_for(connected, seconds=25)
        print('PASS: Napar spawned as a separate FakePlayer; brain receives live snapshots.', flush=True)
        command('napar step 10')
        time.sleep(2)
        command('napar stop')
        command('data get entity Napar Pos')
        wait_for(lambda: contains('Napar has the following entity data'))
        print('PASS: bounded step and stop commands accepted; position recorded in log.', flush=True)
    finally:
        if process.poll() is None:
            command('stop')
            try:
                process.wait(timeout=45)
            except subprocess.TimeoutExpired:
                process.terminate()
                raise RuntimeError('Test shutdown timed out; inspect processes before restarting.')
subprocess.run(['systemctl', 'is-active', '--quiet', 'minecraft'], check=True)
print('PASS: test server stopped; existing Minecraft remains active.', flush=True)
