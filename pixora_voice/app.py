"""HA ingress app. All home interpretation runs in the native local Assist agent."""
import asyncio,json,os,shutil,tempfile,time,logging
from pathlib import Path
from aiohttp import web,ClientSession,ClientTimeout,ClientError

VERSION='0.1.14'
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
        shutil.copyfile(Path(__file__).with_name('planner_phrases.py'),stage/'phrase_tools.py')
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


def prepare_integration_update(config_root, data_root, phrase_file=None):
    """Update only our recognized component; journal a restart before issuing it."""
    from planner_phrases import write_owned
    journal = data_root / 'integration-update.json'
    record = json.loads(journal.read_text()) if journal.exists() else {}
    if not isinstance(record, dict):raise ValueError('Integration update record needs attention.')
    manifest = config_root / 'custom_components/pixora_voice/manifest.json'
    exists = manifest.exists()
    installed = json.loads(manifest.read_text()) if exists else {}
    if not isinstance(installed,dict) or exists and (installed.get('domain')!='pixora_voice' or installed.get('codeowners')!=['@bptworld']):raise ValueError('An unrecognized Assist folder was preserved; automatic update stopped.')
    if installed.get('version') == VERSION:
        if record.get('version') == VERSION and record.get('phase') == 'prepared':
            if record.get('speechNeeded'):
                if not phrase_file:raise ValueError('Speech phrase recovery needs its saved destination.')
                from planner_phrases import update_local_phrases
                update_local_phrases(phrase_file)
            record['phase'] = 'installed'
            write_owned(journal, json.dumps(record))
        return record if record.get('version') == VERSION and record.get('phase') != 'complete' else None
    from planner_phrases import update_local_phrases
    speech_changed = update_local_phrases(phrase_file,check_only=True) if phrase_file else False
    record = {'version': VERSION, 'phase': 'prepared', 'needRestart': exists, 'speechNeeded': speech_changed}
    write_owned(journal, json.dumps(record))
    install_component(config_root, data_root)
    if phrase_file:
        from planner_phrases import update_local_phrases
        update_local_phrases(phrase_file)
    record['phase'] = 'installed'
    write_owned(journal, json.dumps(record))
    return record

async def finish_integration_update(record, config_root, data_root, ha, notice, sleep=asyncio.sleep):
    try:
        await _finish_integration_update(record, config_root, data_root, ha, notice, sleep)
    except (OSError, ValueError, TypeError, KeyError):
        logging.getLogger(__name__).warning('Automatic Voice update paused: local files could not be saved or verified. No restart replay.')
        notice.update(message='Automatic update paused because its local files could not be saved or verified. No restart was repeated. Check storage and the Voice app logs.', pending=False)

async def _finish_integration_update(record, config_root, data_root, ha, notice, sleep=asyncio.sleep):
    from planner_phrases import write_owned
    journal = data_root / 'integration-update.json'
    def save(phase):
        record['phase'] = phase
        write_owned(journal, json.dumps(record))
    # Reads may recover from startup. The restart command is issued at most once.
    for _ in range(45):
        try:
            states = await ha('states')
            agents = [s for s in states if s.get('entity_id','').startswith('conversation.') and s.get('attributes',{}).get('friendly_name') in {'Pixora Voice','Pixora Voice (Beta)'}]
            if any(s.get('attributes',{}).get('pixora_voice_version') == VERSION for s in agents):
                if record.get('speechNeeded'):
                    if record['phase'] in {'speech-restart-requested','speech-uncertain'}:
                        notice.update(message='Voice and Assist are updated. Speech restart was not confirmed and was not repeated; check Speech-to-Phrase.',pending=False)
                        return
                    baseline=await ha('services/pixora_voice/speech_ready?return_response',{})
                    record['speechPrevious']=baseline.get('service_response',{}).get('generation')
                    if not record['speechPrevious']:
                        notice.update(message='Assist updated, but speech readiness could not be verified. No speech restart was sent; check Speech-to-Phrase.',pending=False)
                        return
                    await asyncio.to_thread(save,'speech-restart-requested')
                    try:await ha('services/hassio/addon_restart',{'addon':'core_speech-to-phrase'})
                    except (ValueError,ClientError,asyncio.TimeoutError):
                        await asyncio.to_thread(save,'speech-uncertain')
                        notice.update(message='Voice and Assist are updated. Speech restart was not confirmed and was not repeated; check Speech-to-Phrase.',pending=False)
                        return
                if record.get('speechNeeded'):
                    notice.update(message='Speech phrases are training. Waiting until your local voice service is ready.',pending=True)
                    for _ in range(60):
                        try:
                            result=await ha('services/pixora_voice/speech_ready?return_response',{})
                            if result.get('service_response',{}).get('ready') is True and result.get('service_response',{}).get('generation') != record.get('speechPrevious'):break
                        except (ValueError,ClientError,asyncio.TimeoutError):pass
                        await sleep(2)
                    else:
                        notice.update(message='Voice and Assist are updated, but speech readiness is not confirmed. No restart was repeated; check Speech-to-Phrase.',pending=False)
                        return
                await asyncio.to_thread(save, 'complete')
                notice.update(message='Ready. Voice and Assist are up to date.', pending=False)
                return
            if not record.get('needRestart') and not agents:
                await asyncio.to_thread(save, 'complete')
                notice.update(message='Assist files installed automatically. Add Pixora Voice in Devices & services for first-time setup.', pending=False)
                return
            if record['phase'] in {'prepared','installed'}:
                await asyncio.to_thread(save, 'restart-requested')
                notice.update(message='Assist updated automatically. Home Assistant is restarting once to load it.', pending=True)
                try:await ha('services/homeassistant/restart', {})
                except (ValueError,ClientError,asyncio.TimeoutError):pass
        except (ValueError,ClientError,asyncio.TimeoutError):
            pass
        await sleep(2)
    notice.update(message='Assist files are updated, but loading could not be confirmed. The HA restart was not repeated; check Home Assistant logs.', pending=False)


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
        return web.json_response({'maintenance':app.get('maintenance',{}),'version':VERSION,'agents':available,'installed':(config_root/'custom_components/pixora_voice/manifest.json').exists(),'notice':error})
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
        changed=await asyncio.to_thread(update_phrases,phrase_file,vocabulary)
        if changed is False:return 'Planner speech phrases are unchanged. No training was needed.'
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
    async def refresh_flows(request):
        from planner_phrases import update_voice_phrases
        try:
            result=await ha('services/pixora_voice/flow_vocabulary?return_response',{})
            vocabulary=result.get('service_response',{})
            if vocabulary.get('available') is not True:raise ValueError('Flows did not respond. Check the paired Home Control app and updated Assist integration.')
            values=vocabulary.get('phrases',[])
            changed=await asyncio.to_thread(update_voice_phrases,phrase_file.with_name('pixora_voice_flows.yaml'),values,vocabulary.get('variables',[]))
            await asyncio.to_thread(write_owned,config_root/'.storage'/'pixora_voice_flows.json',json.dumps(values))
            if changed is False:return web.json_response({'message':'Voice phrases are unchanged. No training was needed.'})
            await ha('services/hassio/addon_restart',{'addon':'core_speech-to-phrase'})
            return web.json_response({'message':str(len(values))+' voice trigger phrases saved. Speech-to-Phrase is restarting to learn them. Wait for training before speaking.'})
        except (ValueError,OSError,asyncio.TimeoutError,ClientError):
            return web.json_response({'error':'Voice trigger refresh or speech training could not be confirmed. Check the updated Assist integration, paired Home Control app and Speech-to-Phrase. It was not retried.'},status=503)
    async def install(request):
        try:await asyncio.to_thread(install_component,config_root,data_root)
        except ValueError as exc:return web.json_response({'error':str(exc)},status=409)
        return web.json_response({'message':'Assist integration installed. Restart Home Assistant once, add Pixora Voice under Settings → Devices & services, then select it in your local voice assistant.'})
    async def local_phrases(request):
        try:
            changed=await asyncio.to_thread(update_local_phrases,phrase_file.with_name('pixora_voice_language.yaml'))
            if changed is False:return web.json_response({'message':'Local speech phrases are unchanged. No training was needed.'})
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
    async def startup(app):
        app['session']=ClientSession(timeout=ClientTimeout(total=20))
        app['maintenance']={'message':'Voice and Assist update together automatically.', 'pending':False}
        try:
            record=await asyncio.to_thread(prepare_integration_update,config_root,data_root,phrase_file.with_name('pixora_voice_language.yaml'))
            if record:
                app['maintenance'].update(message='Updating Assist automatically…',pending=True)
                app['update_task']=asyncio.create_task(finish_integration_update(record,config_root,data_root,ha,app['maintenance']))
        except (ValueError,OSError,TypeError) as exc:
            app['maintenance'].update(message='Automatic Assist update needs attention: '+str(exc)[:180],pending=False)
    async def cleanup(app):
        task=app.get('update_task')
        if task:
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
        await app['session'].close()
    app.on_startup.append(startup);app.on_cleanup.append(cleanup)
    app.router.add_get('/',index);app.router.add_get('/icon.svg',icon);app.router.add_get('/api/status',status)
    app.router.add_get('/api/planner',planner_settings);app.router.add_post('/api/planner',planner_settings);app.router.add_post('/api/planner/refresh',refresh_planner)
    app.router.add_post('/api/install',install);app.router.add_post('/api/ask',ask)
    app.router.add_get('/api/timings',timings)
    app.router.add_post('/api/phrases',local_phrases)
    app.router.add_post('/api/flows/refresh',refresh_flows)
    return app

if __name__=='__main__':web.run_app(make_app(),host='0.0.0.0',port=4190)
