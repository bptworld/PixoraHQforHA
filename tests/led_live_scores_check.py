"""Live artwork refreshes every 10s; pre/post-game cards and events are unchanged."""
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
            now[0]=109;assert await s.render(item,64,device_id='panel')==first and len(calls)==1
            now[0]=110;second=await s.render(item,64,device_id='panel')
            assert second!=first and len(calls)==2,'Live cache served stale artwork at ten seconds'
            now[0]=120;third=await s.render(item,64,device_id='panel')
            assert third!=second and not s.is_live_score(item,64,'panel')
            now[0]=150;assert await s.render(item,64,device_id='panel')==third and len(calls)==3,'Final game used live cadence'
        # Live metadata survives disk-cache restoration on app restart.
        restored=instance(Path(folder));restored.run_worker=worker
        key=next(iter(s.cache));s.write_artwork(key,first,25,True)
        with patch('studio.time.time',side_effect=lambda:__import__('os').stat(Path(folder)/'render-cache'/(key+'.image')).st_mtime+1):
            assert await restored.render(item,64,device_id='panel')==first
            assert restored.is_live_score(item,64,'panel')
        s=instance(Path(folder));s.quiet=lambda cfg:False
        for width in (64,128):
            for live in (False,True):
                chunks=[];refreshes=[]
                s.live_sports={s.sports_key(item,width,'panel'):live}
                async def deliver(client,body,width,duration,**kwargs):chunks.append((body,duration));return True
                async def render(*args,**kwargs):
                    assert kwargs.get('fresh') is True;refreshes.append(True);return b'fresh'
                s.deliver=deliver;s.render=render
                with patch('studio.time.monotonic',return_value=0):
                    await s.deliver_score(None,b'initial',width,25,item,'panel')
                assert [duration for body,duration in chunks]==([10,10,5] if live else [25])
                assert len(refreshes)==(2 if live else 0)
                if live:assert chunks[1][0]==b'fresh'
            # Once the game is final, finish the card without further fast polls.
            chunks=[];s.live_sports={s.sports_key(item,width,'panel'):True}
            async def final(*args,**kwargs):
                s.live_sports[s.sports_key(item,width,'panel')]=False;return b'final'
            s.render=final
            with patch('studio.time.monotonic',return_value=0):await s.deliver_score(None,b'live',width,25,item,'panel')
            assert chunks==[(b'live',10),(b'final',15)]
            # A failed read retains the last score; an uncertain panel write never repeats.
            chunks=[];s.live_sports={s.sports_key(item,width,'panel'):True}
            async def unavailable(*args,**kwargs):raise ValueError('Provider unavailable')
            s.render=unavailable
            with patch('studio.time.monotonic',return_value=0):await s.deliver_score(None,b'last-good',width,25,item,'panel')
            assert all(body==b'last-good' for body,duration in chunks) and len(chunks)==3
            async def uncertain(*args,**kwargs):return False
            s.deliver=uncertain
            async def never(*args,**kwargs):raise AssertionError('Uncertain frame was repeated')
            s.render=never
            await s.deliver_score(None,b'last-good',width,25,item,'panel')
        # A card reappearing four seconds after its previous fetch updates in
        # six seconds, rather than resetting the cadence at each deck turn.
        s=instance(Path(folder));s.quiet=lambda cfg:False;now=[4.];chunks=[];refreshes=[]
        key=s.sports_key(item,64,'panel');s.live_sports={key:True};s.live_checked={key:0}
        async def advancing(client,body,width,duration,**kwargs):chunks.append(duration);now[0]+=duration;return True
        async def refreshed(*args,**kwargs):refreshes.append(now[0]);s.live_checked[key]=now[0];return b'fresh'
        s.deliver=advancing;s.render=refreshed
        with patch('studio.time.time',side_effect=lambda:now[0]),patch('studio.time.monotonic',side_effect=lambda:now[0]):
            await s.deliver_score(None,b'prefetched',64,12,item,'panel')
        assert chunks==[6,6] and refreshes==[10]
        chunks.clear();refreshes.clear();now[0]=0;s.live_checked[key]=0
        async def failed(*args,**kwargs):refreshes.append(now[0]);raise ValueError('Provider down')
        s.render=failed
        with patch('studio.time.time',side_effect=lambda:now[0]),patch('studio.time.monotonic',side_effect=lambda:now[0]):
            await s.deliver_score(None,b'last-good',64,25,item,'panel')
        assert chunks==[10,10,5] and refreshes==[10,20],'Failed reads were retried too quickly'
    print('Live scores passed: ten-second fresh cache and on-screen updates, pre/post-game slow mode, live metadata restart persistence, both sizes, provider failure fallback and no uncertain frame replay.')

asyncio.run(check())
