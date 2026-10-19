"""Live artwork refreshes every 15s; pre/post-game cards and events are unchanged."""
import asyncio,base64,io,json,sys,tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image
APP=Path(__file__).resolve().parents[1]/'pixora_led_displays'
sys.path[:0]=[str(APP),str(APP/'custom_components/pixora_local')]
from studio import Studio

def png(color):
    out=io.BytesIO();Image.new('RGB',(64,32),color).save(out,'PNG');return out.getvalue()

async def check():
    item={'card':'nba','options':{'favoriteTeam':'BOS'},'duration':25}
    cards={'nba':{'id':'nba','module':'nba','name':'NBA','category':'Sports'}}
    def instance(root):
        s=Studio.__new__(Studio);s.root=root;s.cache={};s.refresh_jobs={};s.card_timing={};s.artwork_timing={}
        s.data={'settings':{},'devices':{'panel':{'playing':True}}};s.runtime={};s.renderer_revision='live-scores-v1'
        s.store=SimpleNamespace(root=root/'cards',cards=cards,catalog={'commit':'test'})
        return s
    with tempfile.TemporaryDirectory() as folder:
        s=instance(Path(folder));now=[100.];calls=[];states=[True,True,False]
        async def worker(request):
            calls.append(request)
            return {'body':base64.b64encode(png(('red','green','blue')[min(len(calls)-1,2)])).decode(),'duration':25,'live_sports':states[min(len(calls)-1,2)]}
        s.run_worker=worker
        with patch('studio.time.time',side_effect=lambda:now[0]):
            first=await s.render(item,64,device_id='panel')
            assert s.is_live_score(item,64,'panel')
            now[0]=114;assert await s.render(item,64,device_id='panel')==first and len(calls)==1
            now[0]=115;second=await s.render(item,64,device_id='panel')
            assert second!=first and len(calls)==2,'Live cache served stale artwork at fifteen seconds'
            now[0]=130;third=await s.render(item,64,device_id='panel')
            assert third!=second and not s.is_live_score(item,64,'panel')
            now[0]=150;assert await s.render(item,64,device_id='panel')==third and len(calls)==3,'Final game used live cadence'
        # Live metadata survives disk-cache restoration on app restart.
        restored=instance(Path(folder));restored.run_worker=worker
        key=next(iter(s.cache));s.write_artwork(key,first,25,True)
        with patch('studio.time.time',side_effect=lambda:__import__('os').stat(Path(folder)/'render-cache'/(key+'.image')).st_mtime+1):
            assert await restored.render(item,64,device_id='panel')==first
            assert restored.is_live_score(item,64,'panel')
        # Visible cards read prepared snapshots and never ask providers to refresh.
        for width in (64,128):
            s=instance(Path(folder));s.quiet=lambda cfg:False;chunks=[];reads=[]
            async def cached(*args,**kwargs):
                assert kwargs.get('cached_only') is True and not kwargs.get('fresh')
                reads.append(True);return b'latest' if len(reads)>1 else b'initial'
            async def deliver(client,body,width,duration,**kwargs):
                chunks.append((body,duration))
                if len(chunks)==1:
                    assert 'refresh_signal' in kwargs
                    return 10.0  # background artwork arrives after fifteen seconds
                return True
            s.render=cached;s.deliver=deliver
            await s.deliver_score(None,b'initial',width,25,item,'panel')
            assert chunks==[(b'initial',25),(b'latest',10)] and len(reads)==2
            # An uncertain physical write terminates this card without replay.
            chunks.clear()
            async def uncertain(*args,**kwargs):chunks.append(True);return False
            s.deliver=uncertain
            await s.deliver_score(None,b'initial',width,25,item,'panel')
            assert len(chunks)==1
    print('Live scores passed: fifteen-second freshness, slower final state, restart metadata, prepared-artwork redraw at both sizes, no display-driven provider polling and no uncertain frame replay.')

asyncio.run(check())
