"""Bad artwork cannot stop healthy cards; uncertain panel writes still stop."""
import asyncio
import io
import sys
from pathlib import Path
from types import SimpleNamespace
from PIL import Image

APP=Path(__file__).resolve().parents[1]/'pixora_led_displays'
sys.path[:0]=[str(APP),str(APP/'custom_components/pixora_local')]
from studio import Studio


async def scenario(names,fail_write=False):
    output=io.BytesIO();Image.new('RGB',(64,32)).save(output,'PNG');body=output.getvalue()
    studio=Studio.__new__(Studio);delivered=[];rendered=[]
    items=[{'id':name,'card':name,'enabled':True,'duration':1} for name in names]
    studio.data={'devices':{'panel':{'deck':'deck','playing':True}},'decks':{'deck':{'items':items}}}
    studio.store=SimpleNamespace(cards={name:{'name':name} for name in names})
    studio.card_timing={};studio.runtime={};studio.quiet=lambda cfg:False
    class Panel:
        async def info(self):return {'width':64,'active':False}
        async def request(self,*args):pass
    studio.selected=lambda ident:Panel()
    async def render(item,width,**kwargs):
        rendered.append(item['id'])
        if item['id']=='broken':raise ValueError('Invalid card artwork')
        return body
    async def deliver(*args,**kwargs):
        delivered.append(studio.runtime['panel']['item'])
        if fail_write:raise ValueError('Uncertain panel write')
        await asyncio.sleep(0)
        if len(delivered)>=4:raise asyncio.CancelledError()
    async def save():pass
    studio.render=render;studio.deliver=deliver;studio.save=save
    try:await studio.player('panel')
    except asyncio.CancelledError:pass
    return studio,delivered,rendered


async def check():
    studio,delivered,rendered=await scenario(['one','broken','two'])
    assert delivered==['one','two','one','two'], delivered
    assert rendered.count('broken')==1, rendered
    assert 'broken' in studio.runtime['panel']['warning']
    assert studio.data['devices']['panel']['playing']
    studio,delivered,_=await scenario(['broken'])
    assert not delivered and 'No playable cards remain' in studio.runtime['panel']['error']
    assert not studio.data['devices']['panel']['playing']
    studio,delivered,_=await scenario(['one','two'],True)
    assert delivered==['one'] and 'Uncertain panel write' in studio.runtime['panel']['error']
    print('Broken-card checks passed: healthy cards repeat in order, bad card skipped once per session, named warning, all-bad pause and no uncertain-write retry.')


asyncio.run(check())
