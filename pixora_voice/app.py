"""Local Voice runtime and ingress UI; the stable HA bridge retains authorization."""
import asyncio,json,os,shutil,tempfile,time,logging
from pathlib import Path
from aiohttp import web,ClientSession,ClientTimeout,ClientError

VERSION='0.2.2'
COMPONENT=Path(__file__).parent/'custom_components'/'pixora_voice'
# Assist changes have their own release identity; app-only updates keep this unchanged.
INTEGRATION_VERSION=json.loads((COMPONENT/'manifest.json').read_text(encoding='utf-8'))['version']


async def configure_bridge(session,config_root):
    """Publish only a Supervisor-provided internal address and persistent private bridge key."""
    import secrets,re
    path=config_root/'.storage/pixora_voice_bridge.json'
    try:previous=json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:previous={}
    if not isinstance(previous,dict):raise ValueError('Local bridge settings need repair.')
    key=previous.get('token')
    # Preserve the established local connection across app updates, even while
    # Supervisor is temporarily unavailable. No background polling or key rotation.
    if isinstance(key,str) and re.fullmatch(r'[a-f0-9]{64}',key) and re.fullmatch(r'http://[a-z0-9-]+-pixora-voice:4190',previous.get('url','')):return
    token=os.environ.get('SUPERVISOR_TOKEN','')
    if not token:raise ValueError('Home Assistant access is unavailable.')
    async with session.get('http://supervisor/addons/self/info',headers={'Authorization':'Bearer '+token},timeout=ClientTimeout(total=10)) as response:
        if response.status!=200:raise ValueError('Local app address unavailable.')
        value=await response.json()
    hostname=value.get('data',{}).get('hostname','')
    if not re.fullmatch(r'[a-z0-9-]+-pixora-voice',hostname):raise ValueError('Unexpected local app address.')
    if not isinstance(key,str) or not re.fullmatch(r'[a-f0-9]{64}',key):key=secrets.token_hex(32)
    from planner_phrases import write_owned
    await asyncio.to_thread(write_owned,path,json.dumps({'url':'http://'+hostname+':4190','token':key}))


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


def prepare_integration_update(config_root, data_root, phrase_file=None):
    """Update only our recognized component; journal a restart before issuing it."""
    from planner_phrases import write_owned
    journal = data_root / 'integration-update.json'
    record = json.loads(journal.read_text()) if journal.exists() else {}
    if not isinstance(record, dict):raise ValueError('Integration update record needs attention.')
    from speech_settings import read_settings
    if read_settings(config_root).get('enabled'):
        phrase_file=None
        record['speechNeeded']=False
    manifest = config_root / 'custom_components/pixora_voice/manifest.json'
    exists = manifest.exists()
    installed = json.loads(manifest.read_text()) if exists else {}
    if not isinstance(installed,dict) or exists and (installed.get('domain')!='pixora_voice' or installed.get('codeowners')!=['@bptworld']):raise ValueError('An unrecognized Assist folder was preserved; automatic update stopped.')
    if installed.get('version') == INTEGRATION_VERSION:
        if record.get('version') == INTEGRATION_VERSION and record.get('phase') == 'prepared':
            if record.get('speechNeeded'):
                if not phrase_file:raise ValueError('Speech phrase recovery needs its saved destination.')
                from planner_phrases import update_local_phrases
                update_local_phrases(phrase_file)
            record['phase'] = 'installed'
            write_owned(journal, json.dumps(record))
        return record if record.get('version') == INTEGRATION_VERSION and record.get('phase') != 'complete' else None
    # Keep the running integration intact until Restart now is approved. Its
    # dynamically imported modules may still be needed while the user chooses Later.
    if exists and record.get('version') == INTEGRATION_VERSION and record.get('phase') in {'awaiting-restart','restart-approved','restart-requested'}:
        return record
    from planner_phrases import update_local_phrases
    speech_changed = update_local_phrases(phrase_file,check_only=True) if phrase_file else False
    record = {'version': INTEGRATION_VERSION, 'phase': 'awaiting-restart' if exists else 'prepared',
              'needRestart': exists, 'speechNeeded': speech_changed, 'activationPending': exists,
              'phraseFile': str(phrase_file) if phrase_file else None}
    write_owned(journal, json.dumps(record))
    if exists:return record
    install_component(config_root, data_root)
    if phrase_file:update_local_phrases(phrase_file)
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
    notice['restartRequired']=False
    journal = data_root / 'integration-update.json'
    def save(phase):
        record['phase'] = phase
        write_owned(journal, json.dumps(record))
    # Reads may recover from startup. The restart command is issued at most once.
    for _ in range(45):
        try:
            states = await ha('states')
            agents = [s for s in states if s.get('entity_id','').startswith('conversation.') and s.get('attributes',{}).get('friendly_name') in {'Pixora Voice','Pixora Voice (Beta)'}]
            if not record.get('activationPending') and any(s.get('attributes',{}).get('pixora_voice_version') == INTEGRATION_VERSION for s in agents):
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
            if record['phase'] in {'prepared','installed','awaiting-restart'}:
                await asyncio.to_thread(save, 'awaiting-restart')
                notice.update(message='Voice and Assist files are updated. Restart Home Assistant when you are ready to load them.',pending=False,restartRequired=True)
                return
            if record['phase'] == 'restart-approved':
                await asyncio.to_thread(install_component, config_root, data_root)
                record['activationPending']=False
                from speech_settings import read_settings
                if record.get('phraseFile') and not read_settings(config_root).get('enabled'):
                    from planner_phrases import update_local_phrases
                    record['speechNeeded'] = await asyncio.to_thread(update_local_phrases, Path(record['phraseFile']))
                else:record['speechNeeded'] = False
                await asyncio.to_thread(save, 'restart-requested')
                notice.update(message='Home Assistant is restarting once as requested. Waiting for Voice to return.', pending=True,restartRequired=False)
                try:await ha('services/homeassistant/restart', {})
                except (ValueError,ClientError,asyncio.TimeoutError):pass
        except (ValueError,ClientError,asyncio.TimeoutError):
            pass
        await sleep(2)
    notice.update(message='Assist files are updated, but loading could not be confirmed. The HA restart was not repeated; check Home Assistant logs.', pending=False)


def make_app(config_root=Path('/homeassistant'),data_root=Path('/data')):
    @web.middleware
    async def ingress(request,handler):
        if request.path.startswith('/bridge/'):
            import hmac
            token=app.get('bridge_token','')
            supplied=request.headers.get('X-Pixora-Bridge','')
            if not token or not hmac.compare_digest(token,supplied):raise web.HTTPForbidden(text='Local bridge authorization required.')
            return await handler(request)
        if request.remote!='172.30.32.2':raise web.HTTPForbidden(text='Open Pixora Voice from Home Assistant.')
        if request.content_length and request.content_length>4096:raise web.HTTPRequestEntityTooLarge(max_size=4096,actual_size=request.content_length)
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
    app=web.Application(middlewares=[ingress],client_max_size=2*1024*1024)

    async def ha(path,body=None):
        token=os.environ.get('SUPERVISOR_TOKEN','')
        if not token:raise ValueError('Home Assistant access is unavailable.')
        async with app['session'].request('POST' if body is not None else 'GET','http://supervisor/core/api/'+path,headers={'Authorization':'Bearer '+token},json=body,timeout=ClientTimeout(total=60 if path=='services/hassio/addon_restart' else 20)) as response:
            if response.status>=400:raise ValueError('Home Assistant could not confirm the request (HTTP '+str(response.status)+'). It was not retried.')
            return await response.json()

    async def bridge_request(request):
        try:
            payload=await request.json()
            if not isinstance(payload,dict) or not isinstance(payload.get('text'),str) or not 0<len(payload['text'])<=2000 or not isinstance(payload.get('catalog'),list) or len(payload['catalog'])>5000 or not isinstance(payload.get('request_id'),str):raise web.HTTPBadRequest(text='Invalid local request.')
            app['ha_timezone']=payload.get('timezone','UTC')
            async with asyncio.timeout(28):result=await app['runtime'].answer(payload)
            return web.json_response(result)
        except (ValueError,KeyError,TypeError,RuntimeError,asyncio.TimeoutError):
            return web.json_response({'speech':"I couldn't finish that request. Please check any device you asked to control before trying again."},status=503)
    async def bridge_speech(request):
        from runtime.speech import transcribe,MAX_AUDIO
        if request.content_length and request.content_length>MAX_AUDIO:raise web.HTTPRequestEntityTooLarge(max_size=MAX_AUDIO,actual_size=request.content_length)
        if app.get('speech_active',0)>=2:return web.json_response({'text':None},status=503)
        app['speech_active']=app.get('speech_active',0)+1
        audio=bytearray()
        try:
            async with asyncio.timeout(5):
                async for chunk in request.content.iter_chunked(16384):
                    if len(audio)+len(chunk)>MAX_AUDIO:raise web.HTTPRequestEntityTooLarge(max_size=MAX_AUDIO,actual_size=len(audio)+len(chunk))
                    audio.extend(chunk)
            result=await transcribe(app['session'],config_root,audio,request.headers.get('X-Pixora-Timezone',app.get('ha_timezone','UTC'))[:80])
            return web.json_response(result)
        finally:
            audio.clear();app['speech_active']-=1

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
    async def voice_log(request):
        from diagnostics import recent_runs
        try:
            async with asyncio.timeout(20):
                available=await agents()
                runs=await recent_runs(app['session'],os.environ.get('SUPERVISOR_TOKEN',''),available,limit=20,include_text=True)
            return web.json_response({'runs':runs})
        except (ValueError,KeyError,TypeError,asyncio.TimeoutError,ClientError):
            return web.json_response({'error':'Voice log is unavailable right now. Check HA Voice assistants → Debug. No commands or restarts were sent.'},status=503)
    async def icon(request):return web.FileResponse(Path(__file__).with_name('icon.svg'))
    from speech_settings import read_settings,save_settings,public_settings
    async def speech_settings(request):
        try:
            if request.method=='POST':
                if request.headers.get('X-Pixora-Request')!='1':raise ValueError('Use Save speech settings in the Voice app.')
                result=await asyncio.to_thread(save_settings,config_root,await request.json())
                return web.json_response({**result,'message':'Speech settings saved. Select Pixora Groq Whisper under the assistant’s Speech-to-text setting. No restart or phrase training is needed for key changes.'})
            return web.json_response(await asyncio.to_thread(lambda:public_settings(read_settings(config_root))))
        except (ValueError,OSError):
            return web.json_response({'error':'Speech settings could not be saved or read. Enter a valid Groq key before enabling, or check local storage.'},status=400)
    async def speech_test(request):
        try:
            if request.headers.get('X-Pixora-Request')!='1':raise ValueError('Use Test connection in Voice.')
            settings=await asyncio.to_thread(read_settings,config_root)
            if not settings.get('key'):return web.json_response({'error':'Save your Groq API key first.'},status=400)
            async with app['session'].get('https://api.groq.com/openai/v1/models',headers={'Authorization':'Bearer '+settings['key']},timeout=ClientTimeout(total=10),allow_redirects=False) as response:
                if response.status!=200:
                    message={401:'Groq rejected the API key.',403:'Groq denied access.',429:'Groq rate limit reached.'}.get(response.status,'Groq is unavailable right now.')
                    return web.json_response({'error':message+' No audio or command was sent.'},status=503)
                return web.json_response({'message':'Connected to Groq. Your saved key was accepted. No audio was sent; test a satellite next.'})
        except (OSError,ValueError,ClientError,asyncio.TimeoutError):
            return web.json_response({'error':'Could not reach Groq. Check your internet connection and saved key. No audio or command was sent.'},status=503)
    async def speech_stats(request):
        from speech_settings import read_stats
        try:
            settings=await asyncio.to_thread(read_settings,config_root)
            return web.json_response(await asyncio.to_thread(read_stats,config_root,settings.get('key','')))
        except (OSError,ValueError):return web.json_response({'error':'Speech usage is unavailable. No requests were sent.'},status=503)
    async def retire_speech(request):
        try:
            if request.headers.get('X-Pixora-Request')!='1' or not (await asyncio.to_thread(read_settings,config_root)).get('enabled'):
                return web.json_response({'error':'Enable Groq before removing local phrase files.'},status=400)
            from planner_phrases import retire_phrase_files
            removed=await asyncio.to_thread(retire_phrase_files,Path('/share/speech-to-phrase/custom_sentences/en'),data_root/'retired-speech-phrases')
            return web.json_response({'removed':removed,'message':'Removed '+str(len(removed))+' Pixora training files. A recovery copy stays in the Voice app’s private data. Saved Flow trigger definitions and user-owned sentences were preserved.'})
        except (OSError,ValueError):return web.json_response({'error':'Phrase cleanup stopped. Files without a verified recovery copy were preserved.'},status=409)
    async def status(request):
        try:available=await agents();error=''
        except (ValueError,asyncio.TimeoutError,ClientError):available=[];error='Home Assistant is reconnecting. Try again shortly.'
        return web.json_response({'maintenance':app.get('maintenance',{}),'version':VERSION,'agents':available,'installed':(config_root/'custom_components/pixora_voice/manifest.json').exists(),'notice':error})
    async def restart_now(request):
        body=await request.json()
        if request.headers.get('X-Pixora-Request') != '1' or not isinstance(body,dict) or body.get('confirm') is not True:
            return web.json_response({'error':'Confirm Restart now in the Voice app.'},status=400)
        async with app['restart_lock']:
            task=app.get('update_task')
            if task and not task.done():
                return web.json_response({'error':'An update operation is already running. No additional restart was sent.'},status=409)
            journal=data_root/'integration-update.json'
            try:
                record=json.loads(journal.read_text())
                if not isinstance(record,dict) or record.get('version')!=INTEGRATION_VERSION or record.get('phase')!='awaiting-restart':
                    raise ValueError('No pending restart is available. Refresh Voice status.')
                from planner_phrases import write_owned
                record['phase']='restart-approved'
                await asyncio.to_thread(write_owned,journal,json.dumps(record))
            except (ValueError,OSError,TypeError) as exc:
                return web.json_response({'error':str(exc)},status=409)
            app['maintenance'].update(message='Restart approved. Waiting for Home Assistant to restart and Voice to return.',pending=True,restartRequired=False)
            app['update_task']=asyncio.create_task(finish_integration_update(record,config_root,data_root,ha,app['maintenance']))
            return web.json_response({'message':'Restart approved. Voice will check readiness when Home Assistant returns.'})
    from planner_phrases import write_owned,update_phrases,update_local_phrases
    def groq_enabled():return read_settings(config_root).get('enabled') is True
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
        if await asyncio.to_thread(groq_enabled):return 'Planner is connected. Groq does not need phrase files or training.'
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
            if await asyncio.to_thread(groq_enabled):
                from planner_phrases import validate_voice_vocabulary
                validate_voice_vocabulary(values,vocabulary.get('variables',[]))
                await asyncio.to_thread(write_owned,config_root/'.storage'/'pixora_voice_flows.json',json.dumps(values))
                return web.json_response({'message':'Voice triggers saved. Groq is ready; no phrase files, training or restart needed.'})
            changed=await asyncio.to_thread(update_voice_phrases,phrase_file.with_name('pixora_voice_flows.yaml'),values,vocabulary.get('variables',[]))
            await asyncio.to_thread(write_owned,config_root/'.storage'/'pixora_voice_flows.json',json.dumps(values))
            if changed is False:return web.json_response({'message':'Voice phrases are unchanged. No training was needed.'})
            await ha('services/hassio/addon_restart',{'addon':'core_speech-to-phrase'})
            return web.json_response({'message':str(len(values))+' voice trigger phrases saved. Speech-to-Phrase is restarting to learn them. Wait for training before speaking.'})
        except (ValueError,OSError,asyncio.TimeoutError,ClientError):
            return web.json_response({'error':'Voice trigger refresh or speech training could not be confirmed. Check the updated Assist integration, paired Home Control app and Speech-to-Phrase. It was not retried.'},status=503)
    async def install(request):
        try:
            manifest=config_root/'custom_components/pixora_voice/manifest.json'
            if manifest.exists():
                value=json.loads(manifest.read_text())
                if not isinstance(value,dict) or value.get('domain')!='pixora_voice' or value.get('codeowners')!=['@bptworld']:raise ValueError('An unrecognized Assist folder was preserved.')
                if app.get('update_task') and not app['update_task'].done():return web.json_response({'error':'An update is already running.'},status=409)
                from planner_phrases import write_owned
                record={'version':INTEGRATION_VERSION,'phase':'awaiting-restart','needRestart':True,'speechNeeded':False,'activationPending':True}
                await asyncio.to_thread(write_owned,data_root/'integration-update.json',json.dumps(record))
                app['maintenance'].update(message='Assist repair is ready. Current files stay intact until you choose Restart now.',pending=False,restartRequired=True)
                return web.json_response({'message':'Assist repair is ready. Choose Restart now when convenient; Later keeps the current integration unchanged.'})
            await asyncio.to_thread(install_component,config_root,data_root)
        except (ValueError,OSError) as exc:return web.json_response({'error':str(exc)},status=409)
        return web.json_response({'message':'Assist integration installed. Add Pixora Voice under Settings → Devices & services, then select it in your local voice assistant.'})
    async def local_phrases(request):
        if await asyncio.to_thread(groq_enabled):return web.json_response({'message':'Groq does not use phrase files. No training or restart needed.'})
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
        app['maintenance']={'message':'Checking the local Voice bridge.', 'pending':False}
        from runtime.server import Runtime
        app['runtime']=Runtime(config_root,ha)
        try:
            await configure_bridge(app['session'],config_root)
            bridge=json.loads((config_root/'.storage/pixora_voice_bridge.json').read_text(encoding='utf-8'))
            app['bridge_token']=bridge['token']
        except (OSError,ValueError,KeyError,TypeError,ClientError,asyncio.TimeoutError):
            app['maintenance'].update(message='Local Voice connection could not be prepared. No restart was requested.',pending=False)
            return
        try:
            record=await asyncio.to_thread(prepare_integration_update,config_root,data_root,phrase_file.with_name('pixora_voice_language.yaml'))
            if record:
                app['maintenance'].update(message='Updating Assist automatically…',pending=True)
                app['update_task']=asyncio.create_task(finish_integration_update(record,config_root,data_root,ha,app['maintenance']))
            else:
                app['maintenance'].update(message='Voice app is up to date. Assist files are unchanged; no Home Assistant restart needed.',pending=False,restartRequired=False)
        except (ValueError,OSError,TypeError) as exc:
            app['maintenance'].update(message='Automatic Assist update needs attention: '+str(exc)[:180],pending=False)
    async def cleanup(app):
        task=app.get('update_task')
        if task:
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
        await app['session'].close()
    app.on_startup.append(startup);app.on_cleanup.append(cleanup)
    app['restart_lock']=asyncio.Lock()
    app.router.add_post('/bridge/request',bridge_request);app.router.add_post('/bridge/speech',bridge_speech)
    app.router.add_get('/',index);app.router.add_get('/icon.svg',icon);app.router.add_get('/api/status',status)
    app.router.add_get('/api/planner',planner_settings);app.router.add_post('/api/planner',planner_settings);app.router.add_post('/api/planner/refresh',refresh_planner)
    app.router.add_post('/api/install',install);app.router.add_post('/api/ask',ask)
    app.router.add_get('/api/timings',timings)
    app.router.add_get('/api/voice-log',voice_log)
    app.router.add_get('/api/speech',speech_settings);app.router.add_post('/api/speech',speech_settings)
    app.router.add_post('/api/speech/test',speech_test)
    app.router.add_get('/api/speech/stats',speech_stats)
    app.router.add_post('/api/speech/retire-phrases',retire_speech)
    app.router.add_post('/api/restart',restart_now)
    app.router.add_post('/api/phrases',local_phrases)
    app.router.add_post('/api/flows/refresh',refresh_flows)
    return app

if __name__=='__main__':web.run_app(make_app(),host='0.0.0.0',port=4190)
