"""Deck handoff timing without real delays or panel commands."""
import asyncio
import io
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'pixora_led_displays'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'pixora_led_displays/custom_components/pixora_local'))
from studio import Studio


async def check():
    output=io.BytesIO();Image.new('RGB',(64,32)).save(output,'PNG');body=output.getvalue()
    studio=Studio.__new__(Studio)
    for duration in (10,300):
        elapsed=0;expires=0;writes=0
        async def send(*args,**kwargs):
            nonlocal expires,writes
            lease=args[-1];assert lease<=300
            expires=elapsed+lease;writes+=1
        async def sleep(seconds):
            nonlocal elapsed
            elapsed+=seconds
            assert expires>=elapsed+60, 'Artwork expires before the next-card transition'
        studio.send_frame=send
        with patch('studio.asyncio.sleep',sleep):await studio.deliver(None,body,64,duration)
        assert abs(elapsed-duration)<.01 and writes==(2 if duration==300 else 1)

    items=[{'id':n,'card':n,'duration':10,'enabled':True} for n in ('first','second')]
    studio.data={'devices':{'panel':{'deck':'deck'}},'decks':{'deck':{'items':items}}}
    studio.card_timing={};studio.runtime={};studio.store=SimpleNamespace(cards={n:{'name':n} for n in ('first','second')})
    studio.quiet=lambda cfg:False
    class Panel:
        async def info(self):return {'width':64,'active':False}
        async def request(self,*args):pass
    studio.selected=lambda ident:Panel()
    rendered=[];delivered=[]
    async def render(item,width,**kwargs):rendered.append(item['id']);return body
    async def deliver(*args,**kwargs):
        await asyncio.sleep(0)
        expected=('second','first','second')[len(delivered)]
        assert rendered[-1]==expected, 'Next card was not prepared during playback'
        delivered.append(studio.runtime['panel']['item'])
        if len(delivered)==3:raise ValueError('End isolated timing check')
    async def save():pass
    studio.render=render;studio.deliver=deliver;studio.save=save
    await studio.player('panel')
    assert delivered==['first','second','first']
    # A save during delivery must invalidate prefetched artwork with old options.
    rendered.clear();delivered.clear()
    items[1]['options']={'label':'old'}
    async def edited_render(item,width,**kwargs):
        rendered.append((item['id'],dict(item.get('options',{}))))
        return body
    async def edited_deliver(*args,**kwargs):
        await asyncio.sleep(0)
        delivered.append(studio.runtime['panel']['item'])
        if len(delivered)==1:
            studio.data['decks']['deck']={'items':[items[0],{**items[1],'options':{'label':'new'}}]}
        else:raise ValueError('End edited deck check')
    studio.data['decks']['deck']={'items':items};studio.render=edited_render;studio.deliver=edited_deliver
    await studio.player('panel')
    assert delivered==['first','second']
    assert ('second',{'label':'old'}) in rendered and ('second',{'label':'new'}) in rendered
    print('Playback timing passed: next-card preparation across deck repeat, hold buffer, 300s lease renewal and task cleanup.')


asyncio.run(check())
