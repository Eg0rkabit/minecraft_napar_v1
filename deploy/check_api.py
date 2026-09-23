"""One read-only authenticated GET to OpenAI; no generation, no key in output."""
import httpx
from napar.config import Settings

s = Settings()
if not s.llm_api_key.get_secret_value():
    raise SystemExit('API key is not configured')
try:
    with httpx.Client(timeout=15) as client:
        response = client.get(s.llm_base_url.rstrip('/') + '/models/' + s.llm_model,
                              headers={'Authorization': 'Bearer ' + s.llm_api_key.get_secret_value()})
    print('OpenAI HTTP:', response.status_code)
    if response.status_code == 200:
        print('Model access OK:', s.llm_model)
    else:
        try:
            error = response.json().get('error', {})
            print('Error code:', error.get('code', 'unknown'))
            print('Error type:', error.get('type', 'unknown'))
        except (ValueError, AttributeError):
            print('Response was not an API JSON error')
except httpx.HTTPError as exc:
    print('Network error:', type(exc).__name__)
