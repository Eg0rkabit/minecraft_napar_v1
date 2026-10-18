"""Systemd launcher with a local, private FIFO for Minecraft console commands."""
import os
from pathlib import Path
import select
import signal
import subprocess
import time

from dotenv import dotenv_values


def main():
    brain = Path('/opt/napar-next/brain')
    server = Path('/opt/napar-next/server')
    pipe = Path('/run/napar-next-game/console')
    values = dotenv_values(brain/'.env')
    env = os.environ.copy()
    env.update(NAPAR_BRIDGE_TOKEN=values['NAPAR_BRIDGE_TOKEN'],
               NAPAR_OWNER_NAME=values['NAPAR_OWNER_NAME'],
               NAPAR_WORLD_ID=(server/'napar-world-id.txt').read_text().strip())
    if not pipe.exists():
        os.mkfifo(pipe, 0o600)
    fd = os.open(pipe, os.O_RDWR | os.O_NONBLOCK)
    process = subprocess.Popen(['java','-Xms512M','-Xmx2G','-jar',
        str(server/'fabric-server-launch.jar'),'nogui'],cwd=server,env=env,
        stdin=subprocess.PIPE,text=True)
    stopping = False
    def stop(_sig, _frame):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    pending = b''
    try:
        while process.poll() is None and not stopping:
            if select.select([fd],[],[],0.25)[0]:
                pending += os.read(fd,8192)
                if len(pending) > 65536:
                    pending = b''
                while b'\n' in pending:
                    line,pending = pending.split(b'\n',1)
                    command = line.decode('utf-8',errors='strict').strip()
                    if command:
                        process.stdin.write(command+'\n')
                        process.stdin.flush()
        if process.poll() is None:
            process.stdin.write('stop\n')
            process.stdin.flush()
            try:
                process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=10)
        raise SystemExit(process.returncode)
    finally:
        os.close(fd)
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == '__main__':
    main()
