"""Read-only acceptance on the installed VPS: actual GPT tools, web and resource use."""
import asyncio
import json
from pathlib import Path
import subprocess
import time
import urllib.request

from dotenv import dotenv_values
from napar.research import PublicWeb

base=Path('/opt/napar-next')
values=dotenv_values(base/'brain/.env')
headers={'Authorization':'Bearer '+values['NAPAR_BRIDGE_TOKEN']}


def api(path,data=None):
    request=urllib.request.Request('http://127.0.0.1:8000'+path,
        data=None if data is None else json.dumps(data,ensure_ascii=False).encode(),
        headers=headers|{'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=180) as response:return json.load(response)


async def main():
    health=api('/health');status=api('/v1/status')
    assert health.get('version')=='0.2.0' and health['connected']
    assert len(status['capabilities'])>=21
    print('PASS: NAPAR 0.2 connected with '+str(len(status['capabilities']))+' game tools.',flush=True)
    until=time.monotonic()+45
    while status['busy'] and time.monotonic()<until:
        await asyncio.sleep(1);status=api('/v1/status')
    assert not status['busy'],'Owner is using the brain; retry this read-only check later'
    remaining=status['limits']['daily_calls']-status['usage']['calls']
    assert remaining>=4,'Insufficient daily call allowance for the paid smoke test'
    # Exactly this diagnostic is allowed to invoke the configured paid GPT-5 backend.
    result=api('/v1/chat',{'text':'Проверка новой версии. Только чтение: обязательно вызови inspect для inventory (target null, radius 1), затем inspect для recipes (target minecraft:wooden_pickaxe, radius 1). Не меняй мир, цели, память и самостоятельность. В финале кратко по-русски скажи, какие материалы нужны для деревянной кирки и что ты действительно проверил. Не вызывай другие инструменты.'})
    assert result['status']=='completed',result['status']
    assert 'inspect:' in result['message'],'Model did not use the real game inspection tool'
    after=api('/v1/status')
    print('PASS: actual GPT-5 called the installed Minecraft tools and completed its Russian response.',flush=True)
    print(result['message'][-1600:],flush=True)
    web=PublicWeb()
    search=await web.search('Minecraft Java 26.2','minecraft')
    print('WEB search results: '+str(len(search['results'])),flush=True)
    assert search['results'],'Public search is unavailable from this VPS'
    page=await web.fetch('https://www.minecraft.net/en-us/article/minecraft-java-edition-26-2')
    assert len(page['text'])>200
    memory=subprocess.check_output(['systemctl','show','napar-next-game','--property=MemoryCurrent','--value'],text=True).strip()
    enabled=subprocess.check_output(['systemctl','is-enabled','napar-next-brain','napar-next-game'],text=True).strip()
    report={'health':health,'capabilities':after['capabilities'],'model_result':result,
            'paid_calls_used':after['usage']['calls']-status['usage']['calls'],
            'usage_after':after['usage'],'web_search':search,
            'web_page':{'url':page['url'],'retrieved':page['retrieved'],'characters':len(page['text'])},
            'game_memory_bytes':int(memory),'autostart':enabled,'limits':after['limits']}
    (base/'verify-0.2-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print('PASS: open web search and official page fetch work from the VPS.',flush=True)
    print('GAME MEMORY MiB: '+str(round(int(memory)/1024**2)),flush=True)
    print('PAID CALLS IN CHECK: '+str(report['paid_calls_used']),flush=True)
    print('READY: Minecraft Java 26.2 / 77.110.105.165:25565 / MrHobet',flush=True)


if __name__=='__main__':asyncio.run(main())
