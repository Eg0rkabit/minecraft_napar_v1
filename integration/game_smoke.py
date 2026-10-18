"""Real Minecraft mechanics acceptance test. Loopback only, scripted brain, no paid API."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import time

import uvicorn
from napar.app import create_app
from napar.config import Settings

ROOT=Path(__file__).resolve().parents[1]
MOD=ROOT/'minecraft-mod'
ARTIFACTS=Path(os.environ.get('NAPAR_SMOKE_OUTPUT',str(ROOT/'test-artifacts')))
ARTIFACTS.mkdir(parents=True,exist_ok=True)
LOG=ARTIFACTS/'expanded-game-smoke.log'
REPORT=ARTIFACTS/('extra-game-smoke.json' if os.getenv('NAPAR_SMOKE_EXTRA') else 'expanded-game-smoke.json')
TOKEN='local-acceptance-test-token-'*2
app=create_app(Settings(_env_file=None,bridge_token=TOKEN,owner_name='Napar',database=ARTIFACTS/'smoke.db',action_timeout=35,llm_backend='disabled',initiative_seconds=0))

async def main():
    properties=MOD/'run/server.properties'
    if not (MOD/'run/eula.txt').exists() or 'eula=true' not in (MOD/'run/eula.txt').read_text():
        raise RuntimeError('Accept the Minecraft EULA in minecraft-mod/run/eula.txt before running the test')
    original=properties.read_text() if properties.exists() else ''
    values=dict(line.split('=',1) for line in original.splitlines() if '=' in line and not line.startswith('#'))
    values.update({'server-ip':'127.0.0.1','server-port':'25575','online-mode':'false','pause-when-empty-seconds':'0','level-name':'world-acceptance'})
    properties.write_text('\n'.join(f'{k}={v}' for k,v in values.items())+'\n')
    env=os.environ.copy()
    if not env.get('JAVA_HOME'):
        raise RuntimeError('JAVA_HOME must point to JDK 25')
    env.update(NAPAR_BRIDGE_TOKEN=TOKEN,NAPAR_WORLD_ID='expanded-acceptance',NAPAR_OWNER_NAME='Napar',NAPAR_BRIDGE_URL='http://127.0.0.1:8001',NAPAR_RESTORE_PLAYER='false')
    gradle_command=(['cmd.exe','/c',str(MOD/'gradlew.bat')] if os.name=='nt' else [str(MOD/'gradlew')])+['runServer','--no-daemon','--console=plain']
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=8001,log_level='warning'))
    web=asyncio.create_task(server.serve())
    results=[]
    passed=False
    with LOG.open('w',encoding='utf-8') as output:
        process=subprocess.Popen(gradle_command,cwd=MOD,env=env,stdin=subprocess.PIPE,stdout=output,stderr=subprocess.STDOUT,text=True)
        def cmd(text):
            process.stdin.write(text+'\n');process.stdin.flush()
        async def wait(check,timeout=120):
            until=time.monotonic()+timeout
            while not check():
                if process.poll() is not None:raise RuntimeError('Minecraft exited; inspect log')
                if time.monotonic()>until:raise TimeoutError('Minecraft wait timed out')
                await asyncio.sleep(.25)
        async def action(name,args,expected='succeeded'):
            result=await app.state.bridge.execute(name,args)
            results.append(dict(tool=name,arguments=args,result=result))
            print(name,result.get('status'),result.get('detail'),flush=True)
            assert result['status']==expected,result
            await asyncio.sleep(.7)
            return result
        def inventory(item):return sum(i['count'] for i in app.state.bridge.observe()['inventory'] if i['item']==item)
        try:
            await wait(lambda:'Napar runtime loaded.' in LOG.read_text(errors='replace'))
            for text in ['gamerule doDaylightCycle false','time set day','difficulty peaceful','forceload add -16 -16 32 32','fill -12 199 -12 20 199 20 stone','fill -12 200 -12 20 207 20 air','setblock 3 200 0 oak_log','setblock 0 200 3 crafting_table','setblock -2 200 2 chest','setblock -3 200 2 furnace','execute positioned 0.5 200 0.5 run napar spawn']:
                cmd(text)
            await wait(lambda:app.state.bridge.connected,45)
            for text in ['clear Napar','give Napar oak_log 2','give Napar cobblestone 8','give Napar coal 2','give Napar raw_iron 1','give Napar apple 3','give Napar iron_pickaxe 1','effect give Napar hunger 5 255 true']:
                cmd(text)
            await asyncio.sleep(2)
            if os.getenv('NAPAR_SMOKE_EXTRA'):
                for text in ['give Napar shield 1','give Napar iron_sword 1','give Napar iron_helmet 1','setblock 2 200 1 stone_slab[type=bottom]','setblock 4 200 1 stone_brick_stairs[facing=east]','fill 6 197 0 9 197 3 stone','fill 6 198 0 9 199 3 water','setblock 1 200 3 red_bed[facing=south,part=foot]','setblock 1 200 4 red_bed[facing=south,part=head]']:
                    cmd(text)
                await asyncio.sleep(1)
                await action('equip',dict(item='minecraft:iron_helmet',slot='head'))
                await action('move_to',dict(x=2.5,y=200.5,z=1.5))
                await action('move_to',dict(x=4.5,y=201,z=1.5))
                await action('move_to',dict(x=7.5,y=199,z=1.5))
                await action('move_to',dict(x=10.5,y=200,z=1.5))
                await action('move_to',dict(x=3.5,y=200,z=5.5))
                cmd('summon cow 4.5 200 5.5 {NoAI:1b,PersistenceRequired:1b}')
                await asyncio.sleep(1)
                cow=next(e for e in app.state.bridge.observe()['entities'] if e['kind']=='minecraft:cow')
                await action('equip',dict(item='minecraft:iron_sword',slot='mainhand'))
                await action('attack',dict(target=cow['id'],tactic='shield'))
                await action('move_to',dict(x=.5,y=200,z=2.5))
                cmd('time set midnight')
                await asyncio.sleep(1)
                await action('sleep',dict(x=1,y=200,z=3))
                passed=True
                REPORT.write_text(json.dumps(dict(passed=True,results=results,state=app.state.bridge.observe()),ensure_ascii=False,indent=2),encoding='utf-8')
                print('EXTRA_GAME_SMOKE_PASSED',flush=True)
                return
            await action('inspect',dict(sensor='area',target='oak_log',radius=6))
            await action('inspect',dict(sensor='recipes',target='oak_planks',radius=1))
            before=inventory('minecraft:oak_log')
            await action('craft',dict(recipe='minecraft:oak_planks',times=1))
            assert inventory('minecraft:oak_log')==before-1 and inventory('minecraft:oak_planks')==4
            await action('craft',dict(recipe='minecraft:stick',times=1))
            assert inventory('minecraft:stick')==4
            await action('craft',dict(recipe='minecraft:furnace',times=1))
            assert inventory('minecraft:cobblestone')==0 and inventory('minecraft:furnace')==1
            await action('craft',dict(recipe='minecraft:furnace',times=1),'failed')
            await action('equip',dict(item='minecraft:iron_pickaxe',slot='mainhand'))
            await action('mine',dict(x=3,y=200,z=0))
            await action('open_container',dict(x=-2,y=200,z=2))
            await action('transfer',dict(x=-2,y=200,z=2,direction='put',slot=0,count=2,item='minecraft:stick'))
            assert inventory('minecraft:stick')==2
            await action('transfer',dict(x=-2,y=200,z=2,direction='take',slot=0,count=2,item='minecraft:stick'))
            assert inventory('minecraft:stick')==4
            await action('move_to',dict(x=-3.5,y=200,z=.5))
            await action('smelt',dict(x=-3,y=200,z=2,input='minecraft:raw_iron',fuel='minecraft:coal',count=1))
            await asyncio.sleep(11)
            await action('inspect',dict(sensor='container',target='-3,200,2',radius=1))
            await action('transfer',dict(x=-3,y=200,z=2,direction='take',slot=2,count=1,item='minecraft:iron_ingot'))
            assert inventory('minecraft:iron_ingot')==1
            if app.state.bridge.observe()['food']<20:await action('eat',dict(item='minecraft:apple'))
            await action('move_to',dict(x=.5,y=200,z=.5))
            await action('place',dict(x=1,y=199,z=0,item='minecraft:oak_planks',face='up'))
            # Step up onto a real block, then down again without teleporting.
            await action('move_to',dict(x=1.5,y=201,z=.5))
            await action('move_to',dict(x=4.5,y=200,z=2.5))
            moving=asyncio.create_task(app.state.bridge.execute('move_to',dict(x=14.5,y=200,z=14.5)))
            await asyncio.sleep(.5);app.state.engine.stop();cancelled=await moving
            assert cancelled['status']=='cancelled'
            await asyncio.sleep(1);first=app.state.bridge.observe()['position'];await asyncio.sleep(1);last=app.state.bridge.observe()['position']
            assert sum((first[k]-last[k])**2 for k in first)<.02
            cmd('difficulty normal')
            cmd('clear Napar apple')
            cmd('effect give Napar hunger 8 255 true')
            await asyncio.sleep(8.5)
            cmd('give Napar bread 16')
            await asyncio.sleep(.3)
            await action('eat',dict(item='minecraft:bread'))
            # A separate stationary mob verifies real health damage and melee cooldown.
            cmd('give Napar iron_sword 1')
            here=app.state.bridge.observe()['position']
            cmd(f'summon cow {here["x"]+2} 200 {here["z"]} {{NoAI:1b,PersistenceRequired:1b,Tags:["napar_acceptance"]}}')
            await asyncio.sleep(1)
            cow=next(e for e in app.state.bridge.observe()['entities'] if e['kind']=='minecraft:cow')
            await action('equip',dict(item='minecraft:iron_sword',slot='mainhand'))
            await action('attack',dict(target=cow['id']))
            drops=[e for e in app.state.bridge.observe()['entities'] if e['kind']=='minecraft:item']
            if drops:
                await action('pickup',dict(target=drops[0]['id']))
            cmd('player Alex spawn at 8.5 200 2.5 facing 0 0 in minecraft:overworld')
            await wait(lambda:any(e['name']=='Alex' for e in app.state.bridge.observe()['entities']),30)
            await action('follow_player',dict(player='Alex'))
            await asyncio.sleep(12)
            assert app.state.bridge.observe()['activity']=='following:Alex'
            assert abs(app.state.bridge.observe()['position']['x']-8.5)<3
            await action('stop',{},expected='confirmed')
            cmd('player Alex kill')
            # Prove death records an incident and respawns at the native world spawn.
            cmd('setworldspawn 0 200 0')
            cmd('damage Napar 100 minecraft:generic_kill')
            await asyncio.sleep(4.1)
            await wait(lambda:app.state.bridge.connected,35)
            assert inventory('minecraft:iron_ingot')==0
            assert app.state.store.recall('expanded-acceptance','last_incident')
            expected=app.state.bridge.observe()['position']
            old_sid=app.state.bridge.session_id
            cmd('stop')
            await asyncio.to_thread(process.wait,60)
            app.state.bridge.disconnect()
            env['NAPAR_RESTORE_PLAYER']='true'
            process=subprocess.Popen(gradle_command,cwd=MOD,env=env,stdin=subprocess.PIPE,stdout=output,stderr=subprocess.STDOUT,text=True)
            await wait(lambda:app.state.bridge.connected and app.state.bridge.session_id!=old_sid,90)
            actual=app.state.bridge.observe()['position']
            assert sum((expected[k]-actual[k])**2 for k in actual)<4
            results.append(dict(tool='restart',result='Separate FakePlayer restored without a human joining'))
            passed=True
            REPORT.write_text(json.dumps(dict(passed=True,results=results,state=app.state.bridge.observe(),stop=cancelled),ensure_ascii=False,indent=2),encoding='utf-8')
            print('EXPANDED_GAME_SMOKE_PASSED',flush=True)
        finally:
            if not passed:REPORT.write_text(json.dumps(dict(passed=False,results=results),ensure_ascii=False,indent=2),encoding='utf-8')
            if process.poll() is None:
                cmd('stop')
                try:await asyncio.to_thread(process.wait,60)
                except subprocess.TimeoutExpired:process.terminate()
            properties.write_text(original)
            server.should_exit=True
            await web

if __name__=='__main__':asyncio.run(main())
