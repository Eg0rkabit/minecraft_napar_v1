from pydantic import SecretStr
from fastapi.testclient import TestClient

from napar.app import create_app
from napar.config import Settings


def test_health_is_small_and_protected_status(tmp_path):
    token = 't' * 40
    app = create_app(Settings(bridge_token=SecretStr(token), database=tmp_path / 'db.sqlite'))
    with TestClient(app) as client:
        assert client.get('/health').json()['ok'] is True
        assert client.get('/v1/status').status_code == 401
        assert client.get('/v1/status', headers={'Authorization': f'Bearer {token}'}).status_code == 200
