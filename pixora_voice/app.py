"""HA ingress app. All home interpretation runs in the native local Assist agent."""
import asyncio,json,os,shutil,tempfile,time
from pathlib import Path
from aiohttp import web,ClientSession,ClientTimeout,ClientError

VERSION='0.1.1'
COMPONENT=Path(__file__).parent/'custom_components'/'pixora_voice'


def install_component(config_root,data_root):
    """Explicit, app-owned install only; preserve the old version for recovery."""
    parent=config_root/'custom_components';parent.mkdir(parents=True,exist_ok=True)
    if parent.is_symlink():raise ValueError('The custom components folder must not be a symbolic link.')
    target=parent/'pixora_voice'
    if target.is_symlink():raise ValueError('The Pixora Voice folder must not be a symbolic link.')
    if target.exists():
        try:manifest=json.loads((target/'manifest.json').read_text())
        except (OSError,ValueError):raise ValueError('An unrecognized Pixora Voice folder already exists. It was not changed.')
        if manifest.get('domain')!='pixora_voice' or manifest.get('codeowners')!=['@bptworld']:
            raise ValueError('That folder belongs to another integration. It was not changed.')
    stage=Path(tempfile.mkdtemp(prefix='.pixora-voice-',dir=parent))
    try:
        shutil.copytree(COMPONENT,stage,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        if target.exists():
            backup=data_root/'integration-backups'/str(time.time_ns());backup.parent.mkdir(parents=True,exist_ok=True)
            shutil.copytree(target,backup)
            # Rename on the same filesystem before activating the new directory.
            old=parent/('.pixora-voice-old-'+str(time.time_ns()));target.rename(old)
            try:stage.rename(target)
            except BaseException:old.rename(target);raise
            shutil.rmtree(old)
        else:stage.rename(target)
    finally:
        if stage.exists():shutil.rmtree(stage)


def make_app(config_root=Path('/homeassistant'),data_root=Path('/data')):
    @web.middleware
    async def ingress(request,handler):
        if request.remote!='172.30.32.2':raise web.HTTPForbidden(text='Open Pixora Voice from Home Assistant.')
        if request.method=='POST':
            origin=request.headers.get('Origin')
            if origin:
                from urllib.parse import urlsplit
                host=request.headers.get('X-Forwarded-Host',request.host).split(',')[0].strip()
                if urlsplit(origin).netloc!=host:raise web.HTTPForbidden(text='Use the Home Assistant app page.')
        response=await handler(request)
        response.headers['Cache-Control']='no-store'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'self'"
        response.headers['X-Content-Type-Options']='nosniff'
        return response
    app=web.Application(middlewares=[ingress],client_max_size=4096)

    async def ha(path,body=None):
        token=os.environ.get('SUPERVISOR_TOKEN','')
        if not token:raise ValueError('Home Assistant access is unavailable.')
        async with app['session'].request('POST' if body is not None else 'GET','http://supervisor/core/api/'+path,headers={'Authorization':'Bearer '+token},json=body) as response:
            if response.status>=400:raise ValueError('Home Assistant could not confirm the request (HTTP '+str(response.status)+'). It was not retried.')
            return await response.json()

    async def agents():
        states=await ha('states')
        return [s['entity_id'] for s in states if s['entity_id'].startswith('conversation.') and s.get('attributes',{}).get('friendly_name') in {'Pixora Voice','Pixora Voice (Beta)'}]

    async def index(request):return web.FileResponse(Path(__file__).with_name('index.html'))
    async def status(request):
        try:available=await agents();error=''
        except (ValueError,asyncio.TimeoutError,ClientError):available=[];error='Home Assistant is reconnecting. Try again shortly.'
        return web.json_response({'version':VERSION,'agents':available,'installed':(config_root/'custom_components/pixora_voice/manifest.json').exists(),'notice':error})
    async def install(request):
        try:await asyncio.to_thread(install_component,config_root,data_root)
        except ValueError as exc:return web.json_response({'error':str(exc)},status=409)
        return web.json_response({'message':'Assist integration installed. Restart Home Assistant once, add Pixora Voice under Settings → Devices & services, then select it in your local voice assistant.'})
    async def ask(request):
        value=await request.json();text=value.get('text','') if isinstance(value,dict) else ''
        if not isinstance(text,str) or not 0<len(text.strip())<=500:return web.json_response({'error':'Enter one short home question or command.'},status=400)
        try:
            available=await agents()
            if len(available)!=1:raise ValueError('Finish setting up the Pixora Voice integration first.')
            result=await ha('services/conversation/process?return_response',{'text':text,'language':'en','agent_id':available[0]})
            speech=result.get('service_response',{}).get('response',{}).get('speech',{}).get('plain',{}).get('speech')
            if not speech:raise ValueError('Home Assistant did not return an answer. The request was not retried.')
            return web.json_response({'speech':speech})
        except (ValueError,asyncio.TimeoutError,ClientError) as exc:
            return web.json_response({'error':str(exc) if isinstance(exc,ValueError) else 'The request timed out. It was not retried; check any device you asked to control.'},status=503)
    async def startup(app):app['session']=ClientSession(timeout=ClientTimeout(total=20))
    async def cleanup(app):await app['session'].close()
    app.on_startup.append(startup);app.on_cleanup.append(cleanup)
    app.router.add_get('/',index);app.router.add_get('/api/status',status)
    app.router.add_post('/api/install',install);app.router.add_post('/api/ask',ask)
    return app

if __name__=='__main__':web.run_app(make_app(),host='0.0.0.0',port=4190)
