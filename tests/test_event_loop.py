import asyncio
import json

from fastapi.testclient import TestClient
from napar.app import create_app
from napar.config import Settings
from napar.llm import Decision


def test_real_http_events_are_serialized_and_owner_stop_bypasses_queue(tmp_path):
    app = create_app(Settings(_env_file=None, bridge_token='x'*40, owner_name='Egor', database=tmp_path/'db'))
    entered = []
    class Backend:
        async def decide(self, messages, *args, **kwargs):
            entered.append(json.loads(messages[1]['content'])['message'])
            await asyncio.sleep(.1)
            return Decision('ok')
    app.state.engine.backend = Backend()
    headers={'Authorization':'Bearer '+'x'*40}
    with TestClient(app) as client:
        sid=client.post('/v1/bridge/connect',headers=headers,json=dict(world_id='w',agent_name='Napar',capabilities=[])).json()['session_id']
        for i in range(3):
            assert client.post('/v1/bridge/events',headers=headers,json=dict(session_id=sid,event_id=str(i),kind='chat',sender='Egor',text=str(i))).json()['status']=='queued'
        import time
        until=time.monotonic()+3
        while len(entered)<3 and time.monotonic()<until: time.sleep(.02)
        assert entered==['0','1','2']
        assert client.post('/v1/bridge/events',headers=headers,json=dict(session_id=sid,event_id='stop',kind='chat',sender='Egor',text='стоп')).json()['status']=='stopped'


def test_all_tool_object_properties_are_required(tmp_path):
    app=create_app(Settings(_env_file=None,bridge_token='x'*40,database=tmp_path/'db'))
    specs=app.state.engine.toolbox.specs()
    for tool in specs:
        schema=tool['function']['parameters']
        assert schema['additionalProperties'] is False
        assert set(schema['required'])==set(schema['properties'])
    app.state.store.close()
