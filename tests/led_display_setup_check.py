"""First-install image, private profiles and safe USB job dispatch (no hardware)."""
import asyncio,hashlib,json,sys,tempfile
from pathlib import Path
from unittest.mock import patch
from aiohttp import web
from aiohttp.test_utils import TestClient,TestServer
APP=Path(__file__).resolve().parents[1]/'pixora_led_displays';sys.path.insert(0,str(APP))
from display_setup import DisplayInstaller,IMAGE
async def check():
 with tempfile.TemporaryDirectory() as folder:
  setup=DisplayInstaller(folder)
  a=setup.create({'name':'Living room','ssid':'WiFi, "test"','password':'test12345','width':64})
  b=setup.create({'name':'Wall','ssid':'WiFi, "test"','password':'','reuseWifi':True,'width':128})
  assert setup.profiles[b]['password']=='test12345'
  assert setup.profiles[a]['key']!=setup.profiles[b]['key']
  assert DisplayInstaller(folder).profiles==setup.profiles
  assert 'password' not in setup.public()[0] and 'key' not in setup.public()[0]
  original=IMAGE.read_bytes()
  for ident,width in ((a,64),(b,128)):
   image=setup.image(ident)
   assert len(image)==len(original)==0x800000
   assert image[:0x9000]==original[:0x9000] and image[0xe000:]==original[0xe000:]
   assert b'matrixportal-s3-'+str(width).encode()+b'x32' in image[0x9000:0xe000]
   assert b'test12345' in image[0x9000:0xe000] and setup.profiles[ident]['key'].encode() in image[0x9000:0xe000]
  for data in ({'name':'A','ssid':'B','password':'short','width':64},{'name':'A','ssid':'B','password':'','width':96},{'name':'A','ssid':'B\nC','password':'','width':64}):
   try:setup.create(data)
   except ValueError:pass
   else:raise AssertionError('Invalid setup accepted')
  with patch.object(setup,'ports',return_value=[{'port':'/dev/ttyACM0','label':'S3'}]):
   try:await setup.flash(a,'/tmp/arbitrary')
   except ValueError:pass
   else:raise AssertionError('Unobserved USB path accepted')
   fake=asyncio.Future();setup.tasks[a]=fake
   try:await setup.flash(b,'/dev/ttyACM0')
   except ValueError:pass
   else:raise AssertionError('Concurrent flash accepted')
   fake.set_result(None)
  commands=[]
  class Process:
   returncode=0
   async def communicate(self):return (b'do not expose raw serial output',None)
  async def spawn(*args,**kwargs):
   commands.append(args);assert kwargs.get('shell') is None
   assert 'test12345' not in str(args) and setup.profiles[a]['key'] not in str(args)
   return Process()
  with patch('asyncio.create_subprocess_exec',spawn),patch.object(setup,'image',return_value=b'firmware'),patch.object(setup,'read_ip',return_value='192.168.1.50'):
   setup.jobs[a]={'running':True};await setup._flash(a,'/dev/ttyACM0')
   assert setup.jobs[a]['verified'] and setup.jobs[a]['host']=='192.168.1.50'
   assert len(commands)==2 and 'write-flash' in commands[0] and 'verify-flash' in commands[1]
   Process.returncode=1;commands.clear();setup.jobs[a]={'running':True}
   await setup._flash(a,'/dev/ttyACM0')
   assert setup.jobs[a]['error'] and not setup.jobs[a]['running'] and len(commands)==1
   assert 'raw serial output' not in json.dumps(setup.jobs[a])
  async def attach(profile,host):assert profile['key']==setup.profiles[a]['key'];return {'connected':True}
  @web.middleware
  async def errors(request,handler):
   try:return await handler(request)
   except ValueError as e:return web.json_response({'error':str(e)},status=400)
  app=web.Application(middlewares=[errors]);setup.register(app,attach)
  with patch.object(setup,'ports',return_value=[]):
   async with TestClient(TestServer(app)) as client:
    response=await client.get('/api/setup');result=await response.json()
    assert 'test12345' not in json.dumps(result) and setup.profiles[a]['key'] not in json.dumps(result)
    assert response.headers['Cache-Control']=='no-store'
    response=await client.post('/api/setup/'+a+'/image');body=await response.read()
    assert response.headers['Cache-Control']=='no-store' and hashlib.md5(body).hexdigest()==response.headers['X-Firmware-MD5']
    response=await client.post('/api/setup/'+a+'/flash',json={'port':'/dev/ttyACM0'})
    assert response.status==400
    response=await client.post('/api/setup/'+a+'/finish',json={'host':'192.168.1.50'})
    assert (await response.json())['connected']
    response=await client.delete('/api/setup/'+a);assert response.status==200 and a not in setup.profiles
 # Exercise the real app registration callback, including key mismatch refusal.
 from app import make_app
 class Automation:
  def __init__(self,*args):pass
  async def sync(self,devices):return {'ready':True}
 class Client:
  mismatch=False
  def __init__(self,session,host,key=''):self.host=host;self.key=key
  async def info(self):return {'id':'new-s3','name':'Native','width':64,'height':32,'version':'2.0.27'}
  async def pair(self):
   if self.mismatch:self.key='0'*32
 with tempfile.TemporaryDirectory() as folder:
  root=Path(folder);setup=DisplayInstaller(root)
  ident=setup.create({'name':'Kitchen','ssid':'Test','password':'test12345','width':64})
  with patch('app.HomeAssistantSetup',Automation):
   app=make_app(root,root/'ha',Client,ingress_peer='127.0.0.1')
   async with TestClient(TestServer(app)) as client:
    Client.mismatch=True
    response=await client.post('/api/setup/'+ident+'/finish',json={'host':'192.168.1.50'})
    assert response.status==400 and not (root/'displays.json').exists()
    Client.mismatch=False
    response=await client.post('/api/setup/'+ident+'/finish',json={'host':'192.168.1.50'})
    assert response.status==200,await response.text()
    result=await response.json();assert result['displays'][0]['name']=='Kitchen' and 'key' not in result['displays'][0]
    assert json.loads((root/'displays.json').read_text())['displays'][0]['key']==setup.profiles[ident]['key']
 print('Installer passed: unchanged bootloader/application, correct 64/128 NVS, unique keys, Wi-Fi reuse, persistence, no secret status fields, private download, USB path/concurrency guards and explicit erase confirmation. No device was flashed.')
asyncio.run(check())
