"""VPS-only hidden key check; only api.openai.com receives the credential."""
import getpass
import json
import os
from pathlib import Path
import pwd
import re
import subprocess
import sys
import tempfile

import httpx
from dotenv import dotenv_values

ROOT = Path('/opt/napar-next/brain')
MODEL = 'gpt-4o-mini'
URL = 'https://api.openai.com/v1/chat/completions'


def main():
    if os.geteuid() != 0 or not sys.stdin.isatty():
        raise SystemExit('Run as root in an interactive terminal. No key was read.')
    config = ROOT / '.env'
    values = dict(dotenv_values(config))
    if len(values.get('NAPAR_BRIDGE_TOKEN') or '') < 32:
        raise SystemExit('Missing existing bridge configuration; unchanged.')
    print('Destination: api.openai.com only. Model:', MODEL, flush=True)
    print('One small paid tool-call test. Input stays hidden; no key in shell history.', flush=True)
    key = getpass.getpass('OpenAI API key (hidden; Enter alone cancels): ').strip()
    if not key:
        raise SystemExit('Cancelled; configuration unchanged.')
    if not re.fullmatch(r'sk-[A-Za-z0-9_-]{20,}', key):
        raise SystemExit('Unexpected key format; configuration unchanged.')
    payload = {
        'model': MODEL, 'messages': [{'role': 'user', 'content': 'Call connectivity_check.'}],
        'max_tokens': 32, 'parallel_tool_calls': False,
        'tools': [{'type': 'function', 'function': {
            'name': 'connectivity_check', 'description': 'Check API tool calling.',
            'strict': True, 'parameters': {'type': 'object', 'properties': {},
                                         'required': [], 'additionalProperties': False}}}],
        'tool_choice': {'type': 'function', 'function': {'name': 'connectivity_check'}},
    }
    try:
        with httpx.Client(timeout=35, follow_redirects=False) as client:
            response = client.post(URL, headers={'Authorization': 'Bearer ' + key}, json=payload)
    except httpx.HTTPError as exc:
        raise SystemExit('Network error: ' + type(exc).__name__ + '; configuration unchanged.') from None
    print('OpenAI HTTP:', response.status_code, flush=True)
    try:
        body = response.json()
    except ValueError:
        raise SystemExit('Non-JSON response; configuration unchanged.') from None
    if response.status_code != 200:
        error = body.get('error', {}) if isinstance(body, dict) else {}
        code = error.get('code') if isinstance(error, dict) else None
        known = {
            'unsupported_country_region_territory': 'Region is unsupported by OpenAI.',
            'insufficient_quota': 'API quota/balance is unavailable. ChatGPT billing is separate.',
            'invalid_api_key': 'API key was rejected.',
            'model_not_found': 'This account does not have access to the selected model.',
            'rate_limit_exceeded': 'API rate limit reached; try later.',
            'billing_hard_limit_reached': 'API billing limit reached.',
        }
        print(known.get(code, 'Request rejected; cause not confirmed by a recognized API code.'))
        if code in known:
            print('Error code:', code)
        raise SystemExit('Key NOT saved. Bot configuration unchanged.')
    try:
        calls = body['choices'][0]['message']['tool_calls']
        valid = any(c['function']['name'] == 'connectivity_check'
                    and json.loads(c['function']['arguments']) == {} for c in calls)
    except (KeyError, IndexError, TypeError, ValueError):
        valid = False
    if not valid:
        raise SystemExit('Tool-call check failed; key NOT saved, configuration unchanged.')
    values.update(NAPAR_LLM_BACKEND='openai', NAPAR_LLM_MODEL=MODEL,
                  NAPAR_LLM_BASE_URL='https://api.openai.com/v1', NAPAR_LLM_API_KEY=key)
    if any(not re.fullmatch(r'[A-Z0-9_]+', name) or value is None or
           any(c in value for c in '\r\n\x00') for name, value in values.items()):
        raise SystemExit('Unexpected configuration contents; unchanged.')
    account = pwd.getpwnam('napar-next')
    fd, name = tempfile.mkstemp(prefix='.env-checked-', dir=ROOT)
    try:
        os.fchmod(fd, 0o600)
        os.fchown(fd, account.pw_uid, account.pw_gid)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            for field, value in values.items():
                escaped = value.replace('\\', '\\\\').replace('"', '\\"')
                handle.write(field + '="' + escaped + '"\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, config)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    subprocess.run(['systemctl', 'restart', 'napar-next-brain'], check=True)
    subprocess.run(['systemctl', 'is-active', 'napar-next-brain'], check=True)
    print('Tool calling OK. Configuration saved with mode 0600. Brain restarted.')


if __name__ == '__main__':
    main()
