import time

import pytest
from fastapi.testclient import TestClient

from napar.app import create_app
from napar.bridge import Bridge
from napar.config import Settings
from napar.protocol import Connect, Snapshot, Position


def settings(tmp_path):
    return Settings(_env_file=None, bridge_token='x' * 40,
                    owner_name='Egor', database=tmp_path / 'db')


async def test_stop_works_after_state_expires(tmp_path):
    bridge = Bridge(settings(tmp_path))
    sid = bridge.connect(Connect(world_id='w', agent_name='Napar', capabilities=['stop']))['session_id']
    bridge.update(Snapshot(session_id=sid, sequence=1, position=Position(x=0,y=64,z=0), health=20, food=20))
    assert bridge.connected
    bridge.received_at = time.monotonic() - 100
    assert not bridge.connected
    generation = bridge.halt_generation
    assert (await bridge.execute('stop', {}))['status'] == 'requested'
    assert bridge.halt_generation == generation + 1


def test_event_is_queued_deduplicated_and_disconnect_invalidates_session(tmp_path):
    app = create_app(settings(tmp_path))
    headers = {'Authorization': 'Bearer ' + 'x' * 40}
    with TestClient(app) as client:
        sid = client.post('/v1/bridge/connect', headers=headers, json={
            'world_id':'w', 'agent_name':'Napar', 'capabilities':[]}).json()['session_id']
        event = {'session_id':sid, 'event_id':'chat-1', 'kind':'chat', 'sender':'Egor', 'text':'hello'}
        assert client.post('/v1/bridge/events', headers=headers, json=event).json()['status'] == 'queued'
        assert client.post('/v1/bridge/events', headers=headers, json=event).json()['status'] == 'duplicate'
        client.post('/v1/bridge/events', headers=headers, json={
            'session_id':sid, 'event_id':'disconnect', 'kind':'disconnected'})
        assert not client.get('/health').json()['connected']
        assert client.get('/v1/bridge/actions', headers=headers, params={'session_id':sid}).status_code == 409
