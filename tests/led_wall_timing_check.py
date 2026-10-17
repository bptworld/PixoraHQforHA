"""Local wall readiness, shared animation clock and no replay after write failures."""
import asyncio,base64,io,sys,tempfile,time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image
APP=Path(__file__).resolve().parents[1]/'pixora_led_displays'
sys.path[:0]=[str(APP),str(APP/'custom_components/pixora_local')]
from studio import Studio
from pipeline import Pipeline

async def check():
    # Clock-driven playback must catch up rather than accumulate slow-write latency.
    studio=Studio.__new__(Studio)
    clock=0;seen=[]
    async def tick(seconds):
        nonlocal clock
        clock+=seconds
    async def write(client,body,*args,**kwargs):
        nonlocal clock
        seen.append((body,round(clock,3)));clock+=.18 if len(seen)==1 else .01
    studio.send_frame=write
    with patch('studio.time',SimpleNamespace(monotonic=lambda:clock)),patch('studio.asyncio.sleep',tick):
        await studio.deliver_timeline(None,[(b'0',.05),(b'1',.05),(b'2',.1),(b'3',.1)],64,.3,0,'message',None,True,None)
    assert [row[0] for row in seen]==[b'0',b'2',b'3'],seen
    assert abs(clock-.3)<.001,clock

    frames=[Image.new('RGB',(192,32),(red,0,0)) for red in (10,20,30)]
    out=io.BytesIO();frames[0].save(out,'WEBP',save_all=True,append_images=frames[1:],duration=[50,50,200],lossless=True,method=0)
    with tempfile.TemporaryDirectory() as temp:
        for scenario in ('slow','queued-ha','legacy-busy','wire-busy','unavailable','dimensions','missing','uncertain'):
            studio=Studio.__new__(Studio);studio.runtime={};studio.data={'devices':{'left':{'playing':True},'right':{'playing':True}}}
            async def save():pass
            studio.save=save;writes=[];ha=[];started=time.monotonic()
            class Panel:
                def __init__(self,ident):self.ident=ident
                async def info(self):
                    if scenario=='unavailable' and self.ident=='right':raise ValueError('Offline')
                    return {'width':64 if self.ident=='left' else 128,'active':scenario=='legacy-busy' and self.ident=='left','owner':'message','remaining':.08}
                async def show(self,*args):ha.append(time.monotonic())
                async def request(self,path,payload):
                    red=base64.b64decode(payload['rgb'])[0];writes.append((self.ident,red,time.monotonic()))
                    if self.ident=='left' and red==10:
                        if scenario=='uncertain':raise ValueError('Unknown write result')
                        if scenario=='slow':await asyncio.sleep(.12)
            studio.selected=lambda ident:Panel(ident)
            pipeline=studio.pipeline=Pipeline(Path(temp)/scenario,studio)
            release_task=None
            if scenario=='wire-busy':
                wire=pipeline.wires['left']=asyncio.Lock();await wire.acquire()
                async def release_wire():await asyncio.sleep(.08);wire.release()
                release_task=asyncio.create_task(release_wire())
            wall={'body':base64.b64encode(out.getvalue()).decode(),'duration':.25,'event_id':'wall-'+scenario,'source':'event','once':True,'wall_members':['left','right'],'start_at':time.time()-10}
            entries=[]
            if scenario=='queued-ha':entries.append(('left',{'message':'HA first','duration':.08,'source':'ha'}))
            for ident,left,width in (('left',0,64),('right',64,128)):
                if scenario=='missing' and ident=='right':continue
                entries.append((ident,{**wall,'wall_width':64 if scenario=='dimensions' and ident=='right' else width,'body':base64.b64encode(studio.slice_artwork(out.getvalue(),left,width)).decode()}))
            with patch('pipeline.WALL_START_LEAD',.02),patch('pipeline.WALL_READY_TIMEOUT',.08 if scenario=='missing' else .5):
                await pipeline.submit(entries)
                await asyncio.wait_for(asyncio.gather(*list(pipeline.jobs.values())),2)
            if scenario in ('unavailable','missing','dimensions'):
                assert writes==[],(scenario,writes)
                assert not pipeline.errors,(scenario,pipeline.errors)
                assert any('skipped' in value.get('warning','').lower() for value in studio.runtime.values())
            elif scenario=='uncertain':
                assert len([row for row in writes if row[0]=='left'])==1,writes
                assert pipeline.errors and all(not cfg['playing'] for cfg in studio.data['devices'].values())
            else:
                assert {row[0] for row in writes}=={'left','right'},(scenario,writes,pipeline.errors,studio.runtime)
                first=[next(row for row in writes if row[0]==ident) for ident in ('left','right')]
                assert abs(first[0][2]-first[1][2])<.04,first
                if scenario=='slow':assert [row[1] for row in writes if row[0]=='left']==[10,30],writes
                if scenario=='queued-ha':assert first[0][2]>=ha[0]+.075,(first,ha)
                if scenario in ('legacy-busy','wire-busy'):assert first[0][2]>=started+.075
                assert not pipeline.errors
                assert .24<=time.monotonic()-min(row[2] for row in first)<.36
            if release_task:await release_task
            await pipeline.close()
    print('Wall timing passed: shared readiness after HA queues, stale planned timestamps, 64/128 panels, frame-deadline catch-up, unavailable/missing peers, and no uncertain-write replay.')

asyncio.run(check())
