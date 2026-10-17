"""Local studio integration: on-demand cards, shared-file GC, storage and playback failures."""
import asyncio,io,json,subprocess,sys,tempfile
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from aiohttp.test_utils import TestClient,TestServer
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'pixora_led_displays'))
from app import make_app
from card_store import CardStore
SOURCE=Path('D:/planner/.build-tmp/led-public-card-source/cards')
class Content:
 def __init__(self,body):self.body=body
 async def iter_chunked(self,n):
  for start in range(0,len(self.body),8192):yield self.body[start:start+8192]
class Response:
 status=200
 def __init__(self,body):self.content=Content(body)
 async def __aenter__(self):return self
 async def __aexit__(self,*args):pass
class Downloads:
 calls=[];fail=False
 def get(self,url,**kwargs):
  assert url.startswith('https://raw.githubusercontent.com/bptworld/pixora/') and not kwargs['allow_redirects']
  name=url.split('/cards/',1)[1];self.calls.append(name)
  if self.fail:raise ValueError('Download failed')
  return Response(subprocess.check_output(['git','-C',str(SOURCE.parent),'show',json.loads((ROOT/'pixora_led_displays/card_catalog.json').read_text())['commit']+':cards/'+name]))
async def check():
 sent=[]
 class Panel:
  def __init__(self,session,host,key=''):self.host,self.key=host,key
  async def info(self):return {'id':'panel','name':'Kitchen','width':64,'height':32,'version':'2.0.19','localDecks':True,'active':False}
  async def pair(self):self.key='a'*32
  async def request(self,path,payload):
   sent.append((path,payload))
   if path=='/api/frame':raise ValueError('Uncertain frame; not retried')
 with tempfile.TemporaryDirectory() as temp:
  root=Path(temp);config=root/'ha';config.mkdir()
  app=make_app(root/'data',config,Panel,ingress_peer='127.0.0.1')
  async with TestClient(TestServer(app)) as client:
   studio=app['studio'];downloads=Downloads();studio.store.session=downloads
   assert not list(studio.store.root.rglob('*.py')),'Unused cards were installed at startup'
   await client.post('/api/displays',json={'host':'192.168.1.50'})
   async def deck(name,card,ident=None):
    return await client.post('/api/studio/decks',json={'id':ident,'name':name,'items':[{'id':'item','card':card,'options':{'showWeather':False},'duration':1}]})
   response=await deck('Heartbeat first','heartbeat');assert response.status==200,await response.text();heartbeat=(await response.json())['id']
   for width in (64,128):
    response=await client.get('/api/studio/preview',params={'deck':heartbeat,'item':'item','width':str(width)})
    assert response.status==200,await response.text() if response.status!=200 else ''
    with Image.open(io.BytesIO(await response.read())) as image:assert image.size==(width,32) and image.n_frames>1
   assert (await client.delete('/api/studio/decks/'+heartbeat)).status==200
   response=await deck('Clock','clock');assert response.status==200,await response.text();deck1=(await response.json())['id']
   assert studio.store.installed('clock') and (studio.store.root/'card_utils.py').is_file()
   response=await deck('Calendar','clock_calendar');assert response.status==200;deck2=(await response.json())['id']
   assert (await client.delete('/api/studio/decks/'+deck1)).status==200
   assert not (studio.store.root/'addons/clock.py').exists() and (studio.store.root/'card_utils.py').exists()
   assert studio.store.installed('clock_calendar')
   # The actual public clock card renders locally in a subprocess, at both panel widths.
   item=studio.data['decks'][deck2]['items'][0]
   for width in (64,128):
    body=await studio.render(item,width)
    with Image.open(io.BytesIO(body)) as image:assert image.size==(width,32)
   await studio.store.ensure({'alien_march'})
   animated=await studio.render({'card':'alien_march','options':{}},64)
   with Image.open(io.BytesIO(animated)) as image:assert image.size==(64,32) and image.n_frames>1
   await studio.store.collect(studio.used())
   before=json.loads(studio.file.read_text())
   with patch.object(studio,'persist',side_effect=OSError('Disk unavailable')):
    response=await deck('Not saved','clock_calendar',deck2)
    assert response.status==400 and studio.data['decks'][deck2]['name']=='Calendar'
    assert json.loads(studio.file.read_text())==before
   downloads.fail=True
   response=await deck('Broken','alien_march');assert response.status==400
   assert json.loads(studio.file.read_text())==before
   downloads.fail=False
   settings={'deck':deck2,'brightness':60,'quiet':False,'quietStart':'22:00','quietEnd':'06:00','quietBrightness':0}
   assert (await client.post('/api/studio/devices/panel',json=settings)).status==200
   assert (await client.delete('/api/studio/decks/'+deck2)).status==400,'Assigned deck deleted'
   assert (await client.post('/api/studio/action',json={'id':'panel','action':'play'})).status==200
   await asyncio.wait_for(studio.jobs['panel'],10)
   assert len([s for s in sent if s[0]=='/api/frame'])==1
   assert 'Uncertain' in studio.runtime['panel']['error'] and not studio.data['devices']['panel']['playing']
   assert (await client.post('/api/studio/ha-action',json={'id':'panel','action':'stop'})).status==403
   assert (await client.post('/api/studio/ha-action',headers={'Authorization':'Bearer '+'a'*32},json={'id':'other','action':'stop'})).status==400
   assert (await client.post('/api/studio/ha-action',headers={'Authorization':'Bearer '+'a'*32},json={'id':'panel','action':'stop'})).status==200
   settings['deck']='';await client.post('/api/studio/devices/panel',json=settings)
   assert (await client.delete('/api/studio/decks/'+deck2)).status==200
   assert not (studio.store.root/'addons/clock_calendar.py').exists(),'Unused card remained on hub'
   assert (studio.store.root/'card_utils.py').is_file(),'Shared helper was removed'
   assert (studio.store.root/'assets/fonts/Silkscreen-Regular.ttf').is_file(),'Shared font was removed'
   secret='example-private-provider-token'
   response=await client.post('/api/studio/decks',json={'name':'Secret card','items':[{'id':'secret','card':'hubitat','options':{'token':secret},'duration':10}]})
   assert response.status==200
   saved=await response.json();assert secret not in json.dumps(saved)
   assert studio.data['decks'][saved['id']]['items'][0]['options']['token']==secret
   await client.delete('/api/studio/decks/'+saved['id'])
   # A traversal attempt cannot remove files outside the graphics library.
   assert (await client.delete('/api/studio/graphics/not-owned.png')).status==400
   public=await (await client.get('/api/studio')).json()
   assert len(public['cards'])==142 and 'key' not in public['displays'][0]
 print('Studio passed: zero bundled card code, verified downloads, shared dependency GC, real 64/128 renders, rollback, persistence, HA action authentication and no uncertain retries.')
asyncio.run(check())
