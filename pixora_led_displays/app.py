"""Ingress-only HA app. Panel commands stay on the LAN."""
import asyncio
import base64
import io
import json
import os
import shutil
import sys
import uuid
from pathlib import Path
from aiohttp import web, ClientSession
from PIL import Image, ImageOps
sys.path.insert(0, str(Path(__file__).parent / 'custom_components' / 'pixora_local'))
from client import DisplayClient


def image_payload(body, width, height, duration):
    if not body or len(body) > 5 * 1024 * 1024:
        raise ValueError('Choose an image smaller than 5 MB.')
    with Image.open(io.BytesIO(body)) as image:
        if image.width * image.height > 16000000:
            raise ValueError('Use an image with at most 16 million pixels.')
        image = ImageOps.exif_transpose(image).convert('RGBA')
        image = Image.alpha_composite(Image.new('RGBA', image.size, 'black'), image).convert('RGB')
        pixels = ImageOps.pad(image, (width, height), color='black').tobytes()
    return {'rgb': base64.b64encode(pixels).decode('ascii'), 'width': width, 'height': height, 'duration': duration}


def make_app(root=Path('/data'), config_root=Path('/homeassistant'), client_factory=DisplayClient, ingress_peer='172.30.32.2'):
    app = web.Application(client_max_size=5 * 1024 * 1024)
    lock = asyncio.Lock()
    file = root / 'displays.json'
    # Fail visibly on corrupt storage rather than replacing paired identities.
    state = json.loads(file.read_text()) if file.exists() else {'displays': []}
    if not isinstance(state, dict) or not isinstance(state.get('displays'), list):
        raise ValueError('Display storage is invalid. Restore displays.json from backup.')

    def public():
        return [{k: v for k, v in display.items() if k != 'key'} for display in state['displays']]

    def persist():
        root.mkdir(parents=True, exist_ok=True)
        temp = file.with_suffix('.tmp')
        temp.write_text(json.dumps(state), encoding='utf-8')
        os.chmod(temp, 0o600)
        os.replace(temp, file)

    def selected(ident):
        display = next((d for d in state['displays'] if d['id'] == ident), None)
        if not display:
            raise ValueError('Choose a connected display.')
        return client_factory(app['session'], display['host'], display['key'])

    @web.middleware
    async def errors(request, handler):
        try:
            if request.remote != ingress_peer:
                raise web.HTTPForbidden()
            if request.headers.get('Sec-Fetch-Site') == 'cross-site':
                raise web.HTTPForbidden()
            return await handler(request)
        except (ValueError, OSError) as exc:
            return web.json_response({'error': str(exc)}, status=400)

    app.middlewares.append(errors)

    async def index(request):
        return web.FileResponse(Path(__file__).with_name('index.html'))

    async def listing(request):
        return web.json_response({'displays': public()})

    async def object_payload(request):
        try:
            payload = await request.json()
        except (ValueError, UnicodeError) as exc:
            raise ValueError('Use valid JSON.') from exc
        if not isinstance(payload, dict):
            raise ValueError('Use a JSON object.')
        return payload

    async def pair(request):
        payload = await object_payload(request)
        async with lock:
            if len(state['displays']) >= 30:
                raise ValueError('Up to 30 displays are supported.')
            client = client_factory(app['session'], payload.get('host', ''))
            info = await client.info()
            await client.pair()
            display = {'id': info['id'], 'name': str(payload.get('name') or info.get('name') or 'Pixora LED')[:80],
                       'host': client.host, 'key': client.key, 'width': info['width'], 'height': info['height'], 'version': info['version']}
            previous = list(state['displays'])
            state['displays'] = [d for d in previous if d['id'] != display['id']] + [display]
            try:
                await asyncio.to_thread(persist)
            except OSError:
                state['displays'] = previous
                raise
        return web.json_response({'displays': public()})

    async def show(request):
        payload = await object_payload(request)
        duration = payload.get('duration', 10)
        if type(duration) is not int or not 1 <= duration <= 300:
            raise ValueError('Choose 1 to 300 seconds.')
        client = selected(payload.get('id'))
        await client.show(payload.get('message'), payload.get('color', [255, 255, 255]), duration)
        return web.json_response({'accepted': True})

    async def manage_display(request):
        name = None
        if request.method == 'PATCH':
            payload = await object_payload(request)
            name = payload.get('name')
            if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
                raise ValueError('Enter a display name from 1 to 80 characters.')
            name = name.strip()
        async with lock:
            ident = request.match_info['display_id']
            if not any(d['id'] == ident for d in state['displays']):
                return web.json_response({'error': 'That display is no longer in the list.'}, status=404)
            previous = state['displays']
            if request.method == 'DELETE':
                state['displays'] = [d for d in previous if d['id'] != ident]
            else:
                state['displays'] = [dict(d, name=name) if d['id'] == ident else d for d in previous]
            try:
                await asyncio.to_thread(persist)
            except OSError:
                state['displays'] = previous
                raise
        return web.json_response({'displays': public()})

    async def show_image(request):
        duration = int(request.query.get('duration', '10'))
        if not 1 <= duration <= 300:
            raise ValueError('Choose 1 to 300 seconds.')
        client = selected(request.query.get('id'))
        info = await client.info()
        payload = await asyncio.to_thread(image_payload, await request.read(), info['width'], info['height'], duration)
        await client.request('/api/frame', payload)
        return web.json_response({'accepted': True})

    async def update_firmware(request):
        client = selected(request.query.get('id'))
        await client.update_firmware(await request.read())
        return web.json_response({'updated': True})

    async def install_actions(request):
        source = Path(__file__).parent / 'custom_components' / 'pixora_local'
        target = config_root / 'custom_components' / 'pixora_local'
        if not config_root.is_dir():
            raise ValueError('Home Assistant configuration folder is unavailable.')
        def install():
            if target.exists():
                backup = root / 'action-backups' / uuid.uuid4().hex
                shutil.copytree(target, backup)
            shutil.copytree(source, target, dirs_exist_ok=True)
        await asyncio.to_thread(install)
        return web.json_response({'message': 'Actions installed. Restart Home Assistant, then add the Pixora LED (Local) integration under Devices & services. Restart the panel before connecting it.'})

    async def startup(app):
        app['session'] = ClientSession()

    async def cleanup(app):
        await app['session'].close()

    app.on_startup.append(startup)
    app.on_cleanup.append(cleanup)
    app.router.add_get('/', index)
    app.router.add_get('/api/displays', listing)
    app.router.add_post('/api/displays', pair)
    app.router.add_patch('/api/displays/{display_id}', manage_display)
    app.router.add_delete('/api/displays/{display_id}', manage_display)
    app.router.add_post('/api/show', show)
    app.router.add_post('/api/image', show_image)
    app.router.add_post('/api/install-actions', install_actions)
    app.router.add_post('/api/update', update_firmware)
    return app


if __name__ == '__main__':
    web.run_app(make_app(), host='0.0.0.0', port=4188)
