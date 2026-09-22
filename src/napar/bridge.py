"""One companion connection. Delivery is at most once; results are idempotent."""
import asyncio
import time
from collections import OrderedDict
from uuid import uuid4

from .protocol import ActionResult, Connect, Snapshot


class Bridge:
    def __init__(self, settings):
        self.settings = settings
        self.session_id = None
        self.world_id = None
        self.capabilities = set()
        self.snapshot = None
        self.received_at = 0.0
        self.pending = OrderedDict()
        self.results = OrderedDict()
        self.halt_generation = 0

    def connect(self, request: Connect):
        self.halt('New connection')
        self.session_id = str(uuid4())
        self.world_id = request.world_id
        self.capabilities = set(request.capabilities)
        self.snapshot = None
        self.results.clear()
        return {'session_id': self.session_id, 'protocol_version': 1,
                'heartbeat_seconds': 1, 'disconnect_stop_seconds': 3}

    def check_session(self, session_id):
        if not self.session_id or session_id != self.session_id:
            raise ValueError('Unknown or replaced session; reconnect')

    def update(self, snapshot: Snapshot):
        self.check_session(snapshot.session_id)
        if self.snapshot and snapshot.sequence <= self.snapshot.sequence:
            raise ValueError('Snapshot sequence must increase')
        self.snapshot = snapshot
        self.received_at = time.monotonic()

    def observe(self):
        if not self.snapshot or time.monotonic() - self.received_at > self.settings.state_max_age:
            raise ValueError('World state is missing or stale; movement is disabled')
        return self.snapshot.model_dump()

    def halt(self, reason='Stopped by owner'):
        self.halt_generation += 1
        for action in list(self.pending.values()):
            if not action['future'].done():
                action['future'].set_result({'status': 'cancelled', 'detail': reason})
        self.pending.clear()

    async def execute(self, name, arguments):
        state = self.observe()
        if name not in self.capabilities:
            raise ValueError(f'Adapter does not support {name}')
        if name == 'move_to':
            origin = state['position']
            distance = sum((arguments[k] - origin[k]) ** 2 for k in ('x', 'y', 'z')) ** 0.5
            if distance > 64:
                raise ValueError('Move target exceeds 64 blocks; inspect and use shorter waypoints')
        if name == 'stop':
            self.halt('Model requested stop')
            return {'status': 'requested', 'detail': 'Stop generation changed; awaiting adapter polling'}
        action_id = str(uuid4())
        future = asyncio.get_running_loop().create_future()
        action = {'action_id': action_id, 'session_id': self.session_id, 'tool': name,
                  'arguments': arguments, 'ttl_seconds': self.settings.action_timeout,
                  'expires': time.monotonic() + self.settings.action_timeout,
                  'future': future, 'delivered': False}
        self.pending[action_id] = action
        try:
            result = await asyncio.wait_for(future, self.settings.action_timeout)
            return {'action_id': action_id, **result}
        except TimeoutError:
            self.halt('Action timed out')
            return {'action_id': action_id, 'status': 'failed', 'detail': 'Adapter result timed out; stop requested'}
        finally:
            self.pending.pop(action_id, None)

    def poll(self, session_id):
        self.check_session(session_id)
        try:
            self.observe()
        except ValueError:
            if self.pending:
                self.halt('World state is stale')
            return {'halt_generation': self.halt_generation, 'actions': [], 'stop': True}
        actions = []
        for entry in self.pending.values():
            if not entry['delivered'] and entry['expires'] > time.monotonic():
                entry['delivered'] = True
                actions.append({k: entry[k] for k in ('action_id', 'session_id', 'tool', 'arguments')}
                               | {'ttl_seconds': max(0, entry['expires'] - time.monotonic())})
        return {'halt_generation': self.halt_generation, 'actions': actions, 'stop': False}

    def accept_result(self, result: ActionResult):
        self.check_session(result.session_id)
        if result.action_id in self.results:
            if self.results[result.action_id] != result.model_dump():
                raise ValueError('Conflicting duplicate result')
            return {'accepted': True, 'duplicate': True}
        entry = self.pending.get(result.action_id)
        if not entry or not entry['delivered'] or entry['expires'] <= time.monotonic():
            raise ValueError('Action was not delivered, has expired or was cancelled')
        self.results[result.action_id] = result.model_dump()
        while len(self.results) > 100:
            self.results.popitem(last=False)
        if not entry['future'].done():
            entry['future'].set_result({'status': result.status, 'detail': result.detail})
        return {'accepted': True, 'duplicate': False}
