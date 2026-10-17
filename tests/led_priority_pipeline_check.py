"""Durable local priority queue, order, deduplication and uncertain-write recovery."""
import asyncio
import base64
import io
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image

APP=Path(__file__).resolve().parents[1]/'pixora_led_displays';sys.path[:0]=[str(APP),str(APP/'custom_components/pixora_local')]
from pipeline import Pipeline,normalize_image


async def check():
    with tempfile.TemporaryDirectory() as temp:
        calls=[];fail=False
        class Panel:
            async def info(self):return {'width':64,'active':False}
            async def show(self,message,color,duration):
                calls.append(message)
                if fail:raise ValueError('Uncertain write')
        async def deliver(*args,**kwargs):calls.append('event');assert kwargs['once']
        studio=SimpleNamespace(selected=lambda ident:Panel(),deliver=deliver,runtime={})
        pipeline=Pipeline(Path(temp),studio)
        event={'body':base64.b64encode(b'fixture').decode(),'duration':.01,'event_id':'event-1','source':'event','once':True}
        ha=lambda text:{'message':text,'color':[255,255,255],'duration':.01,'source':'ha'}
        await pipeline.submit([('panel',event),('panel',ha('first')),('panel',ha('second'))],'history',{'score':1})
        await pipeline.jobs['panel']
        assert calls==['first','second','event'],calls
        assert pipeline.data['states']['history']=={'score':1}
        await pipeline.submit([('panel',event)]);assert calls==['first','second','event']
        # An interrupted message is consumed before sending and never replayed after restart.
        fail=True
        await pipeline.submit([('panel',ha('uncertain')),('panel',ha('must not send'))])
        await pipeline.jobs['panel'];assert calls.count('uncertain')==1 and 'must not send' not in calls
        try:await pipeline.wait_ready('panel')
        except ValueError:pass
        else:raise AssertionError('Uncertain delivery did not stop deck writes')
        pipeline.data['inflight']={'panel':'possibly-delivered'};pipeline.persist()
        restored=Pipeline(Path(temp),studio);assert 'panel' in restored.errors and restored.data['queues']['panel']==[]
        assert calls.count('uncertain')==1
        restored.errors.clear();restored.start=lambda ident:None
        before=list(restored.data['queues']['panel'])
        with patch('pipeline.os.replace',side_effect=OSError('Disk full')):
            try:await restored.submit([('panel',ha('not committed'))])
            except OSError:pass
            else:raise AssertionError('Queue persisted despite disk failure')
        assert restored.data['queues']['panel']==before
        # Animated uploads preserve their frame delays.
        out=io.BytesIO();frames=[Image.new('RGB',(64,32),c) for c in ('red','blue')]
        frames[0].save(out,'GIF',save_all=True,append_images=frames[1:],duration=[80,320],loop=0)
        with Image.open(io.BytesIO(normalize_image(out.getvalue(),128))) as image:
            assert image.n_frames==2 and image.size==(128,32)
            durations=[]
            for i in range(2):image.seek(i);image.load();durations.append(image.info['duration'])
            assert durations==[80,320],durations
        from studio import Studio
        from client import DisplayBusy
        playback=Studio.__new__(Studio);playback.runtime={};timeline=[];first_frame=asyncio.Event()
        class PlaybackPanel:
            async def info(self):return {'width':64,'active':False}
            async def request(self,path,payload):timeline.append(payload['owner']);first_frame.set()
            async def show(self,*args):timeline.append('ha')
        panel=PlaybackPanel();playback.selected=lambda ident:panel
        playback.pipeline=Pipeline(Path(temp)/'resume',playback)
        png=io.BytesIO();Image.new('RGB',(64,32)).save(png,'PNG')
        import time
        started=time.monotonic()
        deck=asyncio.create_task(playback.deliver(panel,png.getvalue(),64,.2,ident='panel'))
        await first_frame.wait()
        await playback.pipeline.submit([('panel',{'message':'interrupt','duration':.05,'source':'ha'})])
        from client import PriorityMessageActive
        try:await asyncio.wait_for(deck,2)
        except PriorityMessageActive:pass
        else:raise AssertionError('Interrupted card resumed instead of advancing')
        await playback.pipeline.jobs['panel']
        assert timeline==['deck','ha'],timeline
        attempts=0
        async def busy_write():
            nonlocal attempts
            attempts+=1
            if attempts<3:raise DisplayBusy('Explicitly rejected')
        await playback.pipeline.write('panel',busy_write);assert attempts==3
        attempts=0
        async def uncertain_write():
            nonlocal attempts
            attempts+=1;raise ValueError('Uncertain outcome')
        try:await playback.pipeline.write('panel',uncertain_write)
        except ValueError:pass
        assert attempts==1
        await playback.pipeline.close()
        await pipeline.close();await restored.close()
    print('Priority pipeline passed: HA FIFO ahead of events, durable history, deduplication, no uncertain replay, restart recovery, disk-failure rollback and animated uploads.')


asyncio.run(check())
