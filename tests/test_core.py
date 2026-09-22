import asyncio

import pytest
from pydantic import SecretStr

from napar.bridge import Bridge
from napar.config import Settings
from napar.protocol import ActionResult, Connect, Position, Snapshot
from napar.storage import Store


def settings(tmp_path):
    return Settings(bridge_token=SecretStr('x' * 40), database=tmp_path / 'napar.db')


def snapshot(session_id, sequence=1):
    return Snapshot(session_id=session_id, sequence=sequence,
                    position=Position(x=0, y=64, z=0), health=20, food=20)


def test_memory_is_scoped_and_survives_restart(tmp_path):
    path = tmp_path / 'db.sqlite'
    store = Store(path)
    store.remember('world-a', key='home', content='birch house', kind='place', evidence='observed')
    assert store.recall('world-a', 'home')
    assert store.recall('world-b', 'home') == []
    store.close()
    reopened = Store(path)
    assert reopened.recall('world-a', 'birch')
    reopened.close()


@pytest.mark.asyncio
async def test_bridge_requires_fresh_state_and_accepts_result(tmp_path):
    bridge = Bridge(settings(tmp_path))
    session = bridge.connect(Connect(world_id='survival', agent_name='Napar', capabilities=['move_to']))
    sid = session['session_id']
    with pytest.raises(ValueError, match='stale'):
        await bridge.execute('move_to', {'x': 1, 'y': 64, 'z': 1})
    bridge.update(snapshot(sid))
    task = asyncio.create_task(bridge.execute('move_to', {'x': 1, 'y': 64, 'z': 1}))
    await asyncio.sleep(0)
    actions = bridge.poll(sid)['actions']
    assert len(actions) == 1
    action = actions[0]
    result = bridge.accept_result(ActionResult(session_id=sid, action_id=action['action_id'],
                                                status='succeeded', detail='arrived'))
    assert result['accepted']
    assert (await task)['status'] == 'succeeded'


def test_replaced_session_cannot_poll(tmp_path):
    bridge = Bridge(settings(tmp_path))
    old = bridge.connect(Connect(world_id='one', agent_name='Napar', capabilities=[]))['session_id']
    bridge.connect(Connect(world_id='two', agent_name='Napar', capabilities=[]))
    with pytest.raises(ValueError, match='reconnect'):
        bridge.poll(old)
