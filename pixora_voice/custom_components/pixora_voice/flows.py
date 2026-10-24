"""Explicit, exact voice phrases; Flow execution stays on the existing server."""
import asyncio,json,re,secrets,time
from pathlib import Path
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
 from homeassistant.core import SupportsResponse
 if not hass.services.has_service(DOMAIN,'flow_reply'):hass.services.async_register(DOMAIN,'flow_reply',receive)
 if not hass.services.has_service(DOMAIN,'flow_vocabulary'):hass.services.async_register(DOMAIN,'flow_vocabulary',vocabulary,supports_response=SupportsResponse.ONLY)

def variable_question(text):
 q=str(text).strip().rstrip('?.!')
 match=re.fullmatch(r"(?:what is|what's|read|tell me) (?:the )?(?:value of (?:the )?|variable )(.+?)(?: variable)?",q,re.I)
 if match:return match[1].strip()
 match=re.fullmatch(r"(?:what is|what's|read|tell me) (?:the )?(.+?) variable",q,re.I)
 return match[1].strip() if match else None
