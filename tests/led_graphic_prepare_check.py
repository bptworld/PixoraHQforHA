"""Preparing a test never delivers; concurrent Test shares its render and slices."""
import asyncio
import base64
import io
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from PIL import Image

APP=Path(__file__).resolve().parents[1]/'pixora_led_displays'
sys.path[:0]=[str(APP),str(APP/'custom_components/pixora_local')]
from studio import Studio

async def check():
    with tempfile.TemporaryDirectory() as folder:
        studio=Studio.__new__(Studio);studio.lock=asyncio.Lock();studio.graphic_jobs={};studio.graphic_prepared={}
        card={'id':'nhl','options':[{'key':'goalAnimationTarget','label':'Goal'}]}
        studio.store=SimpleNamespace(cards={'nhl':card},installed=lambda card:True)
        studio.data={'groups':{'pair':{'name':'Pair','members':['left','right']}}}
        studio.selected=lambda ident:object()  # No status HTTP request is needed to prepare a test.
        studio.displays=lambda:[{'id':'left','width':64},{'id':'right','width':128}]
        studio.validate_deck=lambda payload:payload
        studio.used=lambda:set()
        renders=[];sent=[];release=asyncio.Event();entered=asyncio.Event()
        async def collect(ids):pass
        studio.store.collect=collect
        async def render(item,width,**kwargs):return {'width':width,'options':item['options']}
        studio.render=render
        out=io.BytesIO();Image.new('RGB',(192,32),'blue').save(out,'PNG')
        async def worker(request):
            renders.append(request);entered.set();await release.wait()
            return {'event':{'body':base64.b64encode(out.getvalue()).decode(),'duration':6,'once':True}}
        studio.run_worker=worker
        async def submit(entries):sent.append(entries)
        studio.pipeline=SimpleNamespace(submit=submit)
        payload={'display':'left','card':'nhl','option':'goalAnimationTarget','options':{'goalAnimationTarget':'group:pair'}}
        warm=asyncio.create_task(studio.test_graphic(payload,prepare=True));await entered.wait()
        assert not sent
        test=asyncio.create_task(studio.test_graphic(payload));await asyncio.sleep(.01)
        assert len(renders)==1 and not sent
        release.set();await warm;result=await test
        assert result['queued'] and len(sent)==1 and len(sent[0])==2
        assert len(renders)==1 and not studio.graphic_jobs
        start=time.monotonic();await studio.test_graphic(payload)
        warm_ms=(time.monotonic()-start)*1000
        assert len(renders)==1 and len(sent)==2
        assert sent[0][0][1]['event_id']!=sent[1][0][1]['event_id'],'New manual Test was mistaken for a replay'
        studio.store.installed=lambda card:False
        assert await studio.test_graphic(payload,prepare=True)=={'prepared':False}
        assert len(renders)==1 and len(sent)==2,'Preparation downloaded an unused card or sent an interrupt'
        print(f'Graphic preparation passed: no delivery/download, shared render, pre-sliced groups, cached Test {warm_ms:.2f}ms and unique explicit interrupts.')

asyncio.run(check())
