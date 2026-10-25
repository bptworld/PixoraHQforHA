"""Explicit, exact voice phrases; Flow execution stays on the existing server."""
import asyncio,json,re,secrets,time,hashlib,logging
from pathlib import Path
from aiohttp import ClientError
from homeassistant.exceptions import HomeAssistantError
DOMAIN='pixora_voice'

def normalized(text):return ' '.join(re.findall(r'[a-z0-9]+',str(text).lower()))

async def phrases(hass):
 def read():
  try:value=json.loads(Path(hass.config.path('.storage','pixora_voice_flows.json')).read_text(encoding='utf-8'))
  except (AttributeError,OSError,ValueError):return []
  return value[:64] if isinstance(value,list) and all(isinstance(p,str) and 0<len(p)<=100 for p in value) else []
 return await asyncio.to_thread(read)

async def matches(hass,text):return any(normalized(p)==normalized(text) for p in await phrases(hass))

async def ask(hass,text):
 pending=hass.data.setdefault(DOMAIN,{}).setdefault('flow_pending',{})
 if len(pending)>=2:return "I'm still waiting to hear back about a Flow. Please check its history before trying again."
 ident=secrets.token_hex(16);future=asyncio.get_running_loop().create_future();pending[ident]=future
 try:
  hass.bus.async_fire('pixora_voice_flow_request',{'request_id':ident,'text':text[:500],'expires_at':time.time()+10})
  return await asyncio.wait_for(future,8)
 except (asyncio.TimeoutError,HomeAssistantError,OSError):return "I'm not sure whether that Flow started. Please check its history before trying again."
 finally:pending.pop(ident,None)

def install_services(hass):
 async def receive(call):
  future=hass.data.setdefault(DOMAIN,{}).setdefault('flow_pending',{}).get(call.data.get('request_id'))
  speech=call.data.get('speech')
  if future and not future.done() and isinstance(speech,str) and 0<len(speech)<=12000:future.set_result(speech)
 async def vocabulary(call):
  try:value=json.loads(await ask(hass,'__pixora_voice_flow_vocabulary__'))
  except ValueError:return {'available':False}
  return {'available':True,'phrases':value.get('phrases',[]),'variables':value.get('variables',[])} if isinstance(value,dict) else {'available':False}
 async def refresh(call):
  user_id=getattr(getattr(call,'context',None),'user_id',None)
  if user_id:
   user=await hass.auth.async_get_user(user_id)
   if not user or not user.is_admin:raise HomeAssistantError('An administrator must refresh speech training.')
  state=hass.data.setdefault(DOMAIN,{})
  if state.get('flow_refresh_busy'):raise HomeAssistantError('Voice trigger training is already being requested. It was not repeated.')
  state['flow_refresh_busy']=True
  try:
   value=getattr(call,'data',None)
   if not isinstance(value,dict) or not isinstance(value.get('phrases'),list) or not isinstance(value.get('variables'),list):raise HomeAssistantError('Choose saved Flow phrases before refreshing speech training.')
   from .phrase_tools import update_voice_phrases,write_owned,vocabulary_signature,validate_voice_vocabulary
   validate_voice_vocabulary(value['phrases'],value['variables'])
   from .speech_training import uses_groq
   groq=await uses_groq(hass)
   path=Path('/share/speech-to-phrase/custom_sentences/en/pixora_voice_flows.yaml')
   changed=False if groq else await asyncio.to_thread(update_voice_phrases,path,value.get('phrases',[]),value.get('variables',[]))
   await asyncio.to_thread(write_owned,Path(hass.config.path('.storage','pixora_voice_flows.json')),json.dumps(value.get('phrases',[])))
   signature=vocabulary_signature(value['phrases'],value['variables'])
   def progress(status):
    hass.states.async_set('sensor.pixora_voice_training',status,{'friendly_name':'Pixora Voice training','signature':signature,'updated_at':time.time()})
   if groq:
    progress('complete')
    state['flow_refresh_busy']=False
    return
   if changed is False:
    progress('unchanged')
    state['flow_refresh_busy']=False
    return
   progress('restarting')
   async def restart():
    try:
     from .speech_training import read_status,wait_ready
     try:
      baseline=(await read_status(hass)).get('generation');can_verify=True
     except (RuntimeError,ValueError,OSError,KeyError,ClientError,asyncio.TimeoutError):baseline=None;can_verify=False
     await hass.services.async_call('hassio','addon_restart',{'addon':'core_speech-to-phrase'},blocking=True)
     progress('training')
     progress('complete' if can_verify and await wait_ready(hass,previous=baseline) else 'failed')
    except asyncio.CancelledError:
     progress('failed')
     raise
    except (HomeAssistantError,ValueError,OSError,ClientError,asyncio.TimeoutError):
     progress('failed')
     logging.getLogger(__name__).warning('Speech restart was not confirmed. No automatic retry.')
    finally:state['flow_refresh_busy']=False
   hass.async_create_task(restart())
  except (ValueError,OSError,asyncio.TimeoutError,HomeAssistantError):
   state['flow_refresh_busy']=False
   raise HomeAssistantError('Voice refresh could not be confirmed. Check Pixora Voice and Speech-to-Phrase before trying again.')
 async def speech_ready(call):
  from .speech_training import read_status
  try:return await read_status(hass)
  except (RuntimeError,ValueError,OSError,KeyError,ClientError,asyncio.TimeoutError):return {'ready':False}
 from homeassistant.core import SupportsResponse
 if not hass.services.has_service(DOMAIN,'speech_ready'):hass.services.async_register(DOMAIN,'speech_ready',speech_ready,supports_response=SupportsResponse.ONLY)
 if not hass.services.has_service(DOMAIN,'refresh_flow_phrases'):hass.services.async_register(DOMAIN,'refresh_flow_phrases',refresh)
 if not hass.services.has_service(DOMAIN,'flow_reply'):hass.services.async_register(DOMAIN,'flow_reply',receive)
 if not hass.services.has_service(DOMAIN,'flow_vocabulary'):hass.services.async_register(DOMAIN,'flow_vocabulary',vocabulary,supports_response=SupportsResponse.ONLY)
