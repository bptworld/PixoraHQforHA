"""Hub artwork cache: ready frames, deduped refresh and stale fallback."""
import asyncio
import hashlib
import io
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image

APP=Path(__file__).resolve().parents[1]/'pixora_led_displays'
sys.path[:0]=[str(APP),str(APP/'custom_components/pixora_local')]
from studio import Studio


async def check():
    image=io.BytesIO();Image.new('RGB',(64,32),'blue').save(image,'PNG');body=image.getvalue()
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp);calls=0;release=asyncio.Event()
        async def ensure(ids):pass
        def instance():
            studio=Studio.__new__(Studio)
            studio.recovery_task=None;studio.recovery_jobs={};studio.graphic_jobs={};studio.graphic_prepared={}
            studio.root=root;studio.cache={};studio.refresh_jobs={};studio.jobs={};studio.card_timing={}
            studio.renderer_revision=hashlib.sha256((APP/'card_worker.py').read_bytes()).hexdigest()
            studio.data={'settings':{}}
            studio.store=SimpleNamespace(root=root/'cards',catalog={'commit':'public-revision'},
                cards={'clock':{'id':'clock','module':'clock','category':'Utility'}},ensure=ensure)
            return studio
        studio=instance()
        async def render(request):
            nonlocal calls
            calls+=1;await release.wait();return body
        studio.render_request=render
        item={'card':'clock','options':{}}
        first=asyncio.create_task(studio.render(item,64));second=asyncio.create_task(studio.render(item,64))
        while calls==0:await asyncio.sleep(0)
        assert calls==1
        release.set();assert await first==await second==body
        assert len(list((root/'render-cache').glob('*.image')))==1
        restored=instance();failed=asyncio.Event()
        async def unavailable(request):failed.set();raise ValueError('Provider unavailable')
        restored.render_request=unavailable
        with patch('studio.time.time',return_value=10**12):
            # A restarted hub can deliver persisted artwork without awaiting the provider.
            assert await restored.render(item,64)==body
            await failed.wait()
            await asyncio.gather(*list(restored.refresh_jobs.values()),return_exceptions=True)
            await asyncio.sleep(0)
            assert next(iter(restored.cache.values()))[1]==body
        # Option changes must not reuse another card configuration's artwork.
        try:await restored.render({'card':'clock','options':{'format':'different'}},64)
        except ValueError:pass
        else:raise AssertionError('Options reused stale artwork from another configuration')
        from studio import CardSkipped
        inactive=instance();skip_calls=0
        async def no_content(request):
            nonlocal skip_calls
            skip_calls+=1;raise CardSkipped('No active game')
        inactive.render_request=no_content
        inactive_item={'card':'clock','options':{'format':'inactive'}}
        for _ in range(2):
            try:await inactive.render(inactive_item,64)
            except CardSkipped:pass
        assert skip_calls==1 and list((root/'render-cache').glob('*.skip'))
        again=instance();again.render_request=no_content
        try:await again.render(inactive_item,64)
        except CardSkipped:pass
        assert skip_calls==1,'Inactive status was lost after hub restart'
        await inactive.shutdown();await again.shutdown()
        await restored.shutdown();await studio.shutdown()
        for i in range(34):restored.write_artwork(str(i),body)
        assert len(list((root/'render-cache').glob('*.image')))==32
    print('Artwork cache passed: deduped cold render, persisted ready frames, failed-provider stale fallback, configuration isolation and bounded disk usage.')


asyncio.run(check())
