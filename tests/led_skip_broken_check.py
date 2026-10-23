"""Bad artwork cannot stop healthy cards; uncertain panel writes still stop."""
import asyncio
import io
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image

APP=Path(__file__).resolve().parents[1]/'pixora_led_displays'
sys.path[:0]=[str(APP),str(APP/'custom_components/pixora_local')]
from studio import Studio,CardSkipped


async def scenario(names,fail_write=False,recovery=False,empty=False,graphic=False,width=64):
    elapsed=0;real_sleep=asyncio.sleep
    output=io.BytesIO();Image.new('RGB',(width,32)).save(output,'PNG');body=output.getvalue()
    studio=Studio.__new__(Studio);delivered=[];rendered=[]
    items=[{'id':name,'card':name,'enabled':True,'duration':1} for name in names]
    items.append({'id':'disabled','card':'disabled','enabled':False,'duration':1})
    if graphic:
        for item in items:
            if item['id']=='broken':item.pop('card');item['graphic']='broken'
    studio.data={'devices':{'panel':{'deck':'deck','playing':True}},'decks':{'deck':{'items':items}},'graphics':{'broken':{'name':'broken'}}}
    studio.store=SimpleNamespace(cards={name:{'name':name} for name in names})
    studio.card_timing={};studio.runtime={};studio.quiet=lambda cfg:False
    class Panel:
        async def info(self):return {'width':width,'active':False}
        async def request(self,*args):pass
    studio.selected=lambda ident:Panel()
    async def render(item,width,**kwargs):
        rendered.append(item['id'])
        if item['id']=='broken' and (not recovery or elapsed<(15 if empty else 60)):
            raise (CardSkipped('No content') if empty else ValueError('Temporary provider failure'))
        return body
    async def deliver(*args,**kwargs):
        nonlocal elapsed
        delivered.append(studio.runtime['panel']['item'])
        if fail_write:raise ValueError('Uncertain panel write')
        await real_sleep(0);elapsed+=1
        if (recovery and delivered[-1]=='broken') or len(delivered)>100 or (not recovery and len(delivered)>=4):raise asyncio.CancelledError()
    async def sleep(seconds):
        nonlocal elapsed
        elapsed+=seconds;await real_sleep(0)
    async def save():pass
    studio.render=render;studio.deliver=deliver;studio.save=save
    with patch('studio.time',SimpleNamespace(monotonic=lambda:elapsed,time=lambda:elapsed)),patch('studio.asyncio.sleep',sleep):
        try:await studio.player('panel')
        except asyncio.CancelledError:pass
    assert 'disabled' not in rendered
    return studio,delivered,rendered


async def check():
    studio,delivered,rendered=await scenario(['one','broken','two'])
    assert delivered==['one','two','one','two'], delivered
    assert rendered.count('broken')==1, rendered
    assert 'broken' in studio.runtime['panel']['warning']
    assert studio.data['devices']['panel']['playing']
    for width in (64,128):
        for empty in (True,False):
            for names in (['broken'],['one','broken']):
                for graphic in (False,True):
                    studio,delivered,rendered=await scenario(names,recovery=True,empty=empty,graphic=graphic,width=width)
                    assert delivered[-1]=='broken' and rendered.count('broken')>=2,(width,empty,names,graphic,delivered)
                    assert 'warning' not in studio.runtime['panel'],'Recovered card retained an old warning'
    studio,delivered,_=await scenario(['one','two'],True)
    assert delivered==['one'] and 'Uncertain panel write' in studio.runtime['panel']['error']
    print('Card recovery passed: 64/128 widths, empty/provider-error cards and graphics rejoin mixed or all-empty decks, disabled cards stay disabled, healthy rotation continues and uncertain writes are not retried.')


asyncio.run(check())
