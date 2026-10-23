"""Opt-in, read-only Planner requests over the already paired HA connector."""
import asyncio,json,re,secrets,time
from pathlib import Path
DOMAIN='pixora_voice'
SETTINGS='pixora_voice_planner.json'
def is_planner_question(text):
 q=str(text).lower()
 if re.match(r'^(?:(?:can|could|would) you |please )?(turn|switch|set|dim|brighten)\b',q) and 'planner' not in q:return False
 return bool(re.search(r"\b(planner|schedule|calendar|agenda|appointments?|events?|games?|bruins|patriots|celtics|dinner|lunch|breakfast|meals?|menu|chores?|tasks?|grocer(?:y|ies)|shopping|pantry|notes?|messages?|countdowns?|alarms?|routines?|lists?)\b",q) or re.match(r'^(is|are|where)\b.*\b(home|away|arrived)\b',q) or re.match(r'^where is \w',q))
async def enabled(hass):
 def read():
  try:
   value=json.loads(Path(hass.config.path('.storage',SETTINGS)).read_text(encoding='utf-8'));return isinstance(value,dict) and value.get('enabled') is True
  except (OSError,ValueError,AttributeError):return False
 return await asyncio.to_thread(read)
def install_reply_service(hass):
 manager=hass.data.setdefault(DOMAIN,{});pending=manager.setdefault('planner_pending',{})
 async def receive(call):
  ident=call.data.get('request_id');speech=call.data.get('speech')
  future=pending.get(ident) if isinstance(ident,str) else None
  if future and not future.done() and isinstance(speech,str) and 0<len(speech)<=1500 and await enabled(hass):future.set_result(speech)
 if not hass.services.has_service(DOMAIN,'planner_reply'):hass.services.async_register(DOMAIN,'planner_reply',receive)
 async def vocabulary(call):
  raw=await ask(hass,'__pixora_voice_vocabulary__')
  try:value=json.loads(raw)
  except ValueError:return {'available':False}
  return {'available':True,'people':value.get('people',[]),'teams':value.get('teams',[])} if isinstance(value,dict) else {'available':False}
 if not hass.services.has_service(DOMAIN,'planner_vocabulary'):
  from homeassistant.core import SupportsResponse
  hass.services.async_register(DOMAIN,'planner_vocabulary',vocabulary,supports_response=SupportsResponse.ONLY)
async def ask(hass,text):
 if not await enabled(hass):return 'Planner integration is off. You can enable it in the Pixora Voice app.'
 pending=hass.data.setdefault(DOMAIN,{}).setdefault('planner_pending',{})
 if len(pending)>=2:return 'Planner is answering another question. Please try again in a moment.'
 ident=secrets.token_hex(16);future=asyncio.get_running_loop().create_future();pending[ident]=future
 try:
  hass.bus.async_fire('pixora_voice_planner_request',{'request_id':ident,'text':text[:500],'expires_at':time.time()+10})
  return await asyncio.wait_for(future,8)
 except asyncio.TimeoutError:return 'Planner did not respond. Check the Pixora Home Control connection. Your local home controls still work.'
 finally:pending.pop(ident,None)
