"""Automatic setup uses Supervisor discovery only; never auto-restarts HA or sends cards."""
import asyncio
import importlib.util
import os
import tempfile
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('automation',root/'pixora_led_displays/automation.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
async def check():
    calls=[]
    class Response:
        status=200
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def json(self): return [] if getattr(self,'restart',False) else {'result':'ok','data':{'uuid':'private-discovery-id'}}
    class Session:
        def post(self,url,**kwargs):
            calls.append((url,kwargs));response=Response();response.restart=url.endswith('/restart');return response
    with tempfile.TemporaryDirectory() as temp:
        folder=Path(temp);config=folder/'ha';config.mkdir()
        setup=module.HomeAssistantSetup(Session(),folder/'data',config)
        panels=[{'id':'panel1','host':'192.168.1.50','key':'a'*32,'name':'Kitchen','width':64,'height':32,'version':'2.0.18'}]
        with patch.dict(os.environ,{'SUPERVISOR_TOKEN':'test-token'}):
            result=await setup.sync(panels)
            assert result=={'restart_required':True,'error':'','can_restart':True}
            assert (config/'custom_components/pixora_local/manifest.json').is_file()
            assert len(calls)==1 and calls[0][0]=='http://supervisor/discovery'
            assert calls[0][1]['json']=={'service':'pixora_local','config':{'displays':panels}}
            assert not calls[0][1]['allow_redirects']
            assert not (folder/'data/action-backups').exists()
            await setup.sync(panels)
            assert not (folder/'data/action-backups').exists(), 'Unchanged restart made needless backup'
            (config/'.pixora-led-ha-version').write_text('1.0.5')
            assert not (await setup.status())['restart_required']
            # Restart is only sent on explicit UI request, never by installation/discovery.
            assert all(url.endswith('/discovery') for url,_ in calls)
            await setup.restart()
            assert calls[-1][0]=='http://supervisor/core/api/services/homeassistant/restart'
        with patch.dict(os.environ,{},clear=True):
            result=await setup.sync(panels)
            assert result['can_restart'] is False
            assert result['error'] and 'test-token' not in str(result) and 'a'*32 not in str(result)
        original=(config/'custom_components/pixora_local/client.py').read_bytes()
        with patch.object(module.shutil,'copytree',side_effect=OSError('Cannot stage update')):
            (config/'custom_components/pixora_local/old.py').write_text('old')
            try: module.install_companion(folder/'data',config)
            except OSError: pass
            else: raise AssertionError('Failed update reported as installed')
        assert (config/'custom_components/pixora_local/client.py').read_bytes()==original
asyncio.run(check())
print('Automatic HA setup passed: startup install, complete discovery, idempotent updates, private keys, failure recovery and explicit-only restart.')

# S6 strips the ordinary CMD environment; the launcher must explicitly restore it.
folder=root/'pixora_led_displays'
docker=(folder/'Dockerfile').read_text()
assert 'COPY run.sh /run.sh' in docker and 'chmod 0755 /run.sh' in docker and 'CMD ["/run.sh"]' in docker
launcher=(folder/'run.sh').read_bytes()
assert launcher.startswith(b'#!/command/with-contenv bash\n') and b'\r' not in launcher
assert b'exec python3 /app/app.py' in launcher
