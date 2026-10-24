"""Parse a bounded timer request and hand it to Home Assistant's native timers."""
import asyncio,re
from homeassistant.exceptions import HomeAssistantError
from .voice_numbers import number

def timer_request(text):
 q=str(text).strip().lower().rstrip('?.!')
 q=re.sub(r"^(?:please |(?:can|could|would) you )",'',q)
 if 'timer' not in q and q not in {'how much time is left','how much time is remaining'}:return None
 if re.search(r'\b(not|never|unless|except|if|then)\b',q):return ('unsupported',{})
 start=re.fullmatch(r'(?:set|start) (?:a |an )?(?:(.+?) )?timer for (.+)',q)
 if not start:start=re.fullmatch(r'(?:set|start) (?:a |an )?(.+?) timer(?: called (.+))?',q);start=(start[2],start[1]) if start else None
 else:start=(start[1],start[2])
 if start:
  name,duration=start;slots={};remaining=duration
  for unit,mult in (('hours',3600),('minutes',60),('seconds',1)):
   match=re.search(r'([a-z -]+|\d+(?:\.\d+)?) '+unit.rstrip('s')+r's?\b',remaining)
   if match:
    value=number(match[1].strip().removeprefix('and '))
    if value is None or value!=int(value) or value<0:return ('unsupported',{})
    slots[unit]=int(value);remaining=remaining[:match.start()]+remaining[match.end():]
  if re.sub(r'\band\b','',remaining).strip(' ,') or not slots or not 1<=sum(slots.get(u,0)*m for u,m in (('hours',3600),('minutes',60),('seconds',1)))<=86400:return ('unsupported',{})
  if name:
   if not re.fullmatch(r'[a-z0-9 ]{1,40}',name):return ('unsupported',{})
   slots['name']=name
  return 'HassStartTimer',slots
 m=re.fullmatch(r'(cancel|pause|resume) (?:the |my )?(?:(.+?) )?timer',q)
 if m:return {'cancel':'HassCancelTimer','pause':'HassPauseTimer','resume':'HassUnpauseTimer'}[m[1]],({'name':m[2]} if m[2] else {})
 m=re.fullmatch(r'(?:how much time is (?:left|remaining)(?: on (?:the |my )?(?:(.+?) )?timer)?|timer status)',q)
 if m:return 'HassTimerStatus',({'name':m[1]} if m[1] else {})
 return 'unsupported',{}

async def reply(hass,request):
 parsed=timer_request(request.text)
 if parsed is None:return None
 kind,values=parsed
 if kind=='unsupported':return 'Try “set a timer for ten minutes,” “pause the timer,” or “how much time is left?” Timers can be up to 24 hours.'
 if not request.device_id:return 'Please ask a timer-capable satellite so the timer can ring on that speaker.'
 uid=request.context.user_id
 if uid and not await hass.auth.async_get_user(uid):return "I can't manage timers from this account. Please check its permissions."
 try:
  from homeassistant.helpers import intent
  response=await asyncio.wait_for(intent.async_handle(hass,'conversation',kind,{k:{'value':v} for k,v in values.items()},text_input=request.text,context=request.context,language='en',assistant='conversation',device_id=request.device_id,satellite_id=getattr(request,'satellite_id',None)),5)
  if getattr(getattr(response,'response_type',None),'value',None)=='error':return 'Home Assistant could not confirm that timer request. Please check your timers before trying again.'
  if kind=='HassTimerStatus':
   timers=[t for t in getattr(response,'speech_slots',{}).get('timers',[]) if t.get('device_id')==request.device_id]
   if not timers:return "You don't have a matching timer running."
   return ' '.join((t.get('name') or 'Your timer')+' has '+str(t.get('hours_left',0))+' hours, '+str(t.get('minutes_left',0))+' minutes and '+str(t.get('seconds_left',0))+' seconds left'+(' and is paused.' if not t.get('is_active') else '.') for t in timers[:3])
  if kind=='HassStartTimer':
   duration=', '.join(str(v)+' '+k for k,v in values.items() if k!='name' and v)
   return 'Okay, '+('your '+values['name']+' timer' if values.get('name') else 'your timer')+' is set for '+duration+'.'
  return {'HassCancelTimer':'Okay, the timer is cancelled.','HassPauseTimer':'Okay, the timer is paused.','HassUnpauseTimer':'Okay, the timer is running again.'}[kind]
 except asyncio.TimeoutError:return "I'm not sure whether that timer request went through. Please check your timers before trying again."
 except HomeAssistantError as exc:
  key=getattr(exc,'response_key','')
  if key=='no_timer_support':return "That speaker doesn't report native timer support in Home Assistant."
  if key=='timer_not_found':return "I couldn't find a matching timer."
  if key=='multiple_timers_matched':return 'You have more than one matching timer. Please include its name.'
  return "Home Assistant couldn't confirm that timer request. Please check your timers before trying again."
