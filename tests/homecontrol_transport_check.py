"""Run the packaged app against local HTTP/WebSocket HA and Pixora simulators."""
import asyncio
import importlib.util
from pathlib import Path
import time
import hashlib
import io
import json
import logging
import os
import tempfile
from unittest.mock import patch
from aiohttp import web, ClientSession

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('addon', root / 'pixora_home_control' / 'app.py')
addon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(addon)

async def check(unified=True):
    application = web.Application()
    state = {'entity_id': 'binary_sensor.contact', 'state': 'on', 'attributes': {}}
    commands = []
    delivered = asyncio.Event()
    results = {}
    attempts = 0
    local_attempts = 0

    async def api(request):
        assert request.headers['Authorization'] == 'Bearer local-supervisor-token'
        if request.method == 'POST':
            commands.append(await request.json())
            return web.json_response([])
        # Real HA catalog bodies can arrive across several network reads.
        response = web.StreamResponse(headers={'Content-Type': 'application/json'})
        await response.prepare(request)
        body = __import__('json').dumps([state]).encode()
        await response.write(body[:20])
        await asyncio.sleep(0.05)
        await response.write(body[20:])
        await response.write_eof()
        return response

    async def ha_socket(request):
        nonlocal local_attempts
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        local_attempts += 1
        if local_attempts == 1:
            # A local HA restart during greeting must also reconnect safely.
            await ws.close(code=1001)
            return ws
        await ws.send_json({'type': 'auth_required'})
        auth = await ws.receive_json()
        assert auth['access_token'] == 'local-supervisor-token'
        await ws.send_json({'type': 'auth_ok'})
        if unified:
            subscribe = await ws.receive_json()
            assert subscribe == {'id':3,'type':'subscribe_events'}
            # A state event received before the subscription acknowledgement survives.
            await ws.send_json({'id':3,'type':'event','event':{'event_type':'state_changed','data':{'entity_id':state['entity_id'],'new_state':state,'old_state':{**state,'state':'off'}}}})
            await ws.send_json({'id':3,'type':'result','success':True})
            await ws.send_json({'id':3,'type':'event','event':{'event_type':'lutron_caseta_button_event','time_fired':'2026-10-09T20:00:00Z','data':{'device_id':'a'*32,'button_type':'on','action':'press'}}})
            await ws.send_json({'id':3,'type':'event','event':{'event_type':'pixora_test_event','data':{'value':42}}})
        else:
            subscribe = await ws.receive_json()
            assert subscribe['type'] == 'subscribe_events' and subscribe['event_type'] == 'state_changed'
            await ws.send_json({'id': 1, 'type': 'result', 'success': True})
            await ws.send_json({'id': 1, 'type': 'event', 'event': {'event_type': 'state_changed', 'data': {'entity_id': state['entity_id'], 'new_state': state, 'old_state': {**state, 'state': 'off'}}}})
            lutron=await ws.receive_json()
            assert lutron['event_type']=='lutron_caseta_button_event'
            await ws.send_json({'id':2,'type':'result','success':True})
            await ws.send_json({'id':2,'type':'event','event':{'event_type':'lutron_caseta_button_event','time_fired':'2026-10-09T20:00:00Z','data':{'device_id':'a'*32,'button_type':'on','action':'press'}}})
            all_events=await ws.receive_json()
            assert all_events['id']==3 and 'event_type' not in all_events
            await ws.send_json({'id':3,'type':'result','success':True})
            await ws.send_json({'id':3,'type':'event','event':{'event_type':'pixora_test_event','data':{'value':42}}})
        async for frame in ws:
            message = __import__('json').loads(frame.data)
            await ws.send_json({'type': 'result', 'id': message['id'], 'success': True, 'result': []})
        return ws

    async def cloud_socket(request):
        nonlocal attempts
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        auth=await ws.receive_json()
        assert auth['credential']=='paired-app-credential' and auth['eventStream']=='unified'
        attempts += 1
        if attempts == 1:
            # Exact production failure: close frame instead of auth_ok.
            await ws.close(code=1008, message=b'private-peer-reason')
            return ws
        await ws.send_json({'type':'auth_ok',**({'eventStream':'unified'} if unified else {})})
        ready = await ws.receive()
        if ready.type != addon.aiohttp.WSMsgType.TEXT:
            return ws
        assert json.loads(ready.data)['type'] == 'ready'
        if unified:
            event = await ws.receive_json()
            assert event['type']=='ha_event' and event['data']['event_type']=='state_changed' and event['data']['data']['new_state']['state']=='on'
            pico=await ws.receive_json()
            assert pico['type']=='ha_event' and pico['data']['event_type']=='lutron_caseta_button_event'
            assert pico['data']['data']['button_type']=='on'
        else:
            event = await ws.receive_json()
            assert event['type'] == 'event' and event['data']['new_state']['state'] == 'on'
            pico=await ws.receive_json()
            assert pico['data']['entity_id']=='event.lutron_'+'a'*32
            assert pico['data']['new_state']['attributes']['event_type']=='on:press'
        raw=await ws.receive_json()
        assert raw['type']=='ha_event' and raw['data']=={'event_type':'pixora_test_event','data':{'value':42}}
        for ident, path, method in [('a', '/api/states', 'GET'), ('b', '/pixora/registry', 'GET'), ('c', '/api/services/light/turn_on', 'POST')]:
            await ws.send_json({'type': 'request', 'id': ident * 32, 'path': path, 'method': method, 'payload': {'entity_id': 'light.test'} if method == 'POST' else None, 'expiresAt': time.time() + 10})
        async for frame in ws:
            message = __import__('json').loads(frame.data)
            if message.get('type') == 'result':
                results[message['id']] = message
                if len(results) == 3:
                    delivered.set()
                    break
        await ws.close()
        return ws

    application.router.add_route('*', '/core/api/{tail:.*}', api)
    application.router.add_get('/core/websocket', ha_socket)
    application.router.add_get('/cloud', cloud_socket)
    runner = web.AppRunner(application)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    addon.API = f'http://127.0.0.1:{port}/core/api'
    addon.HA_SOCKET = f'ws://127.0.0.1:{port}/core/websocket'
    addon.SOCKET = f'ws://127.0.0.1:{port}/cloud'
    try:
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'SUPERVISOR_TOKEN': 'local-supervisor-token'}):
            data = Path(directory)
            code = 'already-paired-code'
            (data / 'options.json').write_text(json.dumps({'pairing_code': code}))
            (data / 'connection.json').write_text(json.dumps({'credential': 'paired-app-credential', 'codeHash': hashlib.sha256(code.encode()).hexdigest()}))
            connector = addon.Connector(data)
            logs = io.StringIO()
            handler = logging.StreamHandler(logs)
            addon.LOG.addHandler(handler)
            task = asyncio.create_task(connector.run())
            try:
                await asyncio.wait_for(delivered.wait(), 6)
                assert attempts >= 3, 'Connector did not reconnect after cloud and local handshake closes'
                assert local_attempts >= 2
                assert 'Pixora connection closed during handshake (code 1008)' in logs.getvalue()
                assert 'Home Assistant connection closed during handshake (code 1001)' in logs.getvalue()
                assert 'Reconnecting in 1s.' in logs.getvalue()
                assert 'private-peer-reason' not in logs.getvalue()
                assert 'paired-app-credential' not in logs.getvalue()
                assert commands == [{'entity_id': 'light.test'}]
                assert all(result['ok'] for result in results.values()), results
                assert results['a' * 32]['data'] == [state]
                assert results['b' * 32]['data'] == {'areas': [], 'devices': [], 'entities': [], 'buttonControllers': []}
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                addon.LOG.removeHandler(handler)
    finally:
        await runner.cleanup()

asyncio.run(check())
asyncio.run(check(False))
print('Packaged app survived authentication close 1008, reconnected, and passed live events, registry reads and service commands over actual HTTP/WebSocket connections.')
