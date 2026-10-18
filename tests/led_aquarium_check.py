"""Exercise pinned aquarium downloads, real HA worker and panel RGB preparation."""
import asyncio, base64, hashlib, io, json, os, subprocess, sys, tempfile
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'pixora_led_displays'
sys.path[:0] = [str(APP), str(APP / 'custom_components/pixora_local')]
from card_store import CardStore
from studio import Studio


async def check(source):
    catalog = json.loads((APP / 'card_catalog.json').read_text())
    card = next(c for c in catalog['cards'] if c['id'] == 'aquarium')
    blobs = {}
    for name in card['files']:
        body = subprocess.check_output(['git', '-C', source, 'show', catalog['commit'] + ':cards/' + name])
        assert hashlib.sha256(body).hexdigest() == catalog['files'][name]['sha256']
        blobs[name] = body

    requested = []
    class Response:
        status = 200
        def __init__(self, body): self.body = body; self.content = self
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def iter_chunked(self, size): yield self.body
    class Session:
        def get(self, url, **kwargs):
            requested.append(url)
            return Response(blobs[url.split('/cards/', 1)[1]])

    with tempfile.TemporaryDirectory() as temp:
        store = CardStore(Session(), Path(temp) / 'cards')
        old = store.path('addons/aquarium.py'); old.parent.mkdir(parents=True)
        old.write_bytes(b'# old still-image version')
        await store.ensure({'aquarium'})
        assert old.read_bytes() == blobs['addons/aquarium.py']
        count = len(requested)
        await store.ensure({'aquarium'})
        assert len(requested) == count, 'Verified downloads should be reused'
        studio = Studio.__new__(Studio)
        for width in (64, 128):
            request = {'root': str(store.root), 'module': 'aquarium', 'width': width,
                       'protocol': 2, 'options': {}, 'settings': {}, 'dwell': 10, 'events': False}
            result = subprocess.run([sys.executable, str(APP / 'card_worker.py')],
                                    input=json.dumps(request).encode(), capture_output=True, timeout=30)
            assert result.returncode == 0, result.stderr.decode()
            body = base64.b64decode(json.loads(result.stdout)['body'])
            with Image.open(io.BytesIO(body)) as image:
                assert image.size == (width, 32) and image.n_frames >= 90
                frames = []
                for n in range(image.n_frames):
                    image.seek(n); frames.append(image.convert('RGB').copy())
                # Track actual colored fish pixels, not just moving bubbles.
                for channel in ((255,170,55), (80,220,255), (255,110,180)):
                    centers = set()
                    for frame in frames:
                        points = [(i % width, i // width) for i, pixel in enumerate(frame.getdata()) if pixel == channel]
                        assert points, 'Fish disappeared from tank'
                        centers.add((round(sum(p[0] for p in points)/len(points)), round(sum(p[1] for p in points)/len(points))))
                    assert len(centers) > 10, 'Fish did not swim'
                preview = Path('D:/planner/.build-tmp') / f'aquarium-{width}.gif'
                enlarged = [frame.resize((width*5, 160), Image.Resampling.NEAREST) for frame in frames]
                enlarged[0].save(preview, save_all=True, append_images=enlarged[1:], duration=100, loop=0)
            ready = await studio.prepared_frames(body, width)
            assert len(ready) >= 90
            assert len({frame.rgb for frame, delay in ready}) > 80
            assert all(len(base64.b64decode(frame.rgb)) == width*32*3 for frame, delay in ready)
            assert 9.9 <= sum(delay for frame, delay in ready) <= 10.1
    print('Aquarium passed: verified stale-card replacement, cached reuse, real HA worker, all three fish swimming at 64/128, and ten seconds of distinct RGB frames.')


asyncio.run(check(sys.argv[1]))
