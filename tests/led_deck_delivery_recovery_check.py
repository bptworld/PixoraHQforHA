"""Lost frame replies recover without replaying frames or overriding user intent."""
import asyncio,sys,tempfile
from pathlib import Path
from unittest.mock import AsyncMock,patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'pixora_led_displays'),str(ROOT/'pixora_led_displays/custom_components/pixora_local')]
from studio import Studio,PanelFrame
from client import DisplayUnavailable,DisplayWriteUnconfirmed

async def main():
 with tempfile.TemporaryDirectory() as folder:
  client=type('Client',(),{})()
  studio=Studio({'session':object()},Path(folder),lambda ident:client,lambda:[])
  studio.data['devices']['panel']={'playing':True}
  statuses=[DisplayUnavailable('offline'),{'id':'panel','active':True,'owner':'deck'},
            {'id':'panel','active':False,'owner':''}]
  client.info=AsyncMock(side_effect=statuses)
  client.request=AsyncMock(side_effect=DisplayWriteUnconfirmed('lost response'))
  studio.prepared_frames=AsyncMock(return_value=[(PanelFrame('pixels'),1)])
  with patch('studio.asyncio.sleep',AsyncMock()):
   await studio.deliver(client,b'card',64,10,ident='panel')
  assert client.request.await_count==1,'Uncertain frame was resent'
  assert client.info.await_count==3,'Accepted frame was not reconciled'
  assert studio.data['devices']['panel']['playing']
  assert 'panel' not in studio.pipeline.blocked and 'panel' not in studio.pipeline.errors
  assert 'next card' in studio.runtime['panel']['status']
  # The next card can use the normal serialized wire after reconciliation.
  client.request=AsyncMock(return_value={'accepted':True})
  await studio.send_frame(client,PanelFrame('next'),64,10,ident='panel')
  assert client.request.await_count==1
  assert client.request.await_args.args[1]['rgb']=='next'
  # A pause while reconnecting cancels recovery; it must not resume delivery.
  studio.pipeline.blocked.add('panel')
  async def paused():
   studio.data['devices']['panel']['playing']=False
   raise DisplayUnavailable('offline')
  client.info=paused
  with patch('studio.asyncio.sleep',AsyncMock()):
   try:await studio.recover_deck_delivery('panel',client)
   except asyncio.CancelledError:pass
   else:raise AssertionError('Manual pause ignored')
  assert 'panel' in studio.pipeline.blocked
  # Never clear an uncertain priority-message error as deck recovery.
  studio.data['devices']['panel']['playing']=True
  studio.pipeline.errors['panel']='Priority delivery uncertain'
  client.info=AsyncMock(return_value={'id':'panel','active':False})
  try:await studio.recover_deck_delivery('panel',client)
  except ValueError:pass
  else:raise AssertionError('Priority error cleared')
  assert studio.pipeline.errors['panel']=='Priority delivery uncertain'
  # A different controller at the same IP cannot authorize continuation.
  client.info=AsyncMock(return_value={'id':'other','active':False})
  try:await studio.recover_deck_delivery('panel',client)
  except ValueError:pass
  else:raise AssertionError('Different controller accepted')
  # Exercise the real player: failure in card one advances to card two.
  import io
  from PIL import Image
  studio.pipeline.errors.clear();studio.pipeline.blocked.clear()
  studio.data['devices']['panel']={'playing':True,'deck':'deck'}
  studio.data['decks']['deck']={'items':[{'id':name,'card':name,'enabled':True,'duration':10} for name in ('first','second')]}
  studio.store.cards={name:{'name':name,'module':name} for name in ('first','second')}
  png=io.BytesIO();Image.new('RGB',(64,32)).save(png,format='PNG')
  studio.render=AsyncMock(return_value=png.getvalue())
  studio.prepared_frames=AsyncMock(side_effect=[[(PanelFrame('first'),1)],[(PanelFrame('second'),1)]])
  client.info=AsyncMock(return_value={'id':'panel','active':False,'width':64,'brightness':60})
  writes=[]
  async def frame(path,payload):
   writes.append(payload['rgb'])
   if len(writes)==1:raise DisplayWriteUnconfirmed('lost reply')
   raise asyncio.CancelledError
  client.request=frame
  try:await studio.player('panel')
  except asyncio.CancelledError:pass
  assert writes==['first','second'],writes
  assert studio.data['devices']['panel']['playing']
asyncio.run(main())
print('Deck recovery passed: one-shot delivery, offline reads, accepted lease expiry, next frame, manual pause, priority error and identity checks.')
