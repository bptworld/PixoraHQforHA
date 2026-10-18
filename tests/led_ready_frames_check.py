"""Ready RGB frames preserve pixels/delays and avoid image work on the send path."""
import asyncio
import base64
import io
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image,ImageDraw

APP=Path(__file__).resolve().parents[1]/'pixora_led_displays'
sys.path[:0]=[str(APP),str(APP/'custom_components/pixora_local')]
from studio import Studio,PanelFrame

async def check():
    studio=Studio.__new__(Studio);sent=[]
    async def request(path,payload):sent.append((path,payload));return {'accepted':True}
    client=SimpleNamespace(request=request)
    frames=[]
    for color in ('red','green'):
        frame=Image.new('RGB',(192,32),'blue');ImageDraw.Draw(frame).rectangle((0,0,63,31),fill=color);frames.append(frame)
    out=io.BytesIO();frames[0].save(out,'WEBP',save_all=True,append_images=frames[1:],duration=[70,350],lossless=True,method=0)
    slices=await studio.prepared_slices(out.getvalue(),[('left',64),('right',128)])
    assert not sent,'Preparing frames sent an interrupt'
    assert await studio.prepared_slices(out.getvalue(),[('left',64),('right',128)]) is slices
    left=base64.b64decode(slices[0][2]);ready=await studio.prepared_frames(left,64)
    assert all(isinstance(frame,PanelFrame) for frame,_ in ready)
    assert [round(delay*1000) for _,delay in ready]==[70,350]
    for (frame,_),color in zip(ready,((255,0,0),(0,128,0))):
        pixels=base64.b64decode(frame.rgb);assert len(pixels)==64*32*3 and tuple(pixels[:3])==color
    # Cached delivery has no PNG encode, image reopen or RGB conversion.
    async def sleep(seconds):pass
    with patch('studio.Image.open',side_effect=AssertionError('Image work reached the send path')),patch('studio.asyncio.sleep',sleep):
        await studio.deliver(client,left,64,.001,owner='message',once=True)
    assert len(sent)==1 and sent[0][0]=='/api/frame'
    assert sent[0][1]['rgb']==ready[0][0].rgb and sent[0][1]['owner']=='message'
    assert sent[0][1]['width']==64 and sent[0][1]['height']==32
    reordered=await studio.prepared_slices(out.getvalue(),[('right',128),('left',64)])
    assert reordered is not slices,'Group order reused the wrong slices'
    assert len(base64.b64decode((await studio.prepared_frames(base64.b64decode(reordered[0][2]),128))[0][0].rgb))==128*32*3
    print('Ready frames passed: exact 64/128 RGB pixels, 70/350ms timing, cached wall slices, group-order isolation and no image conversion during cached delivery.')

asyncio.run(check())
