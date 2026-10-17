"""Automatic local HA companion installation and Supervisor discovery."""
import asyncio
import os
import shutil
import uuid
from urllib.parse import quote
from pathlib import Path
import aiohttp

VERSION = '1.1.0'

def install_companion(root, config_root):
    source = Path(__file__).parent / 'custom_components/pixora_local'
    target = config_root / 'custom_components/pixora_local'
    if not config_root.is_dir():
        raise ValueError('Home Assistant configuration folder is unavailable.')
    def contents(folder):
        return {p.relative_to(folder): p.read_bytes() for p in folder.rglob('*')
                if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}
    if target.is_dir() and contents(source) == contents(target):
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = target.with_name('.pixora-stage-' + uuid.uuid4().hex)
    old = target.with_name('.pixora-old-' + uuid.uuid4().hex)
    try:
        shutil.copytree(source, stage, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        if target.exists():
            shutil.copytree(target, root / 'action-backups' / uuid.uuid4().hex)
            target.rename(old)
        try:
            stage.rename(target)
        except OSError:
            if old.exists(): old.rename(target)
            raise
        if old.exists(): shutil.rmtree(old)
    finally:
        if stage.exists(): shutil.rmtree(stage)
    return True

class HomeAssistantSetup:
    def __init__(self, session, root, config_root):
        self.session, self.root, self.config_root = session, root, config_root
        self.error = ''
        self.lock = asyncio.Lock()

    async def supervisor(self, path, payload):
        token = os.environ.get('SUPERVISOR_TOKEN')
        if not token:
            raise ValueError('Home Assistant API access is unavailable. Update Pixora LED Studio to 1.0.7 or newer and restart the Pixora LED Studio app. Your saved displays are kept.')
        try:
            async with self.session.post('http://supervisor/' + path, json=payload,
                    headers={'Authorization':'Bearer ' + token}, allow_redirects=False,
                    timeout=aiohttp.ClientTimeout(total=15)) as response:
                if response.status != 200:
                    raise ValueError('Home Assistant did not confirm setup. Use Retry HA setup below.')
                result = await response.json()
                if (path == 'discovery' and (not isinstance(result,dict) or result.get('result') != 'ok'
                        or not isinstance(result.get('data'),dict) or not isinstance(result['data'].get('uuid'),str))) or (path != 'discovery' and not isinstance(result,list)):
                    raise ValueError('Home Assistant did not confirm setup. Use Retry HA setup below.')
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise ValueError('Could not confirm HA setup. Your connected displays are saved; use Retry HA setup.') from exc

    async def sync(self, displays):
        if (self.root / ".cleanup-started").exists():
            return {"restart_required":False,"error":"Cleanup mode is active. Finish cleanup, then uninstall this app.","can_restart":False}
        async with self.lock:
            try:
                await asyncio.to_thread(install_companion, self.root, self.config_root)
                # Supervisor keeps one discovery record per app/service. Send the whole catalog.
                await self.supervisor('discovery', {'service':'pixora_local', 'config':{'displays':displays,'companion_version':VERSION}})
                self.error = ''
            except (ValueError,OSError) as exc:
                self.error = str(exc)
        return await self.status()

    async def status(self):
        def loaded():
            marker = self.config_root / '.pixora-led-ha-version'
            return marker.read_text().strip() if marker.is_file() else ''
        try:
            restart = await asyncio.to_thread(loaded) != VERSION
        except OSError:
            restart = True
        return {'restart_required':restart, 'error':self.error, 'can_restart':bool(os.environ.get('SUPERVISOR_TOKEN')) and not self.error}

    async def restart(self):
        # Only called by the explicit Restart Home Assistant button, never startup/connect.
        await self.supervisor('core/api/services/homeassistant/restart', {})

    async def cleanup_request(self, method, path, payload=None):
        token = os.environ.get('SUPERVISOR_TOKEN')
        if not token: raise ValueError('Home Assistant API is unavailable. Cleanup has not completed.')
        try:
            async with self.session.request(method, 'http://supervisor/' + path,
                    json=payload, headers={'Authorization':'Bearer '+token},
                    allow_redirects=False, timeout=aiohttp.ClientTimeout(total=60)) as response:
                if response.status != 200:
                    raise ValueError('HA cleanup was not confirmed. Keep the app installed and try cleanup again.')
                return await response.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise ValueError('HA cleanup outcome could not be confirmed. Keep the app installed and try cleanup again.') from exc

    async def remove_ha(self):
        # Replace this app's discovery with an empty catalog, then remove its owned record.
        result = await self.cleanup_request('POST','discovery',{'service':'pixora_local','config':{'displays':[]}})
        ident = result.get('data',{}).get('uuid') if result.get('result') == 'ok' else None
        if not isinstance(ident,str) or not ident: raise ValueError('Could not confirm discovery cleanup.')
        result = await self.cleanup_request('DELETE','discovery/'+quote(ident,safe=''))
        if result.get('result') != 'ok': raise ValueError('Could not remove app discovery.')
        path = 'core/api/config/config_entries/entry'
        entries = await self.cleanup_request('GET',path+'?domain=pixora_local')
        if not isinstance(entries,list): raise ValueError('Could not list Pixora LED devices.')
        for entry in entries:
            if entry.get('domain') != 'pixora_local': continue
            ident=entry.get('entry_id')
            if not isinstance(ident,str) or not ident: raise ValueError('Invalid HA display entry.')
            result = await self.cleanup_request('DELETE',path+'/'+quote(ident,safe=''))
            if not isinstance(result,dict) or result.get('require_restart') is True:
                raise ValueError('Restart HA, then run cleanup again to finish removing display devices.')
        remaining = await self.cleanup_request('GET',path+'?domain=pixora_local')
        if not isinstance(remaining,list) or any(e.get('domain')=='pixora_local' for e in remaining):
            raise ValueError('Some Pixora LED devices remain. Keep the app installed and run cleanup again.')

    def remove_files(self):
        # Fixed, app-owned paths only; never traverse links into other HA data.
        target=self.config_root/'custom_components'/'pixora_local'
        if target.parent.resolve() != self.config_root.resolve()/'custom_components':
            raise ValueError('Cannot clean a linked custom_components folder. Remove the Pixora integration manually.')
        if target.is_symlink(): target.unlink()
        elif target.exists(): shutil.rmtree(target)
        (self.config_root/'.pixora-led-ha-version').unlink(missing_ok=True)
        for path in self.root.iterdir():
            if path.name in ('.cleanup-started','options.json'): continue
            if path.is_symlink() or path.is_file(): path.unlink()
            elif path.is_dir(): shutil.rmtree(path)
