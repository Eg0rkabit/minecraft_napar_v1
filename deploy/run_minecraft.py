"""Launch an existing Fabric server with bridge settings from the brain's .env."""
import argparse
import os
from pathlib import Path
import subprocess
from dotenv import dotenv_values

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('server_directory', type=Path)
    parser.add_argument('--jar', default='fabric-server-launch.jar')
    parser.add_argument('--memory', default='2G', choices=['1G','2G','3G','4G'])
    args=parser.parse_args()
    root=Path(__file__).resolve().parent.parent
    directory=args.server_directory.resolve(strict=True)
    jar=(directory/args.jar).resolve(strict=True)
    if jar.parent != directory:
        raise SystemExit('Server jar must be directly in the server directory')
    values=dotenv_values(root/'.env')
    token=values.get('NAPAR_BRIDGE_TOKEN') or ''
    if len(token)<32 or not values.get('NAPAR_OWNER_NAME'):
        raise SystemExit('Configure bridge token and owner in .env first')
    identity=directory/'napar-world-id.txt'
    if not identity.exists():
        from uuid import uuid4
        identity.write_text(str(uuid4()),encoding='utf-8')
    env=os.environ.copy()
    env.update(NAPAR_BRIDGE_TOKEN=token,NAPAR_OWNER_NAME=values['NAPAR_OWNER_NAME'],
               NAPAR_WORLD_ID=identity.read_text(encoding='utf-8').strip())
    raise SystemExit(subprocess.call(['java',f'-Xmx{args.memory}','-jar',str(jar),'nogui'],cwd=directory,env=env))

if __name__=='__main__': main()
