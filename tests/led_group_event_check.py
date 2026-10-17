"""Group event slices, shared timeline and duplicate-monitor suppression."""
import asyncio
import base64
import io
import sys
from pathlib import Path
from types import SimpleNamespace
from PIL import Image,ImageDraw

APP=Path(__file__).resolve().parents[1]/'pixora_led_displays'
sys.path[:0]=[str(APP),str(APP/'custom_components/pixora_local')]
from studio import Studio


async def check():
    studio=Studio.__new__(Studio);calls=[]
    async def submit(entries,key,state):calls.append((entries,key,state))
    studio.pipeline=SimpleNamespace(submit=submit);studio.quiet=lambda cfg:False
    card={'id':'item','card':'sport','options':{},'enabled':True}
    studio.data={'devices':{'left':{'playing':True,'deck':'deck'},'right':{'playing':True,'deck':'deck'}},'decks':{'deck':{'items':[card]}}}
    frames=[]
    for color in ('red','green'):
        frame=Image.new('RGB',(192,32),'blue');ImageDraw.Draw(frame).rectangle((0,0,63,31),fill=color);frames.append(frame)
    out=io.BytesIO();frames[0].save(out,'WEBP',save_all=True,append_images=frames[1:],duration=[70,350],lossless=True,loop=1)
    event={'body':base64.b64encode(out.getvalue()).decode(),'duration':6,'wall':True,'kind':'score','once':True}
    request={'state_key':'left-history','device_id':'left','module':'sport','card_id':'sport','identity_options':{},'wall_members':[('left',64),('right',128)]}
    await studio.accept_event(request,{'event':event,'state':{'score':1}})
    entries=calls[-1][0];assert [i for i,_ in entries]==['left','right']
    assert entries[0][1]['event_id']==entries[1][1]['event_id']
    assert entries[0][1]['start_at']==entries[1][1]['start_at']
    for (ident,payload),width,color in zip(entries,(64,128),((255,0,0),(0,0,255))):
        with Image.open(io.BytesIO(base64.b64decode(payload['body']))) as image:
            assert image.size==(width,32) and image.n_frames==(2 if ident=='left' else 1)
            assert image.convert('RGB').getpixel((0,0))==color
    await studio.accept_event({**request,'device_id':'right','state_key':'right-history'},{'event':event,'state':{'score':1}})
    assert calls[-1][0]==[], 'Two group members queued the same celebration twice'
    print('Group events passed: 64/128 slices, shared start, correct pixels, history commits and duplicate-monitor suppression.')


asyncio.run(check())
