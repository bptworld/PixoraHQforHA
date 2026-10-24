"""HA ingress app. All home interpretation runs in the native local Assist agent."""
import asyncio,json,os,shutil,tempfile,time
from pathlib import Path
from aiohttp import web,ClientSession,ClientTimeout,ClientError

VERSION='0.1.5'
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
        async with app['session'].request('POST' if body is not None else 'GET','http://supervisor/core/api/'+path,headers={'Authorization':'Bearer '+token},json=body,timeout=ClientTimeout(total=60 if path=='services/hassio/addon_restart' else 20)) as response:
            if response.status>=400:raise ValueError('Home Assistant could not confirm the request (HTTP '+str(response.status)+'). It was not retried.')
            return await response.json()

    async def agents():
        states=await ha('states')
        return [s['entity_id'] for s in states if s['entity_id'].startswith('conversation.') and s.get('attributes',{}).get('friendly_name') in {'Pixora Voice','Pixora Voice (Beta)'}]

    async def index(request):return web.FileResponse(Path(__file__).with_name('index.html'))
    async def timings(request):
        from diagnostics import recent_runs
        try:
            available=await agents()
            async with asyncio.timeout(12):
                runs=await recent_runs(app['session'],os.environ.get('SUPERVISOR_TOKEN',''),available)
            return web.json_response({'runs':runs})
        except (ValueError,KeyError,TypeError,asyncio.TimeoutError,ClientError):
            return web.json_response({'error':'Timing details are unavailable right now. You can also inspect this assistant under Home Assistant Voice assistants → Debug.'},status=503)
    async def icon(request):return web.FileResponse(Path(__file__).with_name('icon.svg'))
    async def status(request):
        try:available=await agents();error=''
        except (ValueError,asyncio.TimeoutError,ClientError):available=[];error='Home Assistant is reconnecting. Try again shortly.'
        return web.json_response({'version':VERSION,'agents':available,'installed':(config_root/'custom_components/pixora_voice/manifest.json').exists(),'notice':error})
    from planner_phrases import write_owned,update_phrases,update_local_phrases
    planner_file=config_root/'.storage'/'pixora_voice_planner.json'
    phrase_file=Path('/share/speech-to-phrase/custom_sentences/en/pixora_voice_planner.yaml')
    def planner_enabled():
        try:value=json.loads(planner_file.read_text(encoding='utf-8'))
        except (OSError,ValueError):return False
        return isinstance(value,dict) and value.get('enabled') is True
    async def planner_refresh():
        result=await ha('services/pixora_voice/planner_vocabulary?return_response',{})
        vocabulary=result.get('service_response',{})
        if vocabulary.get('available') is not True:raise ValueError('Planner did not respond. Check that the paired Pixora Home Control app and the updated Assist integration are running.')
        await asyncio.to_thread(update_phrases,phrase_file,vocabulary)
        try:await ha('services/hassio/addon_restart',{'addon':'core_speech-to-phrase'})
        except (ValueError,asyncio.TimeoutError,ClientError):return 'Planner is connected and its spoken phrases are saved. Speech-to-Phrase restart could not be confirmed; check its status before trying a spoken Planner question. The restart was not retried.'
        return 'Planner is connected. Speech-to-Phrase is restarting to learn your household names and teams; spoken requests will be available after training finishes.'
    async def planner_settings(request):
        if request.method=='GET':return web.json_response({'enabled':await asyncio.to_thread(planner_enabled)})
        try:
            value=await request.json()
            if not isinstance(value,dict) or type(value.get('enabled')) is not bool:raise ValueError('Choose whether to integrate with Planner.')
            await asyncio.to_thread(write_owned,planner_file,json.dumps({'enabled':value['enabled']}))
            if value['enabled']:
                try:message=await planner_refresh()
                except (ValueError,asyncio.TimeoutError,ClientError,OSError):message='Planner integration is enabled, but its connection or spoken phrases could not be confirmed. Check the paired Pixora Home Control app, then use Refresh Planner phrases.'
            else:
                await asyncio.to_thread(update_phrases,phrase_file)
                message='Planner integration is off. Your local home controls still work.'
            return web.json_response({'enabled':value['enabled'],'message':message})
        except (ValueError,OSError) as exc:return web.json_response({'error':str(exc)},status=400)
    async def refresh_planner(request):
        if not await asyncio.to_thread(planner_enabled):return web.json_response({'error':'Enable Planner integration first.'},status=400)
        try:return web.json_response({'message':await planner_refresh()})
        except (ValueError,asyncio.TimeoutError,ClientError,OSError):return web.json_response({'error':'Planner phrases could not be confirmed. Check the paired Pixora Home Control app and Assist integration. The request was not retried.'},status=503)
    async def install(request):
        try:await asyncio.to_thread(install_component,config_root,data_root)
        except ValueError as exc:return web.json_response({'error':str(exc)},status=409)
        return web.json_response({'message':'Assist integration installed. Restart Home Assistant once, add Pixora Voice under Settings → Devices & services, then select it in your local voice assistant.'})
    async def local_phrases(request):
        try:
            await asyncio.to_thread(update_local_phrases,phrase_file.with_name('pixora_voice_language.yaml'))
            await ha('services/hassio/addon_restart',{'addon':'core_speech-to-phrase'})
            return web.json_response({'message':'Conversation phrases saved. Speech-to-Phrase is restarting; wait for its training to finish before testing spoken follow-ups.'})
        except (ValueError,OSError,asyncio.TimeoutError,ClientError):
            return web.json_response({'error':'Phrase preparation or restart could not be confirmed. Check Speech-to-Phrase before testing. The restart was not retried.'},status=503)
    async def ask(request):
        value=await request.json();text=value.get('text','') if isinstance(value,dict) else ''
        if not isinstance(text,str) or not 0<len(text.strip())<=500:return web.json_response({'error':'Enter one short home question or command.'},status=400)
        try:
            available=await agents()
            if len(available)!=1:raise ValueError('Finish setting up the Pixora Voice integration first.')
            body={'text':text,'language':'en','agent_id':available[0]}
            cid=value.get('conversation_id')
            if isinstance(cid,str) and 0<len(cid)<=128:body['conversation_id']=cid
            result=await ha('services/conversation/process?return_response',body)
            speech=result.get('service_response',{}).get('response',{}).get('speech',{}).get('plain',{}).get('speech')
            if not speech:raise ValueError('Home Assistant did not return an answer. The request was not retried.')
            return web.json_response({'speech':speech,'conversation_id':result.get('service_response',{}).get('conversation_id')})
        except (ValueError,asyncio.TimeoutError,ClientError) as exc:
            return web.json_response({'error':str(exc) if isinstance(exc,ValueError) else 'The request timed out. It was not retried; check any device you asked to control.'},status=503)
    async def startup(app):app['session']=ClientSession(timeout=ClientTimeout(total=20))
    async def cleanup(app):await app['session'].close()
    app.on_startup.append(startup);app.on_cleanup.append(cleanup)
    app.router.add_get('/',index);app.router.add_get('/icon.svg',icon);app.router.add_get('/api/status',status)
    app.router.add_get('/api/planner',planner_settings);app.router.add_post('/api/planner',planner_settings);app.router.add_post('/api/planner/refresh',refresh_planner)
    app.router.add_post('/api/install',install);app.router.add_post('/api/ask',ask)
    app.router.add_get('/api/timings',timings)
    app.router.add_post('/api/phrases',local_phrases)
    return app

if __name__=='__main__':web.run_app(make_app(),host='0.0.0.0',port=4190)
