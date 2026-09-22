from contextlib import asynccontextmanager
from secrets import compare_digest

from fastapi import Depends, FastAPI, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .bridge import Bridge
from .config import Settings
from .engine import Engine
from .llm import make_backend
from .protocol import ActionResult, ChatMessage, Connect, GameEvent, Snapshot
from .storage import Store
from .toolbox import Toolbox


def create_app(settings: Settings | None = None):
    settings = settings or Settings()
    store = Store(settings.database)
    bridge = Bridge(settings)
    toolbox = Toolbox(bridge, store)
    engine = Engine(settings, store, bridge, toolbox, make_backend(settings))
    bearer = HTTPBearer(auto_error=False)

    def auth(credentials: HTTPAuthorizationCredentials | None = Security(bearer)):
        token = credentials.credentials if credentials else ''
        if not compare_digest(token, settings.bridge_token.get_secret_value()):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Unauthorized')

    @asynccontextmanager
    async def lifespan(_app):
        yield
        store.close()

    app = FastAPI(title='Napar brain', version='0.1.0', lifespan=lifespan)
    app.state.engine, app.state.bridge, app.state.store = engine, bridge, store

    @app.get('/health')
    async def health():
        return {'ok': True, 'connected': bool(bridge.session_id), 'llm': settings.llm_backend}

    @app.get('/v1/status', dependencies=[Depends(auth)])
    async def status_view():
        return {
            'connected': bool(bridge.session_id), 'world_id': bridge.world_id,
            'session_id': bridge.session_id, 'usage': store.usage(), 'busy': engine.busy,
        }

    @app.post('/v1/bridge/connect', dependencies=[Depends(auth)])
    async def connect(request: Connect):
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
            return bridge.poll(session_id)
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
        if event.session_id != bridge.session_id:
            raise HTTPException(409, 'Unknown session')
        store.audit(bridge.world_id or 'unknown', 'event', event.model_dump())
        if event.kind == 'chat' and (not settings.owner_name or event.sender == settings.owner_name):
            return await engine.handle(event.text, trigger='chat')
        return {'status': 'accepted'}

    @app.post('/v1/chat', dependencies=[Depends(auth)])
    async def chat(message: ChatMessage):
        return await engine.handle(message.text, trigger='owner')

    @app.post('/v1/stop', dependencies=[Depends(auth)])
    async def stop():
        engine.stop()
        return {'stopped': True}

    return app
