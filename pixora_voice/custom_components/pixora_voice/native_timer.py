import asyncio,re
from homeassistant.exceptions import HomeAssistantError
async def reply(hass,request,data):
 kind=data.get('kind');values=data.get('values')
 if kind not in {'HassStartTimer','HassCancelTimer','HassPauseTimer','HassUnpauseTimer','HassTimerStatus'} or not isinstance(values,dict) or set(values)-{'hours','minutes','seconds','name'}:raise HomeAssistantError('Invalid timer request.')
 if any(type(v) is not int or v<0 for k,v in values.items() if k!='name') or 'name' in values and (not isinstance(values['name'],str) or not re.fullmatch(r'[a-z0-9 ]{1,40}',values['name'])):raise HomeAssistantError('Invalid timer values.')
 if kind=='HassStartTimer' and not 1<=sum(values.get(k,0)*m for k,m in (('hours',3600),('minutes',60),('seconds',1)))<=86400:raise HomeAssistantError('Timer duration out of range.')
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
