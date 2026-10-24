"""On-demand weather and narrowly bounded Recorder history reads."""
import asyncio,re
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
from functools import partial
from homeassistant.exceptions import HomeAssistantError
from .engine import Result,choose,spoken_name,words,canonical_request
from .controls import select

def request_kind(text):
 q=canonical_request(text).lower().strip().rstrip('?.!')
 if re.fullmatch(r"(?:(?:what is|what's) (?:the )?(?:weather|forecast)(?: .*)?|(?:what is|what's) (?:it like|the temperature) outside|(?:will|does|is) it (?:rain|raining)(?: .*)?)",q):return 'weather'
 if re.match(r'^when (?:did|was)\b',q) and re.search(r'\b(last|open|opened|closed|locked|unlocked|turned)\b',q):return 'history'
 return None

def history_request(text):
 m=re.fullmatch(r'when did (?:the )?(.+?) (?:last )?(open|close|turn on|turn off|lock|unlock)[?.!]*',text,re.I)
 if not m:m=re.fullmatch(r'when was (?:the )?(.+?) last (opened|closed|turned on|turned off|locked|unlocked)[?.!]*',text,re.I)
 if not m:return None
 action={'opened':'open','closed':'close','turned on':'turn on','turned off':'turn off','locked':'lock','unlocked':'unlock'}.get(m[2].lower(),m[2].lower())
 return m[1],action

async def reply(hass,text,catalog,area=''):
 kind=request_kind(text)
 if not kind:return None
 try:zone=ZoneInfo(str(hass.config.time_zone))
 except (AttributeError,ValueError,ZoneInfoNotFoundError):return Result('Please set your time zone in Home Assistant before asking about forecasts or history.','capability')
 if kind=='weather':
  entity=select(catalog,'','weather','')
  if isinstance(entity,Result):return Result('Please share one weather entity with Assist so I know which forecast to use.','capability')
  if entity.state in {'unknown','unavailable'}:return Result("Your weather information isn't available right now.",'unavailable')
  q=' '.join(words(text));a=entity.attributes
  if re.search(r'\b(yesterday|week|weekend|month|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b',q):return Result('I can read current weather and forecasts for today or tomorrow. Please use one of those dates.','capability')
  if re.search(r'\b(?:in|at) [a-z]',q):return Result('I can read the weather from '+spoken_name(entity)+" in Home Assistant, but I don't have a separate forecast for that location.",'capability')

  if not re.search(r'\b(forecast|will|tomorrow|rain|raining)\b',q):
   condition=entity.state.replace('-',' ').replace('_',' ');temperature=a.get('temperature');unit=a.get('temperature_unit','')
   return Result("It's "+condition+' outside'+(' and '+str(temperature)+' '+unit if temperature is not None else '')+'.')
  features=int(a.get('supported_features') or 0);forecast_type='daily' if features&1 else 'hourly' if features&2 else None
  if not forecast_type or not hass.services.has_service('weather','get_forecasts'):return Result("Your weather entity doesn't provide a supported forecast.",'capability')
  try:response=await asyncio.wait_for(hass.services.async_call('weather','get_forecasts',{'entity_id':entity.entity_id,'type':forecast_type},blocking=True,return_response=True),5)
  except (HomeAssistantError,asyncio.TimeoutError):return Result("I can't read the forecast right now. Please try again later.",'unavailable')
  payload=(response or {}).get(entity.entity_id) if isinstance(response,dict) else None
  if not isinstance(payload,dict) or not isinstance(payload.get('forecast'),list):return Result("I couldn't read a valid forecast from that weather entity.",'unavailable')
  forecasts=payload['forecast'][:72]
  now=datetime.now(zone);day=(now+timedelta(days=1 if 'tomorrow' in q else 0)).date();matched=[]
  for item in forecasts:
   if not isinstance(item,dict):continue
   try:at=datetime.fromisoformat(str(item.get('datetime','')).replace('Z','+00:00'))
   except ValueError:continue
   if at.tzinfo is None:continue
   if at.astimezone(zone).date()==day:matched.append(item)
  label='tomorrow' if 'tomorrow' in q else 'today'
  if not matched:return Result("I don't have a forecast for "+label+'.','unavailable')
  if re.search(r'\b(?:rain|raining)\b',q):
   probabilities=[i['precipitation_probability'] for i in matched if isinstance(i.get('precipitation_probability'),(int,float)) and 0<=i['precipitation_probability']<=100]
   if probabilities:return Result('The forecast shows up to a '+str(max(probabilities))+' percent chance of precipitation '+label+'.')
   wet=any(i.get('condition') in {'rainy','pouring','lightning-rainy','snowy-rainy'} for i in matched)
   return Result(('Rain is in the forecast '+label+'.') if wet else "The forecast doesn't list rain "+label+", but it doesn't give a rain probability.")
  item=matched[0];condition=str(item.get('condition') or 'No conditions listed').replace('-',' ')
  return Result('The forecast for '+label+' is '+condition+('.' if item.get('temperature') is None else ', with a temperature of '+str(item['temperature'])+' '+str(a.get('temperature_unit',''))+'.'))
 parsed=history_request(text)
 if not parsed:return Result('Try asking when a specific door last opened or closed. I can check the last 24 hours.','capability')
 target,action=parsed;prop='opening' if action in {'open','close'} else 'lock' if action in {'lock','unlock'} else 'power'
 rows=choose('is '+target+' '+('open' if prop=='opening' else 'locked' if prop=='lock' else 'on'),catalog,prop,area)
 if not rows:return Result("I can't find that shared device to check its history.",'capability')
 best=rows[0][0];matches=[e for score,e in rows if score==best]
 if len(matches)!=1:return Result('Which device do you mean? Please include its full name and room.','capability')
 entity=matches[0];wanted={'open':'on' if entity.domain=='binary_sensor' else 'open','close':'off' if entity.domain=='binary_sensor' else 'closed','lock':'locked','unlock':'unlocked','turn on':'on','turn off':'off'}[action]
 state=hass.data.setdefault('pixora_voice',{})
 task=state.get('history_task')
 if task and not task.done():return Result("I'm still checking a recent history request. Please give it a moment.",'unavailable')
 try:
  from homeassistant.components.recorder import get_instance
  from homeassistant.components.recorder.history import get_significant_states
  now=datetime.now(timezone.utc)
  task=asyncio.ensure_future(get_instance(hass).async_add_executor_job(partial(get_significant_states,hass,now-timedelta(hours=24),now,[entity.entity_id],include_start_time_state=False,significant_changes_only=True,no_attributes=True)))
  task.add_done_callback(lambda done:done.exception() if not done.cancelled() else None)
  state['history_task']=task
  result=await asyncio.wait_for(asyncio.shield(task),5)
 except (ImportError,HomeAssistantError,asyncio.TimeoutError,KeyError,RuntimeError,ValueError):return Result("I couldn't read that history. Recorder must be available; I only check one device over the last 24 hours.",'unavailable')
 rows=result.get(entity.entity_id,[])
 changed=[item for item in rows if getattr(item,'state',None)==wanted and isinstance(getattr(item,'last_changed',None),datetime) and item.last_changed.tzinfo is not None]
 if not changed:return Result("I don't see that change recorded in the last 24 hours.")
 last=max(item.last_changed for item in changed).astimezone(zone)
 return Result(spoken_name(entity)+' was last recorded '+{'open':'open','close':'closed','lock':'locked','unlock':'unlocked','turn on':'on','turn off':'off'}[action]+' at '+last.strftime('%I:%M %p').lstrip('0')+(' today.' if last.date()==datetime.now(zone).date() else ' yesterday.'))
