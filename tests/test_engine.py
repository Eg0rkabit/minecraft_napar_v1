import asyncio
import pytest

from napar.bridge import Bridge
from napar.config import Settings
from napar.engine import Engine
from napar.llm import Decision, DisabledBackend
from napar.protocol import Connect
from napar.storage import Store
from napar.toolbox import Toolbox


@pytest.fixture
def runtime(tmp_path):
    s = Settings(_env_file=None, bridge_token='x' * 40, database=tmp_path/'test.db')
    store = Store(s.database)
    bridge = Bridge(s)
    bridge.connect(Connect(world_id='world-a', agent_name='test', capabilities=[]))
    engine = Engine(s, store, bridge, Toolbox(bridge, store), DisabledBackend())
    yield engine
    store.close()


async def test_disabled_does_not_charge_budget(runtime):
    result = await runtime.handle('hello')
    assert result['status'] == 'disabled'
    assert runtime.store.usage()['calls'] == 0


async def test_stop_during_model_response_prevents_tool_execution(runtime):
    started, release = asyncio.Event(), asyncio.Event()
    class DelayedBackend:
        async def decide(self, *args, **kwargs):
            started.set()
            await release.wait()
            return Decision(tool_calls=[{'id': '1', 'name': 'create_goal',
                'arguments': '{"description":"late","success_condition":"never"}'}])
    runtime.backend = DelayedBackend()
    task = asyncio.create_task(runtime.handle('go'))
    await started.wait()
    runtime.stop()
    release.set()
    assert (await task)['status'] == 'cancelled'
    assert runtime.store.goals('world-a') == []


async def test_reconnect_during_response_does_not_write_to_new_world(runtime):
    class ReconnectingBackend:
        async def decide(self, *args, **kwargs):
            runtime.bridge.connect(Connect(world_id='world-b', agent_name='test', capabilities=[]))
            return Decision(tool_calls=[{'id': '1', 'name': 'create_goal',
                'arguments': '{"description":"old world task","success_condition":"never"}'}])
    runtime.backend = ReconnectingBackend()
    assert (await runtime.handle('go'))['status'] == 'cancelled'
    assert runtime.store.goals('world-b') == []


def test_budget_persists_and_goals_pause_after_restart(tmp_path):
    path = tmp_path/'db'
    store = Store(path)
    store.create_goal('world', 'find shelter', 'indoors')
    store.reserve_call(1)
    store.close()
    store = Store(path)
    assert store.goals('world')[0]['status'] == 'paused'
    with pytest.raises(ValueError, match='Daily'):
        store.reserve_call(1)
    store.close()
