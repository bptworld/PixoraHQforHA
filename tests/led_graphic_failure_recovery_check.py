"""Failed wall graphics never replay, and cannot permanently block quiet hours."""
import asyncio,sys,tempfile
from pathlib import Path
from unittest.mock import AsyncMock,patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'pixora_led_displays'),str(ROOT/'pixora_led_displays/custom_components/pixora_local')]
from studio import Studio
from pipeline import Pipeline
from client import DisplayUnavailable,DisplayWriteUnconfirmed

async def main():
 with tempfile.TemporaryDirectory() as folder:
  class Panel:
   def __init__(self,ident):self.ident=ident;self.active=True;self.brightness=60;self.writes=[];self.offline=False
   async def info(self):
    if self.offline:raise DisplayUnavailable('offline')
    return {'id':self.ident,'active':self.active,'owner':'message','width':64,'brightness':self.brightness}
   async def show(self,message,color,duration):
    self.writes.append(message);raise DisplayWriteUnconfirmed('lost acknowledgment')
   async def request(self,path,payload):
    assert path=='/api/settings';self.brightness=payload['brightness']
  panels={name:Panel(name) for name in ('left','center','right')}
  studio=Studio({'session':None},Path(folder),panels.__getitem__,lambda:[])
  studio.data['devices']={name:{'playing':True,'resume_on_boot':True,'quietBrightness':0} for name in panels}
  studio.quiet=lambda cfg:True
  event={'message':'failed graphic','source':'ha','duration':.01,'event_id':'failed'}
  await studio.pipeline.submit([(name,event) for name in panels])
  await asyncio.gather(*studio.pipeline.jobs.values())
  assert all(cfg['playing'] for cfg in studio.data['devices'].values())
  for name,panel in panels.items():
   assert not await studio.recover_priority_delivery(name)
   assert panel.brightness==0,'Quiet hours blocked by uncertain active graphic'
   assert panel.writes==['failed graphic']
  # Offline and wrong-identity reads cannot release the delivery fence.
  panels['right'].offline=True
  assert not await studio.recover_priority_delivery('right')
  assert not await studio.recover_priority_delivery('right',{'id':'other','active':False})
  panels['right'].offline=False
  # Lease expiry releases all three without replaying any graphic or queued tail.
  for name,panel in panels.items():
   panel.active=False
   await asyncio.wait_for(studio.pipeline.wait_ready(name),2)
   assert name not in studio.pipeline.errors and name not in studio.pipeline.blocked
   assert panel.writes==['failed graphic']
  # A later, distinct event is accepted; historical failed IDs remain consumed.
  for panel in panels.values():panel.show=AsyncMock()
  await studio.pipeline.submit([('right',{**event,'event_id':'next','message':'next graphic'})])
  await studio.pipeline.jobs['right']
  panels['right'].show.assert_awaited_once()
  await studio.pipeline.submit([('right',event)])
  panels['right'].show.assert_awaited_once()
  # Interrupted deliveries from older app versions recover after restart too.
  studio.pipeline.data['inflight']['right']='interrupted';studio.pipeline.persist()
  studio.pipeline=Pipeline(Path(folder),studio)
  studio.data['devices']['right']['playing']=False
  studio.play=AsyncMock()
  await studio.recover_display('right',await panels['right'].info())
  studio.play.assert_awaited_once_with('right')
  assert not studio.pipeline.errors
  # An explicit Pause is never reversed by recovery.
  studio.data['devices']['right']['resume_on_boot']=False
  studio.pipeline.errors['right']='Priority delivery uncertain'
  studio.play.reset_mock()
  await studio.recover_display('right',await panels['right'].info())
  studio.play.assert_not_awaited()
  assert 'right' in studio.pipeline.errors
  # Pause while a status read is in flight also wins, before brightness changes.
  studio.data['devices']['right']['resume_on_boot']=True
  panels['right'].brightness=60
  async def paused_read():
   studio.data['devices']['right']['resume_on_boot']=False
   return {'id':'right','active':False,'brightness':60}
  panels['right'].info=paused_read
  try:await studio.recover_priority_delivery('right')
  except asyncio.CancelledError:pass
  else:raise AssertionError('Pause during status read was ignored')
  assert panels['right'].brightness==60
  await studio.pipeline.close()
asyncio.run(main())
print('Graphic recovery passed: three panels, quiet-off during accepted lease, offline/identity fences, no replay, later events, restart and manual pause.')
