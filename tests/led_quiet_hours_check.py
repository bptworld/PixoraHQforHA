"""Overnight clock handoff and lost brightness acknowledgments without hardware."""
import asyncio,base64,io,json,sys,tempfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'pixora_led_displays'),str(ROOT/'pixora_led_displays/custom_components/pixora_local')]
import quiet_hours
from studio import Studio
from client import DisplayWriteUnconfirmed
from pipeline import quiet_card,Pipeline

config={'quiet':True,'quietStart':'22:30','quietEnd':'06:00','quietBrightness':10}
zone=ZoneInfo('America/New_York')
assert quiet_hours.active(config,datetime(2026,10,18,22,30,tzinfo=zone))
assert not quiet_hours.active(config,datetime(2026,10,19,6,tzinfo=zone))
assert not quiet_hours.active({**config,'quietEnd':'22:30'},datetime(2026,10,18,23,tzinfo=zone))
assert quiet_hours.boundary(config,datetime(2026,11,1,0,0,tzinfo=zone))==7*3600,'DST overnight boundary'

async def check(width,fail_value,quiet_brightness):
    current=datetime(2026,10,18,22,29,59,tzinfo=zone)
    studio=Studio.__new__(Studio)
    items=[{'id':name,'card':name,'duration':300,'enabled':True} for name in ('first','second')]
    studio.data={'settings':{'timezone':'America/New_York','timeFormat':'12'},'devices':{'panel':{**config,'quietBrightness':quiet_brightness,'deck':'deck','playing':True,'resume_on_boot':True,'brightness':60}},'decks':{'deck':{'items':items}}}
    studio.runtime={};studio.card_timing={}
    studio.store=SimpleNamespace(root=Path('D:/planner/.build-tmp/led-public-card-source/cards'),cards={name:{'name':name} for name in ('first','second')})
    class Panel:
        brightness=60
        writes=[]
        failed=False
        async def info(self):return {'width':width,'brightness':self.brightness,'active':False,'localDecks':True}
        async def request(self,path,payload):
            self.brightness=payload['brightness'];self.writes.append(self.brightness)
            if self.brightness==fail_value and not self.failed:
                self.failed=True;raise DisplayWriteUnconfirmed('Lost response after applying brightness')
    panel=Panel();panel.writes=[];studio.selected=lambda ident:panel
    output=io.BytesIO();Image.new('RGB',(width,32)).save(output,'PNG');body=output.getvalue()
    async def render(*args,**kwargs):return body
    studio.render=render
    phases=[]
    async def deliver(client,body,render_width,duration,**kwargs):
        nonlocal current
        status=studio.runtime['panel']['status'];phases.append(status)
        with Image.open(io.BytesIO(body)) as image:
            assert image.size==(width,32)
            if status.startswith('Quiet'):assert image.getbbox() is not None
        if status=='first':
            assert duration==1,'Long card crosses quiet-hours boundary'
            current=datetime(2026,10,18,22,30,tzinfo=zone)
        elif status.startswith('Quiet'):
            assert panel.brightness==quiet_brightness
            if current.hour==22:current=datetime(2026,10,19,5,59,59,tzinfo=zone)
            else:
                assert duration==1
                current=datetime(2026,10,19,6,tzinfo=zone)
        elif status=='second':
            assert panel.brightness==60
            raise asyncio.CancelledError
        else:raise AssertionError(status)
        await original_sleep(0)
    studio.deliver=deliver
    async def save():pass
    studio.save=save
    original_sleep=asyncio.sleep
    async def sleep(_):await original_sleep(0)
    with patch('quiet_hours.now',lambda settings:current),patch('studio.asyncio.sleep',sleep):
        try:await studio.player('panel')
        except asyncio.CancelledError:pass
    quiet_status='Quiet hours · Off' if quiet_brightness==0 else 'Quiet hours · Clock'
    assert phases==['first',quiet_status,quiet_status,'second'],phases
    assert panel.writes==[quiet_brightness,60],panel.writes
    assert studio.data['devices']['panel']['playing'] and 'last_error' not in studio.data['devices']['panel']
    # Saving settings must preserve an existing pause as well as running state.
    async def mutate(fn):fn()
    studio.mutate=mutate
    for playing in (True,False):
        studio.data['devices']['panel']['playing']=playing
        await studio.save_display_settings('panel',{**config,'brightness':60,'quietBrightness':0})
        assert studio.data['devices']['panel']['playing'] is playing
        assert studio.data['devices']['panel']['quietBrightness']==0
        assert studio.data['devices']['panel']['resume_on_boot'] is True
    studio.quiet=lambda cfg:cfg.get('quiet',False)
    studio.data['devices']['other']={'quiet':False}
    assert quiet_card(studio,'other',{'source':'event','wall_members':['other','panel']})
    assert not quiet_card(studio,'panel',{'source':'ha'})

async def main():
    for width in (64,128):
        for brightness in (0,10):
            for value in (None,brightness,60):await check(width,value,brightness)
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder)
        saved={'devices':{'off':{**config,'quietBrightness':0},'clock':config},'decks':{},'settings':{}}
        (root/'studio.json').write_text(json.dumps(saved),encoding='utf-8')
        studio=Studio({'session':None},root,lambda ident:None,lambda:[])
        assert studio.data['devices']['off']['quietBrightness']==0,'Restart changed explicit off setting'
        assert studio.data['devices']['clock']['quietBrightness']==10
        writes=[]
        class SettingsPanel:
            async def info(self):return {'localDecks':True,'brightness':10}
            async def request(self,path,payload):writes.append(payload['brightness'])
        studio.selected=lambda ident:SettingsPanel()
        studio.quiet=lambda cfg:True
        await studio.save_display_settings('off',{**config,'quietBrightness':0})
        assert writes==[0],'Saving zero during Quiet Hours did not turn panel off'
        restored=Studio({'session':None},root,lambda ident:None,lambda:[])
        assert restored.data['devices']['off']['quietBrightness']==0
    with tempfile.TemporaryDirectory() as folder:
        calls=[]
        class Panel:
            async def info(self):return {'width':64,'active':False}
            async def show(self,message,*args):calls.append(message)
        async def deliver(*args,**kwargs):raise AssertionError('Quiet card graphic was delivered')
        studio=SimpleNamespace(selected=lambda ident:Panel(),quiet=lambda cfg:cfg.get('quiet',False),
            data={'devices':{'panel':{'quiet':True,'playing':True}}},runtime={},deliver=deliver)
        pipeline=Pipeline(Path(folder),studio)
        event={'body':base64.b64encode(b'never decode').decode(),'duration':1,'source':'event','event_id':'quiet-event'}
        await pipeline.submit([('panel',event),('panel',{'message':'HA alert','duration':.01,'source':'ha'})])
        await pipeline.jobs['panel']
        assert calls==['HA alert'] and not pipeline.errors
        assert studio.data['devices']['panel']['playing']
        studio.data['devices']['panel']['quiet']=False
        await pipeline.submit([('panel',event)])
        assert calls==['HA alert'],'Quiet-hour event replayed in the morning'
asyncio.run(main())
print('Quiet Hours passed: off at 0% or clock at 10%, both sizes, midnight/DST, next-card resume, lost response reconciliation without duplicate writes, settings state and event suppression.')
