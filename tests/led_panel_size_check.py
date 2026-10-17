"""Panel-size correction preserves identity/settings and never retries a write."""
import asyncio,json,sys,tempfile
from pathlib import Path
from unittest.mock import patch,AsyncMock
from aiohttp.test_utils import TestClient,TestServer
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'pixora_led_displays'))
import app as module
from firmware_updates import verify_panel_size

async def check():
    class Panel:
        width=64;supported=True;uncertain=False;wrong=False;writes=[]
        def __init__(self,session,host,key=''):self.host,self.key=host,key
        async def info(self):return {'id':'wrong' if self.wrong else 'panel','width':self.width,'height':32,'version':'2.0.20','panelConfiguration':self.supported}
        async def pair(self):self.key='a'*32
        async def request(self,path,payload):
            assert path=='/api/panel';self.writes.append(payload);Panel.width=payload['width']
            if self.uncertain:raise ValueError('Uncertain size change; not retried')
            return {'accepted':True}
    async def verify(client,ident,width):return await client.info()
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp);config=root/'config';config.mkdir()
        app=module.make_app(root/'data',config,Panel,ingress_peer='127.0.0.1')
        async with TestClient(TestServer(app)) as client:
            assert (await client.post('/api/displays',json={'host':'192.168.4.91','name':'Center-128'})).status==200
            before=json.loads((root/'data/displays.json').read_text())['displays'][0]
            app['studio'].data['devices']['panel']={'playing':True}
            with patch.object(module,'verify_panel_size',side_effect=verify),patch.object(app['studio'],'play',new_callable=AsyncMock) as play:
                response=await client.post('/api/displays/panel/panel',json={'width':128})
                assert response.status==200,await response.text()
                result=await response.json();assert result['verified'] and result['displays'][0]['width']==128
                play.assert_awaited_once_with('panel')
                after=json.loads((root/'data/displays.json').read_text())['displays'][0]
                assert all(after[key]==before[key] for key in ('id','name','host','key'))
                play.reset_mock();count=len(Panel.writes)
                assert (await client.post('/api/displays/panel/panel',json={'width':128})).status==200
                assert len(Panel.writes)==count;play.assert_not_awaited()
            for width in (True,32,129,'128'):
                assert (await client.post('/api/displays/panel/panel',json={'width':width})).status==400
            Panel.supported=False;count=len(Panel.writes)
            assert (await client.post('/api/displays/panel/panel',json={'width':64})).status==400
            assert len(Panel.writes)==count;Panel.supported=True
            with patch.object(module,'verify_panel_size',new=AsyncMock(return_value=None)):
                response=await client.post('/api/displays/panel/panel',json={'width':64})
                assert response.status==200 and not (await response.json())['verified']
                assert len(Panel.writes)==count+1
                assert json.loads((root/'data/displays.json').read_text())['displays'][0]['width']==128
            Panel.uncertain=True;count=len(Panel.writes)
            assert (await client.post('/api/displays/panel/panel',json={'width':128})).status==400
            assert len(Panel.writes)==count+1
            Panel.uncertain=False;Panel.wrong=True;count=len(Panel.writes)
            assert (await client.post('/api/displays/panel/panel',json={'width':64})).status==400
            assert len(Panel.writes)==count
    delays=[]
    async def wait(seconds):delays.append(seconds)
    Panel.wrong=False;Panel.width=128
    assert (await verify_panel_size(Panel(None,'host'),'panel',128,wait))['width']==128 and delays==[3]
    print('Panel size passed: 64 to 128, unchanged Wi-Fi identity/key/name, no-op saves, old firmware, invalid input, unverified restart, wrong device and no uncertain retries.')

asyncio.run(check())
