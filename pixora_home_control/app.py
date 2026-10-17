"""Local HA API bridge with an authenticated, outbound-only Pixora connection."""
import asyncio
import json
import hashlib
import logging
import os
from pathlib import Path
import re
import time
import aiohttp

ORIGIN = 'https://homecontrol.pixorahq.com'
SOCKET = 'wss://homecontrol.pixorahq.com/api/homecontrol/connector/socket'
API = 'http://supervisor/core/api'
HA_SOCKET = 'ws://supervisor/core/websocket'
LOG = logging.getLogger('pixora_home_control')


async def socket_json(ws, name, timeout=15):
    """Turn handshake close/error frames into recoverable connection failures."""
    frame = await ws.receive(timeout=timeout)
    if frame.type != aiohttp.WSMsgType.TEXT:
        code = frame.data if frame.type == aiohttp.WSMsgType.CLOSE else ws.close_code
        # Never include frame payloads or peer-provided close reasons in logs.
        raise ConnectionError(f'{name} connection closed during handshake (code {code if isinstance(code, int) else ws.close_code}).')
    message = json.loads(frame.data)
    if not isinstance(message, dict):
        raise ValueError('Invalid socket message.')
    return message


def allowed(path, method):
    return (method == 'GET' and (path in {'/api/', '/api/config', '/api/states', '/api/services', '/pixora/registry'} or re.fullmatch(r'/api/states/[a-z0-9_]+\.[a-z0-9_]+', path))) or (method == 'POST' and re.fullmatch(r'/api/services/[a-z0-9_]+/[a-z0-9_]+', path))


class LocalAPI:
    def __init__(self, session, token):
        self.session, self.token = session, token
        self.socket = None
        self.pending = {}
        self.counter = 3
        self.registry_cache = None
        self.registry_at = 0

    async def request(self, path, method='GET', payload=None):
        async with self.session.request(method, API + path.removeprefix('/api'), json=payload if method == 'POST' else None, headers={'Authorization': 'Bearer ' + self.token}, timeout=aiohttp.ClientTimeout(total=8), allow_redirects=False) as response:
            if response.status >= 300:
                raise ValueError(f'Home Assistant local request failed (HTTP {response.status}).')
            raw = bytearray()
            async for chunk in response.content.iter_chunked(65536):
                raw.extend(chunk)
                if len(raw) > 5_000_000:
                    raise ValueError('Home Assistant response is too large.')
            return json.loads(raw)

    async def query(self, kind, **fields):
        self.counter += 1
        ident = self.counter
        future = asyncio.get_running_loop().create_future()
        self.pending[ident] = future
        try:
            await self.socket.send_json({'id': ident, 'type': kind, **fields})
            return await asyncio.wait_for(future, 8)
        finally:
            self.pending.pop(ident, None)

    async def registry(self):
        if self.registry_cache is not None and time.monotonic()-self.registry_at<60:
            return self.registry_cache
        values = await asyncio.gather(*(self.query(kind) for kind in ['config/area_registry/list', 'config/device_registry/list', 'config/entity_registry/list']))
        registry = dict(zip(['areas', 'devices', 'entities'], values))
        controllers = []
        for device in registry['devices']:
            if not any(isinstance(pair,list) and pair and pair[0]=='lutron_caseta' for pair in device.get('identifiers',[])):
                continue
            triggers = await self.query('device_automation/trigger/list', device_id=device['id'])
            options = sorted({item['subtype']+':'+item['type'] for item in triggers if item.get('domain')=='lutron_caseta' and isinstance(item.get('subtype'),str) and isinstance(item.get('type'),str)})
            if options:
                controllers.append({'deviceId':device['id'], 'name':device.get('name_by_user') or device.get('name') or 'Lutron controller', 'events':options})
        registry['buttonControllers'] = controllers
        self.registry_cache=registry;self.registry_at=time.monotonic()
        return registry

    async def listen(self, cloud, events, unified=False):
        def converted(message):
            event=message.get('event',{})
            if message.get('id')==3:return {'_ha_event':event}
            if event.get('event_type')=='state_changed':return event.get('data')
            if event.get('event_type')=='lutron_caseta_button_event':
                data=event.get('data',{});ident=data.get('device_id','')
                if re.fullmatch(r'[a-f0-9]{32}',ident) and isinstance(data.get('button_type'),str) and isinstance(data.get('action'),str):
                    stamp=event.get('time_fired') or str(time.time_ns())
                    return {'entity_id':'event.lutron_'+ident,'new_state':{'entity_id':'event.lutron_'+ident,'state':stamp,'last_updated':stamp,'attributes':{'event_type':data['button_type']+':'+data['action']}}}
        async with self.session.ws_connect(HA_SOCKET, heartbeat=20, max_msg_size=5_000_000) as ws:
            self.socket=ws;self.registry_cache=None
            if (await socket_json(ws,'Home Assistant')).get('type')!='auth_required':raise ValueError('Invalid local greeting.')
            await ws.send_json({'type':'auth','access_token':self.token})
            if (await socket_json(ws,'Home Assistant')).get('type')!='auth_ok':raise ValueError('Local authentication failed.')
            initial=[]
            for ident,kind in ([(3,None)] if unified else [(1,'state_changed'),(2,'lutron_caseta_button_event'),(3,None)]):
                await ws.send_json({'id':ident,'type':'subscribe_events',**({'event_type':kind} if kind else {})})
                result=await socket_json(ws,'Home Assistant')
                while result.get('type')=='event':
                    item=converted(result)
                    if item:initial.append(item)
                    if len(initial)>256:raise asyncio.QueueFull()
                    result=await socket_json(ws,'Home Assistant')
                if result.get('id')!=ident or result.get('type')!='result' or not result.get('success'):raise ValueError('Local event subscription failed.')
            self.counter=max(self.counter,3)
            await cloud.send_json({'type':'ready'})
            for item in initial:events.put_nowait(item)
            async for frame in ws:
                if frame.type!=aiohttp.WSMsgType.TEXT:break
                message=json.loads(frame.data)
                if message.get('type')=='result':
                    future=self.pending.get(message.get('id'))
                    if future and not future.done():
                        if message.get('success'):future.set_result(message.get('result'))
                        else:future.set_exception(ValueError('Local registry request failed.'))
                elif message.get('type')=='event':
                    item=converted(message)
                    if item:events.put_nowait(item)
            raise ConnectionError(f'Home Assistant event connection closed (code {ws.close_code}).')


class Connector:
    def __init__(self, data_dir=Path('/data')):
        self.data_dir = data_dir
        self.executed = {}

    async def pair(self, session, local, code):
        config = await local.request('/api/config')
        async with session.post(ORIGIN + '/api/homecontrol/connector/pair', json={'code': code, 'name': config.get('location_name'), 'url': config.get('external_url') or config.get('internal_url') or 'http://homeassistant.local:8123'}, timeout=aiohttp.ClientTimeout(total=15), allow_redirects=False) as response:
            if response.status != 200:
                raise ValueError('Pairing failed. Generate a fresh code in Planner → Smart Home.')
            token = (await response.json())['credential']
        state = {'credential': token, 'codeHash': hashlib.sha256(code.encode()).hexdigest()}
        temp = self.data_dir / 'connection.tmp'
        temp.touch(mode=0o600, exist_ok=True)
        temp.chmod(0o600)
        temp.write_text(json.dumps(state), encoding='utf-8')
        temp.replace(self.data_dir / 'connection.json')
        return state

    async def execute(self, local, cloud, message):
        ident = message.get('id')
        path, method = message.get('path'), message.get('method')
        if not isinstance(ident, str) or not re.fullmatch(r'[a-f0-9]{32}', ident):
            raise ValueError('Invalid command ID.')
        previous = self.executed.get(ident)
        if previous:
            await cloud.send_json(previous)
            return
        response = {'type': 'result', 'id': ident, 'ok': False}
        # Only service calls need deduplication; never retain large state/registry reads.
        if method == 'POST':
            self.executed[ident] = response
            if len(self.executed) > 256:
                self.executed.pop(next(iter(self.executed)))
        try:
            expires = message.get('expiresAt')
            if type(expires) not in (int, float) or not time.time() < expires <= time.time() + 15 or not isinstance(path, str) or not allowed(path, method):
                raise ValueError('Expired or unsupported request.')
            result = await local.registry() if path == '/pixora/registry' else await local.request(path, method, message.get('payload'))
            response['data'] = None if method == 'POST' else result
            response['ok'] = True
        except (ValueError, aiohttp.ClientError, asyncio.TimeoutError) as error:
            # Report fixed categories only; never relay response bodies or credentials.
            if isinstance(error, asyncio.TimeoutError):
                detail = 'Local Home Assistant request timed out.'
            elif isinstance(error, aiohttp.ClientError):
                detail = 'Local Home Assistant connection failed.'
            elif str(error).startswith('Home Assistant local request failed (HTTP '):
                detail = str(error)
            elif str(error) in {'Expired or unsupported request.', 'Local registry request failed.', 'Home Assistant response is too large.'}:
                detail = str(error)
            else:
                detail = 'Local Home Assistant returned an invalid response.'
            response['error'] = detail
            LOG.warning('%s %s: %s No automatic retry.', method, path, detail)
        await cloud.send_json(response)

    async def run_connection(self, session, local, credential):
        async with session.ws_connect(SOCKET, heartbeat=20, max_msg_size=5_000_000) as cloud:
            await cloud.send_json({'type': 'auth', 'credential': credential, 'eventStream': 'unified'})
            reply = await socket_json(cloud, 'Pixora')
            if reply.get('type') != 'auth_ok':
                raise ValueError('Connector authorization failed. Pair again in Planner.')
            events = asyncio.Queue(maxsize=256)
            requests = asyncio.Queue(maxsize=16)

            async def send_events():
                while True:
                    event=await events.get()
                    await cloud.send_json({'type':'ha_event','data':event['_ha_event']} if '_ha_event' in event else {'type':'event','data':event})

            async def commands():
                while True:
                    await self.execute(local, cloud, await requests.get())

            async def heartbeat():
                while True:
                    await asyncio.sleep(20)
                    await cloud.send_json({'type': 'ping'})

            async def receive():
                async for frame in cloud:
                    if frame.type != aiohttp.WSMsgType.TEXT:
                        break
                    message = json.loads(frame.data)
                    if message.get('type') == 'request':
                        requests.put_nowait(message)
                    elif message.get('type') != 'pong':
                        raise ValueError('Invalid cloud message.')
                raise ConnectionError(f'Pixora connection closed (code {cloud.close_code}).')

            tasks = [asyncio.create_task(coro) for coro in [local.listen(cloud, events, unified=reply.get("eventStream")=="unified"), send_events(), commands(), heartbeat(), receive()]]
            LOG.info('Paired connector connected to Pixora.')
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                for future in local.pending.values():
                    if not future.done():
                        future.cancel()
                local.pending.clear()

    async def run(self):
        options = json.loads((self.data_dir / 'options.json').read_text(encoding='utf-8'))
        code = str(options.get('pairing_code') or '').strip()
        if not code:
            raise ValueError('Enter the pairing code from Planner → Smart Home in this app’s Configuration tab.')
        path = self.data_dir / 'connection.json'
        state = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        delay = 1
        async with aiohttp.ClientSession() as session:
            local = LocalAPI(session, os.environ['SUPERVISOR_TOKEN'])
            while True:
                started = time.monotonic()
                try:
                    if state.get('codeHash') != hashlib.sha256(code.encode()).hexdigest():
                        state = await self.pair(session, local, code)
                    await self.run_connection(session, local, state['credential'])
                except (aiohttp.ClientError, asyncio.TimeoutError, ConnectionError, ValueError, asyncio.QueueFull, KeyError) as error:
                    # Healthy sessions must not inherit earlier outage backoff.
                    if time.monotonic() - started >= 60:
                        delay = 1
                    reason = type(error).__name__
                    if isinstance(error, ConnectionError) or str(error) in {'Invalid local greeting.', 'Local authentication failed.', 'Local event subscription failed.', 'Invalid cloud message.', 'Connector authorization failed. Pair again in Planner.'}:
                        reason = str(error)
                    LOG.warning('Connector offline: %s Reconnecting in %ss.', reason, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    try:
        asyncio.run(Connector().run())
    except (ValueError, OSError, KeyError):
        LOG.error('Setup is incomplete. Check the pairing code and Home Assistant app permissions.')
        raise SystemExit(1)
