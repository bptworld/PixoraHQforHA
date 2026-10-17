"""Local LED app integration checks. No Cloud, hardware, or HA data is touched."""
import asyncio
import base64
import importlib.util
import io
import json
import sys
import tempfile
from unittest.mock import patch
from pathlib import Path
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'pixora_led_displays'
sys.path.insert(0, str(APP))
spec = importlib.util.spec_from_file_location('led_app', APP / 'app.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
from client import DisplayClient, local_host


async def checks():
    calls = []
    class Panel:
        def __init__(self, session, host, key=''):
            self.host, self.key = local_host(host), key
        async def info(self):
            return {'id': 'panel1', 'name': 'Kitchen', 'width': 64, 'height': 32, 'version': '2.0.14'}
        async def pair(self):
            self.key = 'a' * 32
        async def show(self, message, color, duration):
            calls.append(('text', message, color, duration))
            if message == 'uncertain':
                raise ValueError('Could not confirm delivery. The request was not retried.')
        async def update_firmware(self, body):
            calls.append(('firmware', len(body)))
        async def request(self, path, payload):
            calls.append((path, payload))

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        config = root / 'ha'
        config.mkdir()
        app = module.make_app(root / 'data', config, Panel, ingress_peer='127.0.0.1')
        async with TestClient(TestServer(app)) as client:
            app["studio"].pipeline.start=lambda ident:None
            assert (await client.post('/api/show', json=[])).status == 400
            assert (await client.post('/api/displays', json={'host': '8.8.8.8'})).status == 400
            response = await client.post('/api/displays', json={'host': '192.168.1.50', 'name': 'Kitchen'})
            data = await response.json()
            assert response.status == 200 and 'key' not in data['displays'][0]
            assert json.loads((root / 'data/displays.json').read_text())['displays'][0]['key'] == 'a' * 32
            assert (await client.post('/api/show', json={'id': 'panel1', 'message': 'Done', 'duration': 10})).status == 200
            assert app['studio'].pipeline.data['queues']['panel1'][-1]['message']=='Done'
            count = len(calls)
            response = await client.post('/api/show', json={'id': 'panel1', 'message': 'uncertain'})
            assert response.status == 200 and len(calls) == count
            assert app['studio'].pipeline.data['queues']['panel1'][-1]['message']=='uncertain'
            assert (await client.post('/api/show', json={'id': 'panel1', 'message': 'bad', 'duration': 0})).status == 400
            assert (await client.post('/api/show', json={'id': 'missing', 'message': 'bad'})).status == 400
            image = io.BytesIO()
            Image.new('RGB', (128, 64), 'red').save(image, format='PNG')
            assert (await client.post('/api/image?id=panel1&duration=5', data=image.getvalue())).status == 200
            payload=app['studio'].pipeline.data['queues']['panel1'][-1]
            with Image.open(io.BytesIO(base64.b64decode(payload['body']))) as queued:assert queued.size==(64,32)
            assert payload['duration'] == 5
            app['studio'].pipeline.data['queues']['panel1']=[]
            app['studio'].pipeline.persist()
            assert (await client.post('/api/image?id=panel1', data=b'bad')).status == 400
            assert (await client.post('/api/update?id=panel1', data=b'test firmware')).status == 200
            assert calls[-1] == ('firmware', 13)
            assert (await client.post('/api/show', json={}, headers={'Sec-Fetch-Site': 'cross-site'})).status == 403
            assert (await client.post('/api/install-actions', json={})).status == 200
            assert (config / 'custom_components/pixora_local/manifest.json').is_file()
            (config / 'custom_components/pixora_local/old.py').write_text('# obsolete')
            # Updates preserve unrelated HA integrations and back up the previous Pixora copy.
            sentinel = config / 'custom_components/other.txt'
            sentinel.write_text('keep')
            assert (await client.post('/api/install-actions', json={})).status == 200
            assert sentinel.read_text() == 'keep' and list((root / 'data/action-backups').iterdir())
        restarted = module.make_app(root / 'data', config, Panel, ingress_peer='127.0.0.1')
        async with TestClient(TestServer(restarted)) as client:
            assert (await (await client.get('/api/displays')).json())['displays'][0]['name'] == 'Kitchen'
            response = await client.patch('/api/displays/panel1', json={'name': ' Left display '})
            assert response.status == 200
            assert (await response.json())['displays'][0]['name'] == 'Left display'
            assert 'key' not in (await (await client.get('/api/displays')).json())['displays'][0]
            for name in ['', '  ', 'x' * 81, None]:
                assert (await client.patch('/api/displays/panel1', json={'name': name})).status == 400
            assert (await client.patch('/api/displays/missing', json={'name': 'Other'})).status == 404
            assert (await client.delete('/api/displays/missing')).status == 404
            assert (await client.delete('/api/displays/panel1', headers={'Sec-Fetch-Site': 'cross-site'})).status == 403
            before = json.loads((root / 'data/displays.json').read_text())
            with patch.object(module.os, 'replace', side_effect=OSError('Disk unavailable')):
                assert (await client.patch('/api/displays/panel1', json={'name': 'Lost name'})).status == 400
                assert (await client.delete('/api/displays/panel1')).status == 400
            assert (await (await client.get('/api/displays')).json())['displays'][0]['name'] == 'Left display'
            assert json.loads((root / 'data/displays.json').read_text()) == before
            assert (await client.delete('/api/displays/panel1')).status == 200
            assert (await (await client.get('/api/displays')).json())['displays'] == []
            assert (await client.post('/api/show', json={'id': 'panel1', 'message': 'No longer saved'})).status == 400
        removed = module.make_app(root / 'data', config, Panel, ingress_peer='127.0.0.1')
        async with TestClient(TestServer(removed)) as client:
            assert (await (await client.get('/api/displays')).json())['displays'] == []
        full = [{'id': 'panel1' if i == 0 else 'other'+str(i), 'host':'192.168.1.50', 'name':'Existing '+str(i), 'key':'b'*32, 'width':64,'height':32,'version':'2.0.14'} for i in range(30)]
        (root / 'data/displays.json').write_text(json.dumps({'displays':full}))
        class ReconnectPanel(Panel):
            async def pair(self):
                assert self.key == 'b'*32
        async with TestClient(TestServer(module.make_app(root / 'data', config, ReconnectPanel, ingress_peer='127.0.0.1'))) as client:
            response = await client.post('/api/displays', json={'host':'192.168.1.60','name':''})
            assert response.status == 200
            saved = (await response.json())['displays']
            assert len(saved) == 30 and saved[-1]['name'] == 'Existing 0' and saved[-1]['host'] == '192.168.1.60'
        async with TestClient(TestServer(module.make_app(root / 'data', config, Panel))) as client:
            assert (await client.get('/api/displays')).status == 403

    # Real client transport goes only to the chosen panel, and never retries an uncertain write.
    class Response:
        status = 202
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def json(self): return {'accepted': True}
    class Session:
        def request(self, method, url, **kwargs):
            calls.append((method, url, kwargs))
            return Response()
    for host in (None, [], 123, '240.0.0.1', '127.0.0.1', '169.254.1.1', '8.8.8.8'):
        try: local_host(host)
        except ValueError: pass
        else: raise AssertionError('Invalid panel address accepted')
    class RejectedResponse(Response):
        async def json(self): return {'accepted': False}
    class RejectedSession:
        def request(self, *args, **kwargs): return RejectedResponse()
    try: await DisplayClient(RejectedSession(), '192.168.1.50').show('Done', [255,255,255], 10)
    except ValueError as exc: assert 'did not confirm' in str(exc)
    else: raise AssertionError('Missing acknowledgement reported as delivered')
    client = DisplayClient(Session(), '192.168.1.50', 'a' * 32)
    await client.show('Washer finished', [0, 255, 0], 10)
    assert calls[-1][1] == 'http://192.168.1.50/api/message'
    assert calls[-1][2]['json']['color'] == '00FF00' and not calls[-1][2]['allow_redirects']
    for message in ['', 'a' * 161, '\u2603']:
        try: await client.show(message, [255, 255, 255], 10)
        except ValueError: pass
        else: raise AssertionError('Invalid text accepted')
    class UpdateResponse(Response):
        status=200
        async def json(self): return {'updated':True}
    class UpdateSession:
        def post(self,*args,**kwargs):
            calls.append('update')
            return UpdateResponse()
    ota=bytearray(1024);ota[0]=0xe9;ota[12:14]=b'\x09\x00'
    updater=DisplayClient(UpdateSession(),'192.168.1.50','a'*32)
    try: await updater.update_firmware(bytes(ota))
    except ValueError: pass
    else: raise AssertionError('Bootloader/factory header accepted as application OTA')
    ota[32:36]=b'\x32\x54\xcd\xab'
    await updater.update_firmware(bytes(ota))
    assert calls[-1]=='update'
    class TimeoutSession:
        def request(self, *args, **kwargs):
            calls.append('timeout')
            raise asyncio.TimeoutError()
    before = calls.count('timeout')
    try: await DisplayClient(TimeoutSession(), '192.168.1.50', 'a'*32).show('Done', [255,255,255], 10)
    except ValueError as exc: assert 'not retried' in str(exc)
    else: raise AssertionError('Uncertain delivery reported as accepted')
    assert calls.count('timeout') == before + 1


asyncio.run(checks())
print('LED app checks passed: pairing, key privacy/persistence, text/images, no Cloud calls, no uncertain retries, ingress isolation, safe action installation and restart recovery.')

# Local image rendering covers both S3 sizes and transparent graphics.
for width in (64,128):
    image=io.BytesIO();Image.new('RGBA',(20,20),(255,0,0,0)).save(image,format='PNG')
    payload=module.image_payload(image.getvalue(),width,32,10)
    pixels=base64.b64decode(payload['rgb'])
    assert len(pixels)==width*32*3 and not any(pixels)
print('S3 image checks passed: 64/128 widths, RGB sizes and transparent backgrounds.')
