"""Parse a bounded timer request and hand it to Home Assistant's native timers."""
import asyncio,re

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
 return await hass.rpc('timer',{'kind':kind,'values':values})
