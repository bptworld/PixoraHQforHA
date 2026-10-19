"""Provider polling runs on the hub independently of the visible card/browser."""
import asyncio,sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
APP=Path(__file__).resolve().parents[1]/'pixora_led_displays'
sys.path[:0]=[str(APP),str(APP/'custom_components/pixora_local')]
from studio import Studio

async def check():
    for width in (64,128):
        s=Studio.__new__(Studio);now=[0];calls=[]
        s.store=SimpleNamespace(catalog={'commit':'revision'},cards={name:{'id':name,'module':name,'category':'Sports' if name!='clock' else 'Utility'} for name in ('nba','nfl','clock','nba_standings')})
        items=[{'id':name,'card':name,'enabled':True,'options':{},'duration':10} for name in ('nba','nfl','clock','nba_standings')]
        items.append({'id':'disabled','card':'nba','enabled':False})
        s.data={'devices':{'panel':{'playing':True,'deck':'deck'}},'decks':{'deck':{'items':items}}}
        s.runtime={'panel':{'item':'clock','status':'Clock'}}
        s.displays=lambda:[{'id':'panel','width':width}]
        s.quiet=lambda cfg:30<=now[0]<45
        async def render(item,w,**kwargs):
            assert kwargs=={'device_id':'panel','fresh':True},'Background poll touched special-event history'
            calls.append((item['card'],now[0]))
            live=(item['card']=='nba' and now[0]<45) or (item['card']=='nfl' and 60<=now[0]<90)
            if not hasattr(s,'live_sports'):s.live_sports={}
            s.live_sports[s.sports_key(item,w,'panel')]=live
            return b'ready-artwork'
        s.render=render
        async def sleep(seconds):
            now[0]+=seconds
            if now[0]>=121:s.data['devices']['panel']['playing']=False
        with patch('studio.time.monotonic',side_effect=lambda:now[0]),patch('studio.asyncio.sleep',sleep):
            await s.score_monitor('panel')
        assert [at for name,at in calls if name=='nba']==[0,15,45,105],calls
        assert [at for name,at in calls if name=='nfl']==[0,60,75,90],calls
        assert [at for name,at in calls if name=='nba_standings']==[0]
        assert not any(name=='clock' for name,at in calls)
        assert s.runtime['panel']['item']=='clock','Poller changed the visible card'
    # Refresh signals wake the frame hold only after an acknowledged write;
    # no frame POST is cancelled or repeated to redraw new provider data.
    import io
    from PIL import Image
    s=Studio.__new__(Studio);signal=asyncio.Event();sent=[];elapsed=[0]
    out=io.BytesIO();Image.new('RGB',(64,32)).save(out,'PNG')
    async def send(*args,**kwargs):sent.append(True)
    s.send_frame=send
    async def sleep(seconds):
        elapsed[0]+=seconds
        if elapsed[0]>=15:signal.set()
    with patch('studio.asyncio.sleep',sleep),patch('studio.time.monotonic',return_value=0):
        left=await s.deliver(None,out.getvalue(),64,60,refresh_signal=signal)
    assert len(sent)==1 and left==45.0
    print('Background sports passed: hidden cards poll at 15s live / 60s non-live, standings at 300s, both widths, Quiet Hours and pause respected, specials untouched, and new artwork wakes an acknowledged frame hold without duplicate writes.')

asyncio.run(check())
