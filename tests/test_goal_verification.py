import json
from napar.app import create_app
from napar.config import Settings
from napar.protocol import Connect,Snapshot,Position

async def test_chat_success_cannot_complete_unfulfilled_inventory_goal(tmp_path):
    app=create_app(Settings(_env_file=None,bridge_token='x'*40,database=tmp_path/'db'))
    b=app.state.bridge
    sid=b.connect(Connect(world_id='w',agent_name='Napar',capabilities=[]))['session_id']
    b.update(Snapshot(session_id=sid,sequence=1,position=Position(x=0,y=64,z=0),health=20,food=20))
    goal=app.state.store.create_goal('w','20 iron','inventory',dict(kind='inventory',dimension='minecraft:overworld',position=None,item='minecraft:iron_ingot',count=20))
    result=await app.state.engine.toolbox.execute('update_goal',json.dumps(dict(goal_id=goal['goal_id'],status='completed',summary='done',evidence_action_id='chat')),{'chat'})
    assert result['status']=='failed'
    assert app.state.store.goals('w')[0]['status']=='active'
    app.state.store.close()
