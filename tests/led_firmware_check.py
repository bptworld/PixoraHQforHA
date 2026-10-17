"""No hardware is touched: verify release filtering, bounded download and one-shot OTA routes."""
import asyncio
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch
from aiohttp.test_utils import TestClient, TestServer
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'pixora_led_displays'))
from firmware_updates import FirmwareUpdates, MAX_SIZE, verify_restart
from app import make_app
from client import DisplayClient, display_connection

async def check():
    body=bytearray(1024);body[0]=0xe9;body[12:14]=b'\x09\x00';body[32:36]=b'\x32\x54\xcd\xab';body=bytes(body)
    digest=hashlib.sha256(body).hexdigest()
    release={'tag_name':'led-local-v2.0.18','prerelease':True,'assets':[{'name':'pixora-v2.0.18-s3-user-ota-firmware.bin','size':len(body),'digest':'sha256:'+digest}]}
    class Content:
        def __init__(self,body): self.body=body
        async def iter_chunked(self,size):
            for start in range(0,len(self.body),37): yield self.body[start:start+37]
    class Response:
        status=200;headers={}
        def __init__(self,body): self.content=Content(body)
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
    class Session:
        calls=0;bad=False;redirect=False
        def get(self,url,**kwargs):
            assert kwargs['allow_redirects'] is False
            self.calls+=1
            if 'api.github.com' in url:
                # Ignore wrong products and releases missing a trusted digest.
                return Response(json.dumps([{'tag_name':'other-v99.0.0'},release,{'tag_name':'led-local-v3.0.0','assets':[]}]).encode())
            if self.redirect:
                response=Response(b'');response.status=302;response.headers={'Location':'http://192.168.1.1/secret'};return response
            return Response(body+b'x' if self.bad else body)
    session=Session();updates=FirmwareUpdates(session)
    latest=await updates.latest();assert latest['version']=='2.0.18' and latest['preview']
    await updates.latest();assert session.calls==1
    assert await updates.download(latest)==body
    for mode in ('bad','redirect'):
        setattr(session,mode,True)
        try: await updates.download(latest)
        except ValueError: pass
        else: raise AssertionError('Unverified/untrusted firmware accepted')
        setattr(session,mode,False)
    sent=[]
    class Panel:
        def __init__(self,session,host,key=''): self.host,self.key=host,key
        async def info(self): return {'id':'panel','name':'Test','version':'2.0.14','width':64,'height':32}
        async def pair(self): self.key='a'*32
        async def update_firmware(self,body):
            sent.append(body)
            if len(sent)>1: raise ValueError('Uncertain OTA; not retried')
    with tempfile.TemporaryDirectory() as temp:
        folder=Path(temp);config=folder/'ha';config.mkdir()
        app=make_app(folder/'data',config,Panel,ingress_peer='127.0.0.1')
        async with TestClient(TestServer(app)) as client:
            app['firmware_updates'].latest=AsyncMock(return_value=latest)
            app['firmware_updates'].download=AsyncMock(return_value=body)
            assert (await client.post('/api/displays',json={'host':'192.168.1.50'})).status==200
            with patch.object(Panel,'info',AsyncMock(return_value={'id':'panel','version':'2.0.20','width':128,'height':32})):
                fresh=await (await client.get('/api/displays/panel/status')).json()
                assert fresh['display']['width']==128 and fresh['display']['version']=='2.0.20' and 'key' not in fresh['display']
                stored=json.loads((folder/'data'/'displays.json').read_text())['displays'][0]
                assert stored['width']==128 and stored['key']=='a'*32 and stored['host']=='192.168.1.50'
            with patch.object(Panel,'info',AsyncMock(return_value={'id':'wrong','version':'2.0.20','width':64,'height':32})):
                assert (await client.get('/api/displays/panel/status')).status==400
                assert json.loads((folder/'data'/'displays.json').read_text())['displays'][0]['width']==128
            result=await (await client.get('/api/firmware?id=panel')).json()
            result.pop('display');assert result=={'current':'2.0.14','latest':'2.0.18','preview':True,'available':True}
            with patch('app.verify_restart',AsyncMock(return_value={'id':'panel','version':'2.0.18'})) as reconnect:
                response = await client.post('/api/firmware/update?id=panel',json={'version':'2.0.18'})
                assert response.status==200 and len(sent)==1 and (await response.json())['verified']
                reconnect.assert_awaited_once()
            # A lost upload response can still be confirmed using reads only.
            with patch('app.verify_restart',AsyncMock(return_value={'id':'panel','version':'2.0.18'})):
                response=await client.post('/api/firmware/update?id=panel',json={'version':'2.0.18'})
                assert response.status==200 and (await response.json())['verified'] and len(sent)==2
            with patch('app.verify_restart',AsyncMock(return_value=None)):
                response=await client.post('/api/firmware/update?id=panel',json={'version':'2.0.18'})
                assert response.status==400 and len(sent)==3
                assert 'Firmware was not resent' in (await response.json())['error']
            with patch.object(Panel,'info',AsyncMock(side_effect=ValueError('offline'))):
                response=await client.post('/api/firmware/update?id=panel',json={'version':'2.0.18'})
                assert response.status==400 and 'Update not started' in (await response.json())['error'] and len(sent)==3
            app['firmware_updates'].download.side_effect=ValueError('Checksum mismatch')
            assert (await client.post('/api/firmware/update?id=panel',json={'version':'2.0.18'})).status==400 and len(sent)==3
            assert (await client.post('/api/firmware/update?id=unknown')).status==400 and len(sent)==3
            async with app['firmware_updates'].update_lock:
                assert (await client.post('/api/firmware/update?id=panel',json={'version':'2.0.18'})).status==400 and len(sent)==3
    # New client instances for the same panel wait through OTA verification;
    # other displays continue, and nested status reads do not deadlock.
    from aiohttp import ClientSession
    async with ClientSession() as session:
        panel=DisplayClient(session,'192.168.1.50')
        second=DisplayClient(session,'192.168.1.50')
        other=DisplayClient(session,'192.168.1.51')
        panel._request=AsyncMock(return_value={})
        second._request=AsyncMock(return_value={})
        other._request=AsyncMock(return_value={})
        async with display_connection(session,panel.host):
            await panel.request('/api/info')
            pending=asyncio.create_task(second.request('/api/frame',{}))
            await other.request('/api/info')
            await asyncio.sleep(0)
            second._request.assert_not_awaited()
            assert not pending.done()
        await pending
        second._request.assert_awaited_once()
    reconnect=AsyncMock()
    reconnect.info.side_effect=[ValueError('restarting'),{'id':'panel','version':'2.0.17'},{'id':'panel','version':'2.0.18'}]
    result=await verify_restart(reconnect,'panel','2.0.18',wait=AsyncMock())
    assert result['version']=='2.0.18' and reconnect.info.await_count==3
    reconnect.update_firmware.assert_not_called()
    reconnect.info.side_effect=ValueError('offline')
    assert await verify_restart(reconnect,'panel','2.0.18',wait=AsyncMock()) is None
    reconnect.info.side_effect=None
    reconnect.info.return_value={'id':'wrong','version':'2.0.18'}
    try: await verify_restart(reconnect,'panel','2.0.18',wait=AsyncMock())
    except ValueError: pass
    else: raise AssertionError('Wrong panel confirmed after restart')
asyncio.run(check())
print('Firmware updates passed: release selection/cache, chunked download, checksum/size, redirect isolation, selected panel, update serialization and no retries.')
