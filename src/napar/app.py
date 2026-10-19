from contextlib import asynccontextmanager
from collections import OrderedDict
from secrets import compare_digest
import asyncio
import time
from contextlib import suppress

from fastapi import Depends, FastAPI, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .bridge import Bridge
from .config import Settings
from .engine import Engine
from .llm import make_backend
from .protocol import ActionResult, ChatMessage, Connect, GameEvent, Snapshot
from .storage import Store
from .toolbox import Toolbox
from .quick_commands import parse_control


def create_app(settings: Settings | None = None):
    settings = settings or Settings()
    store = Store(settings.database)
    bridge = Bridge(settings)
    toolbox = Toolbox(bridge, store)
    engine = Engine(settings, store, bridge, toolbox, make_backend(settings))
    bearer = HTTPBearer(auto_error=False)
    seen_events = OrderedDict()
    inbox = asyncio.Queue(maxsize=32)
    controls = asyncio.Queue(maxsize=8)
    last_background = 0.0
    last_incident = 0.0

    async def process_events():
        while True:
            event = await inbox.get()
            try:
                while engine.busy:
                    await asyncio.sleep(.05)
                if event.session_id != bridge.session_id:
                    continue
                result = await engine.handle(event.text, trigger='chat' if event.kind=='chat' else event.kind)
                if result['status'] in ('failed', 'step_limit', 'billing_paused') and 'say' in bridge.capabilities:
                    await bridge.execute('say', {'message': result['message'][:240]})
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                store.audit(bridge.world_id or 'unknown', 'worker_error', {'type': type(exc).__name__})
            finally:
                inbox.task_done()

    async def process_controls():
        while True:
            event=await controls.get()
            try:
                if event.session_id!=bridge.session_id:
                    continue
                world=bridge.world_id
                store.conversation(world,'user',event.text)
                control=parse_control(event.text)
                if control in ('stay','auto_leave'):
                    store.presence(world,'stay' if control=='stay' else 'auto')
                    reply='Хорошо, останусь на сервере.' if control=='stay' else 'Ладно, если дел нет — выйду через пару минут после тебя.'
                    store.conversation(world,'assistant',reply)
                    if 'say' in bridge.capabilities:await bridge.execute('say',{'message':reply})
                    continue
                result=await bridge.execute('follow_player',{'player':settings.owner_name})
                reply='Ага, иду за тобой.' if result.get('status')=='succeeded' else 'Не вижу тебя или не могу начать идти. Подойди поближе.'
                if result.get('status')=='cancelled':
                    continue
                store.audit(world,'local_control',{'control':'follow','status':result.get('status')})
                store.conversation(world,'assistant',reply)
                if 'say' in bridge.capabilities:
                    await bridge.execute('say',{'message':reply})
            except asyncio.CancelledError:
                raise
            except ValueError:
                pass
            finally:
                controls.task_done()

    async def continue_goals():
        nonlocal last_background
        # Idle polling is local and free. Paid reasoning requires a real goal/event.
        while True:
            await asyncio.sleep(5)
            if not engine.paid_available() or not settings.initiative_seconds or engine.busy or not inbox.empty() or not bridge.connected:
                continue
            world=bridge.world_id
            mode=store.autonomy(world)
            if mode=='wait' or time.monotonic()-last_background<settings.initiative_seconds:
                continue
            active=[goal for goal in store.goals(world) if goal['status']=='active' or goal['summary'].startswith('[revalidate]')]
            if not active and mode!='expanded':
                continue
            if (settings.max_calls_per_day and store.usage()['calls']>=settings.max_calls_per_day//2) or bridge.observe().get('activity','idle')!='idle':
                continue
            last_background=time.monotonic()
            await engine.handle('Продолжи активную цель по свежему состоянию. Если цели нет, выбери безопасное исследование рядом; не повторяй предложения в чат.',trigger='initiative')

    def auth(credentials: HTTPAuthorizationCredentials | None = Security(bearer)):
        token = credentials.credentials if credentials else ''
        if not compare_digest(token.encode(), settings.bridge_token.get_secret_value().encode()):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Unauthorized')

    @asynccontextmanager
    async def lifespan(_app):
        worker = asyncio.create_task(process_events())
        controller = asyncio.create_task(process_controls())
        background = asyncio.create_task(continue_goals())
        yield
        engine.stop('shutdown')
        worker.cancel()
        controller.cancel()
        background.cancel()
        with suppress(asyncio.CancelledError):
            await worker
        with suppress(asyncio.CancelledError):
            await controller
        with suppress(asyncio.CancelledError):
            await background
        if hasattr(engine.backend, 'close'):
            await engine.backend.close()
        store.close()

    app = FastAPI(title='Napar brain', version='0.2.0', lifespan=lifespan)
    app.state.engine, app.state.bridge, app.state.store = engine, bridge, store

    @app.get('/health')
    async def health():
        return {'ok': True, 'version':'0.2.0','connected': bridge.connected, 'llm': settings.llm_backend}

    @app.get('/v1/status', dependencies=[Depends(auth)])
    async def status_view():
        return {
            'connected': bridge.connected, 'world_id': bridge.world_id,
            'session_id': bridge.session_id, 'usage': store.usage(), 'busy': engine.busy,
            'presence_mode':store.presence(bridge.world_id),
            'paid_enabled':settings.paid_enabled, 'provider_pause':store.provider_pause(),
            'capabilities':sorted(bridge.capabilities), 'autonomy':store.autonomy(bridge.world_id) if bridge.world_id else 'wait',
            'limits':{'daily_calls':settings.max_calls_per_day,'steps':settings.max_steps,'initiative_seconds':settings.initiative_seconds},
        }

    @app.post('/v1/bridge/connect', dependencies=[Depends(auth)])
    async def connect(request: Connect):
        engine.stop('connection')
        seen_events.clear()
        return bridge.connect(request)

    @app.post('/v1/bridge/state', dependencies=[Depends(auth)])
    async def state(snapshot: Snapshot):
        try:
            bridge.update(snapshot)
            return {'accepted': True}
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get('/v1/bridge/actions', dependencies=[Depends(auth)])
    async def actions(session_id: str):
        try:
            result=bridge.poll(session_id)
            result['presence']={'stay':store.presence(bridge.world_id)=='stay',
                'work_pending':engine.busy or any(g['status']=='active' for g in store.goals(bridge.world_id))}
            return result
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post('/v1/bridge/results', dependencies=[Depends(auth)])
    async def results(result: ActionResult):
        try:
            return bridge.accept_result(result)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post('/v1/bridge/events', dependencies=[Depends(auth)])
    async def event(event: GameEvent):
        nonlocal last_background, last_incident
        if event.session_id != bridge.session_id:
            raise HTTPException(409, 'Unknown session')
        if event.event_id in seen_events:
            return {'status': 'duplicate'}
        owner_chat = event.kind == 'chat' and settings.owner_name and event.sender == settings.owner_name
        control=parse_control(event.text) if owner_chat else None
        if control in ('stop','follow'):
            engine.stop()
            while not inbox.empty():
                inbox.get_nowait()
                inbox.task_done()
            while not controls.empty():
                controls.get_nowait()
                controls.task_done()
            seen_events[event.event_id]=True
            if control=='stop':
                return {'status': 'stopped'}
            controls.put_nowait(event)
            return {'status':'local_queued'}
        if control in ('stay','auto_leave'):
            if controls.full():raise HTTPException(429,'Control queue full')
            seen_events[event.event_id]=True
            controls.put_nowait(event)
            return {'status':'local_queued'}
        if owner_chat:
            if inbox.full():
                raise HTTPException(429, 'Event queue full; retry', headers={'Retry-After': '1'})
            inbox.put_nowait(event)
            last_background=time.monotonic()
        seen_events[event.event_id] = True
        if len(seen_events) > 1000:
            seen_events.popitem(last=False)
        store.audit(bridge.world_id or 'unknown', 'event', event.model_dump())
        if event.kind in ('death', 'disconnected', 'danger'):
            engine.stop(event.kind)
        if event.kind in ('danger','death','stuck'):
            store.remember(bridge.world_id or 'unknown',key='last_incident',content=event.text or event.kind,
                           kind='experience',evidence=event.event_id,truth='observation',confidence=.9,source='game_event')
            # At most one background incident per minute; half of the daily cap stays for owner chat.
            if (engine.paid_available() and bridge.connected and not inbox.full() and time.monotonic()-last_incident>=60
                    and (not settings.max_calls_per_day or store.usage()['calls']<settings.max_calls_per_day//2)):
                inbox.put_nowait(event)
                last_incident=time.monotonic()
                last_background=time.monotonic()
        if event.kind == 'disconnected':
            bridge.disconnect()
        if owner_chat:
            return {'status': 'queued'}
        return {'status': 'accepted'}

    @app.post('/v1/chat', dependencies=[Depends(auth)])
    async def chat(message: ChatMessage):
        return await engine.handle(message.text, trigger='owner')

    @app.post('/v1/stop', dependencies=[Depends(auth)])
    async def stop():
        engine.stop()
        return {'stopped': True}

    return app

