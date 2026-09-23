"""Run on the VPS from /opt/napar. Secrets are entered without echo or shell history."""
import getpass
import os
import re
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent.parent
    path = root / '.env'
    api_key = getpass.getpass('OpenAI API key (hidden; empty = disabled): ').strip()
    if api_key and not re.fullmatch(r'sk-[A-Za-z0-9_-]{20,}', api_key):
        raise SystemExit('Invalid key characters; configuration unchanged')
    owner = input('Minecraft owner nickname (empty = local API only): ').strip()
    if owner and not re.fullmatch(r'[A-Za-z0-9_]{1,16}', owner):
        raise SystemExit('Invalid nickname; configuration unchanged')
    if path.exists():
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup = root / ('.env.backup-' + stamp)
        shutil.copy2(path, backup)
        backup.chmod(0o600)
    values = {
        'NAPAR_BRIDGE_TOKEN': secrets.token_urlsafe(32),
        'NAPAR_DATABASE': 'data/napar.db',
        'NAPAR_LLM_BACKEND': 'openai' if api_key else 'disabled',
        'NAPAR_LLM_MODEL': 'gpt-4o-mini',
        'NAPAR_LLM_BASE_URL': 'https://api.openai.com/v1',
        'NAPAR_LLM_API_KEY': api_key,
        'NAPAR_OWNER_NAME': owner,
        'NAPAR_MAX_CALLS_PER_DAY': '120',
        'NAPAR_MAX_STEPS': '6',
        'NAPAR_MAX_OUTPUT_TOKENS': '700',
        'NAPAR_INITIATIVE_SECONDS': '0',
    }
    fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write(''.join(f'{k}={v}\n' for k, v in values.items()))
    path.chmod(0o600)
    print('Configuration saved. Backend:', values['NAPAR_LLM_BACKEND'], '; key length:', len(api_key))


if __name__ == '__main__':
    main()
