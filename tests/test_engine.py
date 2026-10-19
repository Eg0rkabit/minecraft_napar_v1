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


async def test_signed_tool_continuation_is_returned_to_provider(runtime):
    wire = {'role': 'assistant', 'content': None, 'tool_calls': [{
        'id': 'signed', 'type': 'function',
        'function': {'name': 'recall', 'arguments': '{"query":"base"}'},
        'extra_content': {'google': {'thought_signature': 'opaque'}}}]}
    class SignedBackend:
        calls = 0
        async def decide(self, messages, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return Decision(tool_calls=[dict(id='signed', name='recall', arguments='{"query":"base"}')],
                                assistant_message=wire)
            assert messages[-2] == wire
            assert messages[-1]['tool_call_id'] == 'signed'
            return Decision('готов')
    runtime.backend = SignedBackend()
    assert (await runtime.handle('test'))['status'] == 'disabled'
    assert runtime.backend.calls == 2


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


async def test_unlimited_reasoning_can_finish_beyond_twenty_steps(runtime):
    runtime.settings.max_steps=0
    runtime.settings.max_calls_per_day=0
    runtime.settings.llm_backend='openai'
    class LongBackend:
        calls=0
        async def decide(self,*args,**kwargs):
            self.calls+=1
            if self.calls<=25:
                return Decision(tool_calls=[dict(id=str(self.calls),name='recall',arguments='{"query":"base'+str(self.calls)+'"}')])
            return Decision('finished')
    runtime.backend=LongBackend()
    result=await runtime.handle('long task',trigger='owner')
    assert result['status']=='completed'
    assert runtime.backend.calls==26
    assert runtime.store.usage()['calls']==26


async def test_payment_error_is_latched_and_survives_restart(runtime):
    import httpx
    from openai import APIStatusError
    runtime.settings.llm_backend='openai'
    class Rejected:
        calls=0
        async def decide(self,*args,**kwargs):
            self.calls+=1
            response=httpx.Response(402,request=httpx.Request('POST','https://example.test'))
            raise APIStatusError('payment required',response=response,body=None)
    runtime.backend=Rejected()
    assert (await runtime.handle('hello'))['status']=='billing_paused'
    assert (await runtime.handle('retry'))['status']=='billing_paused'
    assert runtime.backend.calls==1
    other=Store(runtime.settings.database)
    assert other.provider_pause()=='HTTP 402'
    other.close()


async def test_paid_disabled_never_calls_backend(runtime):
    runtime.settings.paid_enabled=False
    class Unexpected:
        async def decide(self,*args,**kwargs):raise AssertionError('Paid request attempted')
    runtime.backend=Unexpected()
    assert (await runtime.handle('hello'))['status']=='billing_paused'
    assert runtime.store.usage()['calls']==0


async def test_no_progress_loop_stops_after_three_identical_steps(runtime):
    runtime.settings.max_steps=0
    class Repeating:
        calls=0
        async def decide(self,*args,**kwargs):
            self.calls+=1
            return Decision(tool_calls=[dict(id=str(self.calls),name='recall',arguments='{"query":"same"}')])
    runtime.backend=Repeating()
    assert (await runtime.handle('go'))['status']=='failed'
    assert runtime.backend.calls==3


async def test_observe_loop_does_not_evade_guard_with_new_snapshot_sequence(runtime):
    from napar.protocol import Snapshot,Position
    runtime.settings.max_steps=0
    class Observing:
        calls=0
        async def decide(self,*args,**kwargs):
            self.calls+=1
            runtime.bridge.update(Snapshot(session_id=runtime.bridge.session_id,sequence=self.calls,
                position=Position(x=0,y=64,z=0),health=20,food=20,environment={'day_time':self.calls}))
            return Decision(tool_calls=[dict(id=str(self.calls),name='observe',arguments='{}')])
    runtime.backend=Observing()
    assert (await runtime.handle('look'))['status']=='failed'
    assert runtime.backend.calls==3
