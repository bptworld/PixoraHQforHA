"""Pre-uninstall cleanup with isolated files and mocked HA responses."""
import asyncio
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pixora_led_displays'))
from app import make_app
from automation import HomeAssistantSetup


async def checks():
    with tempfile.TemporaryDirectory() as temp:
        base = Path(temp)
        data, config = base/'data', base/'ha'
        data.mkdir(); config.mkdir()
        (data/'studio.json').write_text('{"decks":{},"devices":{},"groups":{},"graphics":{},"settings":{}}')
        (data/'options.json').write_text('{}')
        for name in ('downloaded-cards', 'graphics', 'action-backups'):
            (data/name).mkdir(); (data/name/'private').write_text('remove')
        target = config/'custom_components'/'pixora_local'
        target.mkdir(parents=True); (target/'test.py').write_text('remove')
        other = config/'custom_components'/'other'
        other.mkdir(); (other/'keep.py').write_text('keep')
        (config/'.pixora-led-ha-version').write_text('1.2.0')
        calls = []
        remaining = [{'domain':'pixora_local','entry_id':'panel'}, {'domain':'other','entry_id':'keep'}]
        fail = True

        async def request(self, method, path, payload=None):
            nonlocal fail
            calls.append((method,path))
            if fail: raise ValueError('HA unavailable')
            if path == 'discovery': return {'result':'ok','data':{'uuid':'owned'}}
            if path == 'discovery/owned': return {'result':'ok'}
            if method == 'GET': return list(remaining)
            assert path.endswith('/panel')
            remaining[:] = [e for e in remaining if e['entry_id'] != 'panel']
            return {'require_restart':False}

        with patch.object(HomeAssistantSetup, 'cleanup_request', request):
            app = make_app(data, config, ingress_peer='127.0.0.1')
            client = TestClient(TestServer(app)); await client.start_server()
            try:
                response = await client.post('/api/cleanup', json={'confirmation':'wrong'})
                assert response.status == 400 and not (data/'.cleanup-started').exists()
                response = await client.post('/api/cleanup', json={'confirmation':'REMOVE'})
                assert response.status == 400 and target.exists()
                assert (data/'.cleanup-started').exists()
                assert (await client.post('/api/install-actions',json={})).status == 400
                fail = False
                response = await client.post('/api/cleanup', json={'confirmation':'REMOVE'})
                assert response.status == 200, await response.text()
                assert not target.exists() and (other/'keep.py').exists()
                assert not (config/'.pixora-led-ha-version').exists()
                assert {p.name for p in data.iterdir()} == {'.cleanup-started','options.json'}
                assert remaining == [{'domain':'other','entry_id':'keep'}]
                assert (await client.get('/api/studio')).status == 400
            finally: await client.close()
            # Restart must not reinstall companion files or resume playback.
            restarted = make_app(data, config, ingress_peer='127.0.0.1')
            client = TestClient(TestServer(restarted)); await client.start_server()
            try:
                assert not target.exists()
                assert (await client.post('/api/cleanup',json={'confirmation':'REMOVE'})).status == 200
            finally: await client.close()
        assert ('DELETE','discovery/owned') in calls
        print('Cleanup passed: confirmation, partial failure/retry, HA scope, file deletion, restart inhibition and idempotence.')


asyncio.run(checks())
