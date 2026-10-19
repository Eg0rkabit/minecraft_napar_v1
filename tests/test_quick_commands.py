import time
import pytest
from fastapi.testclient import TestClient
from napar.app import create_app
from napar.config import Settings
from napar.quick_commands import parse_control


@pytest.mark.parametrize('text',['иди за мной','Следуй за мной!','давай иди за мной','можешь идти за мной?','иди за мной, пожалуйста'])
def test_follow_variants(text):assert parse_control(text)=='follow'


@pytest.mark.parametrize('text',['не иди за мной потом добудь дерево','если я скажу иди за мной','иди за мной и сломай дом','как работает следование?'])
def test_complex_messages_are_not_misinterpreted(text):assert parse_control(text) is None


def test_game_follow_works_without_model_and_ignores_busy_reasoning(tmp_path):
    app=create_app(Settings(_env_file=None,bridge_token='x'*40,owner_name='Egor',database=tmp_path/'db',paid_enabled=False))
    class Unexpected:
        async def decide(self,*args,**kwargs):raise AssertionError('Model called')
    app.state.engine.backend=Unexpected()
    headers={'Authorization':'Bearer '+'x'*40}
    with TestClient(app) as client:
        sid=client.post('/v1/bridge/connect',headers=headers,json=dict(world_id='w',agent_name='Napar',capabilities=['follow_player','say'])).json()['session_id']
        client.post('/v1/bridge/state',headers=headers,json=dict(session_id=sid,sequence=1,position=dict(x=0,y=64,z=0),health=20,food=20))
        app.state.engine.busy=True
        event=dict(session_id=sid,event_id='follow',kind='chat',sender='Egor',text='иди за мной')
        assert client.post('/v1/bridge/events',headers=headers,json=event).json()['status']=='local_queued'
        observed=[]
        until=time.monotonic()+2
        while len(observed)<2 and time.monotonic()<until:
            for action in client.get('/v1/bridge/actions',headers=headers,params=dict(session_id=sid)).json()['actions']:
                observed.append(action)
                client.post('/v1/bridge/results',headers=headers,json=dict(session_id=sid,action_id=action['action_id'],status='succeeded',detail='established'))
            time.sleep(.01)
        assert [a['tool'] for a in observed]==['follow_player','say']
        assert observed[0]['arguments']=={'player':'Egor'}
        assert observed[1]['arguments']['message']=='Ага, иду за тобой.'
        assert app.state.store.usage()['calls']==0
        assert client.post('/v1/bridge/events',headers=headers,json=event).json()['status']=='duplicate'


@pytest.mark.parametrize('text,expected',[('останься на сервере','stay'),('не выходи','stay'),('выходи после меня','auto_leave')])
def test_presence_controls(text,expected):assert parse_control(text)==expected


def test_presence_preference_is_persistent_and_world_scoped(tmp_path):
    from napar.storage import Store
    path=tmp_path/'presence.db'
    store=Store(path)
    assert store.presence('a')=='auto'
    store.presence('a','stay')
    store.close()
    store=Store(path)
    assert store.presence('a')=='stay' and store.presence('b')=='auto'
    store.close()


def test_legacy_preferences_migrate_without_losing_autonomy(tmp_path):
    import sqlite3
    from napar.storage import Store
    path=tmp_path/'old.db'
    with sqlite3.connect(path) as db:
        db.execute('create table preferences(world text primary key,autonomy text)')
        db.execute('insert into preferences values(?,?)',('w','expanded'))
    store=Store(path)
    assert store.autonomy('w')=='expanded' and store.presence('w')=='auto'
    store.close()

