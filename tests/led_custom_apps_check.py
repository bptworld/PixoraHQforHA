"""Custom metadata never executes; trusted imports persist and render in real workers."""
import asyncio
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from PIL import Image
from aiohttp.test_utils import TestClient, TestServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'pixora_led_displays'))
from app import make_app
from card_store import CardStore
from custom_cards import describe

SOURCE = ROOT/'pixora_led_displays/custom_card_starter.py'
PUBLIC = Path('D:/planner/.build-tmp/led-public-card-source')


class Response:
    status = 200
    def __init__(self, body): self.body = body; self.content = self
    async def iter_chunked(self, size): yield self.body
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass


class Downloads:
    def get(self, url, **kwargs):
        revision, name = url.split('bptworld/pixora/', 1)[1].split('/', 1)
        return Response(subprocess.check_output(['git', '-C', str(PUBLIC), 'show', revision+':'+name]))


async def check():
    body = SOURCE.read_bytes()
    card = describe(body)
    assert card['id'] == 'custom_my_message'
    for bad in [body.replace(b'"my_message"', b'"../escape"'), body.replace(b'CARD_OPTIONS = [', b'CARD_OPTIONS = make_options(['), b'x'*262145,
                body.replace(b'"message", "label"', b'"_width", "label"'), body.replace(b'"text", "default": "Hello Pixora"', b'"password", "default": "secret"')]:
        try: describe(bad)
        except ValueError: pass
        else: raise AssertionError('Invalid custom metadata accepted')
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        marker = root/'must-not-exist'
        # This top-level statement would write a file if import validation ran code.
        probe = body + ('\nfrom pathlib import Path\nPath('+repr(str(marker))+').touch()\n').encode()
        assert describe(probe)['id'] == card['id'] and not marker.exists()
        app = make_app(root/'data', root/'ha', ingress_peer='127.0.0.1')
        async with TestClient(TestServer(app)) as client:
            studio = app['studio']; studio.store.session = Downloads()
            response = await client.post('/api/studio/custom-apps', data=body)
            assert response.status == 400
            assert (await client.post('/api/studio/custom-apps', data=b'x'*262145,headers={'X-Pixora-Trust-Code':'yes'})).status == 400
            response = await client.post('/api/studio/custom-apps', data=probe, headers={'X-Pixora-Trust-Code':'yes'})
            assert response.status == 200, await response.text()
            assert not marker.exists(), 'Import executed code'
            # Replace unused source with the ordinary, side-effect-free starter.
            response = await client.post('/api/studio/custom-apps', data=body, headers={'X-Pixora-Trust-Code':'yes'})
            assert response.status == 200
            await studio.store.collect(set())
            restarted = CardStore(Downloads(), studio.store.root)
            assert restarted.cards[card['id']]['custom']
            assert (restarted.custom_root/(card['id']+'.py')).read_bytes() == body
            downloaded = await client.get('/api/studio/custom-apps/'+card['id'])
            assert await downloaded.read() == body
            assert (await client.delete('/api/studio/custom-apps/clock')).status == 400
            saved = await client.post('/api/studio/decks', json={'id':'custom-test','name':'Custom test','items':[{'id':'one','card':card['id'],'options':{'message':'A very long display message','bright':True},'duration':10}]})
            assert saved.status == 200, await saved.text()
            for width in (64,128):
                response = await client.get('/api/studio/preview',params={'deck':'custom-test','item':'one','width':str(width)})
                assert response.status == 200, await response.text() if response.status != 200 else ''
                artwork=await response.read()
                Path('D:/planner/.build-tmp/led-custom-starter-'+str(width)+'.png').write_bytes(artwork)
                with Image.open(io.BytesIO(artwork)) as image:
                    assert image.size == (width,32)
                    assert image.getbbox() and image.getbbox()[0] >= 0 and image.getbbox()[2] <= width
            assert (await client.post('/api/studio/custom-apps',data=body,headers={'X-Pixora-Trust-Code':'yes'})).status == 400
            assert (await client.delete('/api/studio/custom-apps/'+card['id'])).status == 400
            assert (await client.get('/api/studio/creator-brief')).status == 200
            assert (await client.get('/api/studio/custom-starter')).status == 200
            await client.delete('/api/studio/decks/custom-test')
            await studio.store.collect(set())
            assert (studio.store.custom_root/(card['id']+'.py')).exists()
            assert not studio.store.path('addons/'+card['module']+'.py').exists()
            await studio.store.ensure({card['id']})
            assert studio.store.installed(card['id']), 'Unused custom app could not be restored'
            assert (await client.delete('/api/studio/custom-apps/'+card['id'])).status == 200
            assert card['id'] not in CardStore(Downloads(),studio.store.root).cards
    print('Custom apps passed: no execution on import, trust gate, metadata limits, persistence/GC, real 64/128 previews, download, replacement/deletion protection and restore.')


asyncio.run(check())
