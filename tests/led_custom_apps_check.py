"""Custom metadata never executes; trusted imports persist and render in real workers."""
import asyncio
import base64
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
from unittest.mock import patch

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
                body+b'\nreturn 1\n', body.replace(b'def render(options=None):',b'def render():'),
                body.replace(b'def render(options=None):',b'def render(options, required):'),
                body.replace(b'"maxlength": 80', b'"maxlength": -1'),
                body.replace(b'"maxlength": 80', b'"maxlength": 1.5'),
                body.replace(b'"maxlength": 80', b'"min": 5, "max": 1'),
                body.replace(b'"maxlength": 80', b'"step": 0'),
                body.replace(b'"type": "text", "default": "Hello Pixora", "maxlength": 80', b'"type": "number", "default": 2, "min": 1, "step": 2'),
                body.replace(b'"type": "text", "default": "Hello Pixora", "maxlength": 80', b'"type": "number", "default": 20, "min": 1, "max": 10'),
                body.replace(b'"maxlength": 80', b'"min": '+b'9'*400),
                body.replace(b'"default": True', b'"default": "false"'),
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
        frames={64:[],128:[]}
        delivered={64:asyncio.Event(),128:asyncio.Event()}
        class Panel:
            def __init__(self,session,host,key=''):self.width=int(host);self.key=key
            async def info(self):return {'id':'panel'+str(self.width),'width':self.width,'height':32,'version':'2.0.27','localDecks':True,'active':False,'brightness':60}
            async def request(self,path,payload):
                if path=='/api/frame':
                    rgb=base64.b64decode(payload['rgb']);assert len(rgb)==self.width*32*3
                    frames[self.width].append(rgb);delivered[self.width].set()
                return {}
        data_root=root/'data';data_root.mkdir()
        (data_root/'displays.json').write_text(json.dumps({'displays':[{'id':'panel'+str(width),'name':str(width),'host':str(width),'key':'a'*32,'width':width,'height':32,'version':'2.0.27'} for width in (64,128)]}))
        app = make_app(data_root, root/'ha',Panel, ingress_peer='127.0.0.1')
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
            # Assign and play through the real player and frame transport for both widths.
            for width in (64,128):
                settings={'deck':'custom-test','brightness':60,'quiet':False,'quietStart':'22:00','quietEnd':'06:00','quietBrightness':10}
                response=await client.post('/api/studio/devices/panel'+str(width),json=settings)
                assert response.status==200,await response.text()
                response=await client.post('/api/studio/action',json={'id':'panel'+str(width),'action':'play'})
                assert response.status==200,await response.text()
                await asyncio.wait_for(delivered[width].wait(),10)
                assert (await client.post('/api/studio/action',json={'id':'panel'+str(width),'action':'stop'})).status==200
                settings['deck']=''
                assert (await client.post('/api/studio/devices/panel'+str(width),json=settings)).status==200
            assert (await client.get('/api/studio/creator-brief')).status == 200
            assert (await client.get('/api/studio/custom-starter')).status == 200
            await client.delete('/api/studio/decks/custom-test')
            await studio.store.collect(set())
            assert (studio.store.custom_root/(card['id']+'.py')).exists()
            assert not studio.store.path('addons/'+card['module']+'.py').exists()
            await studio.store.ensure({card['id']})
            assert studio.store.installed(card['id']), 'Unused custom app could not be restored'
            original_hash=studio.store.cards[card['id']]['sourceHash']
            updated=body.replace(b'CARD_VERSION = "1.0.0"',b'CARD_VERSION = "1.1.0"').replace(b'(80, 200, 255)',b'(255, 50, 80)')
            bad=updated+b'\nreturn 1\n'
            assert (await client.post('/api/studio/custom-apps',data=bad,headers={'X-Pixora-Trust-Code':'yes'})).status==400
            assert (studio.store.custom_root/(card['id']+'.py')).read_bytes()==body
            assert (await client.post('/api/studio/custom-apps',data=updated,headers={'X-Pixora-Trust-Code':'yes'})).status==200
            assert studio.store.cards[card['id']]['sourceHash']!=original_hash
            assert studio.store.cards[card['id']]['version']=='1.1.0'
            # A re-added card with the same item identity must not reuse old artwork.
            deck={'id':'custom-test','name':'Updated custom','items':[{'id':'one','card':card['id'],'options':{'message':'A very long display message','bright':True},'duration':10}]}
            assert (await client.post('/api/studio/decks',json=deck)).status==200
            for width in (64,128):
                response=await client.get('/api/studio/preview',params={'deck':'custom-test','item':'one','width':str(width)})
                assert response.status==200,await response.text() if response.status!=200 else ''
                with Image.open(io.BytesIO(await response.read())) as image:
                    new_rgb=image.convert('RGB').tobytes()
                assert new_rgb!=frames[width][0], 'Replacement reused old preview artwork'
                assert any(new_rgb[i]>new_rgb[i+2] for i in range(0,len(new_rgb),3)), 'Updated red artwork did not render'
                delivered[width].clear()
                settings={'deck':'custom-test','brightness':60,'quiet':False,'quietStart':'22:00','quietEnd':'06:00','quietBrightness':10}
                assert (await client.post('/api/studio/devices/panel'+str(width),json=settings)).status==200
                assert (await client.post('/api/studio/action',json={'id':'panel'+str(width),'action':'play'})).status==200
                await asyncio.wait_for(delivered[width].wait(),10)
                assert frames[width][-1]==new_rgb, 'Deck playback used old source after replacement'
                assert (await client.post('/api/studio/action',json={'id':'panel'+str(width),'action':'stop'})).status==200
                settings['deck']=''
                assert (await client.post('/api/studio/devices/panel'+str(width),json=settings)).status==200
            # A complete new Studio instance restores source plus saved options/decks.
            from studio import Studio
            restarted=Studio(app,studio.root,studio.selected,studio.displays)
            restarted.store.session=Downloads()
            restored=restarted.data['decks']['custom-test']['items'][0]
            assert restored['options']==deck['items'][0]['options']
            assert restarted.store.cards[card['id']]['version']=='1.1.0'
            for width in (64,128):
                rendered=await restarted.render(restored,width)
                with Image.open(io.BytesIO(rendered)) as image:assert image.size==(width,32)
            await restarted.shutdown()
            assert (await client.delete('/api/studio/decks/custom-test')).status==200
            assert (await client.delete('/api/studio/custom-apps/'+card['id'])).status == 200
            assert card['id'] not in CardStore(Downloads(),studio.store.root).cards
    print('Custom apps passed: no execution on import, trust gate, metadata limits, persistence/GC, real 64/128 previews, download, real code replacement, fresh preview/playback frames, saved options, deck restart and deletion protection.')


asyncio.run(check())
