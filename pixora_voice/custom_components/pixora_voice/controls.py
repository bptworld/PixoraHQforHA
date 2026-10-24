"""Bounded capability-driven control plans. No service calls or entity guessing."""
import re,math
from .engine import Result,canonical_request,normalized,spoken_name
from .voice_numbers import number
COLORS={'red':(255,0,0),'green':(0,255,0),'blue':(0,0,255),'white':(255,255,255),'yellow':(255,255,0),'orange':(255,165,0),'purple':(128,0,128),'pink':(255,105,180)}
STOP=set('the a an it that in here this light lights lamp lamps fan fans thermostat heat heating temperature blinds blind shade shades curtain curtains scene speaker speakers player tv television'.split())
def finite(value):return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)
def select(catalog,target,domain,area):
 tokens=set(normalized(target))-STOP
 rows=[e for e in catalog if e.exposed and e.domain==domain and (not tokens or any(tokens<=set(normalized(name+' '+e.area)) for name in [e.name,*e.aliases]))]
 if 'here' in normalized(target) and not area:return Result('Which room do you mean? Please include the room name.','capability')
 if not tokens or 'here' in normalized(target):
  local=[e for e in rows if e.area and normalized(e.area)==normalized(area)]
  if local:rows=local
  elif 'here' in normalized(target):rows=[]
 if len(rows)!=1:
  return Result("I can't find that shared device. Try its full name and room." if not rows else 'More than one device matches. Please say its full name or room.','capability')
 return rows[0]
def plan(text,catalog,area=''):
 q=re.sub(r"what['’]s",'what is',canonical_request(text),flags=re.I).strip().rstrip('?.!');domain=service=target='';params={};feature=0;mode=''
 # Full matches avoid guessing chained, conditional or security commands.
 if re.search(r'\b(not|never|unless|except|if|when|and|then)\b',q,re.I):
  if re.match(r"^(?:do not |don't |never )?(?:turn|switch|set|make|dim|brighten|open|close|lock|unlock|activate|run|play|pause|resume|stop|mute|unmute|raise|lower)\b",q,re.I):return Result("I haven't sent a command. Please ask for one direct action at a time; I don't execute conditional or chained commands.",'capability')
  return None
 m=re.fullmatch(r'set (.+?) to (.+?) degrees(?: (fahrenheit|celsius))?',q,re.I)
 if m:domain='climate';service='set_temperature';target=m[1];mode='temperature';params={'temperature':number(m[2]),'_unit':m[3]};feature=1
 if not domain:
  m=re.fullmatch(r'(?:turn|raise|lower) (?:the )?(.+?) (up|down)(?: by)? (.+?) degrees',q,re.I)
  if m:domain='climate';service='set_temperature';target=m[1];mode='relative-temperature';params={'_delta':number(m[3]),'_sign':1 if m[2].lower()=='up' else -1};feature=1
 if not domain:
  m=re.fullmatch(r'set (.*?(?:thermostat|heat|heating)) to (heat|cool|off|auto)',q,re.I)
  if m:domain='climate';service='set_hvac_mode';target=m[1];params={'hvac_mode':m[2].lower()}
 if not domain:
  m=re.fullmatch(r'turn (on|off) (?:the )?(.+?(?:thermostat|heat|heating|tv|television|speaker))',q,re.I)
  if m:
   target=m[2];domain='climate' if re.search(r'(thermostat|heat|heating)$',target,re.I) else 'media_player';service='turn_'+m[1].lower();feature=(256 if service=='turn_on' else 128) if domain=='climate' else (128 if service=='turn_on' else 256)
 if not domain:
  m=re.fullmatch(r'set (.*?fan) (?:speed )?to (.+?) percent',q,re.I)
  if m:domain='fan';service='set_percentage';target=m[1];params={'percentage':number(m[2])};feature=1
 if not domain:
  m=re.fullmatch(r'set (.*?fan) (?:speed )?to (low|medium|high)',q,re.I)
  if m:domain='fan';service='set_percentage';target=m[1];params={'percentage':{'low':33,'medium':66,'high':100}[m[2].lower()]};feature=1
 if not domain:
  m=re.fullmatch(r'(open|close) (.*?(?:blinds?|shades?|curtains?))',q,re.I)
  if m:domain='cover';service=m[1].lower()+'_cover';target=m[2];feature=1 if m[1].lower()=='open' else 2
 if not domain:
  m=re.fullmatch(r'set (.*?(?:blinds?|shades?|curtains?)) to (.+?) percent',q,re.I)
  if m:domain='cover';service='set_cover_position';target=m[1];params={'position':number(m[2])};feature=4
 if not domain:
  m=re.fullmatch(r'(?:set|make|turn) (.*?(?:lights?|lamps?)) (?:to )?('+'|'.join(COLORS)+r')',q,re.I)
  if m:domain='light';service='turn_on';target=m[1];mode='color';params={'rgb_color':COLORS[m[2].lower()]}
 if not domain:
  m=re.fullmatch(r'(?:make|dim|brighten) (.+?) (brighter|dimmer)(?: by (.+?) percent)?',q,re.I)
  if m:domain='light';service='turn_on';target=m[1];mode='relative-brightness';params={'_delta':number(m[3]) if m[3] else 10,'_sign':1 if m[2].lower()=='brighter' else -1}
 if not domain:
  m=re.fullmatch(r'(?:activate|run|turn on) (?:the )?(.+?) scene',q,re.I)
  if m:domain='scene';service='turn_on';target=m[1]
 if not domain:
  m=re.fullmatch(r'(play|pause|resume|stop|mute|unmute) (?:the )?(.+)',q,re.I)
  if m:
   domain='media_player';target=m[2];action=m[1].lower();service={'play':'media_play','pause':'media_pause','resume':'media_play','stop':'media_stop','mute':'volume_mute','unmute':'volume_mute'}[action];feature={'play':16384,'pause':1,'resume':16384,'stop':4096,'mute':8,'unmute':8}[action]
   if action in {'mute','unmute'}:params={'is_volume_muted':action=='mute'}
 if not domain:
  m=re.fullmatch(r'set (.+?) volume to (.+?) percent',q,re.I)
  if m:domain='media_player';service='volume_set';target=m[1];params={'volume_level':number(m[2])};feature=4;mode='volume'
 if not domain:
  m=re.fullmatch(r'(?:what is|what s) playing(?: on (.+))?',q,re.I)
  if m:
   entity=select(catalog,m[1] or '', 'media_player',area)
   if isinstance(entity,Result):return entity
   title=entity.attributes.get('media_title')
   return Result((str(title)[:150]+(' by '+str(entity.attributes['media_artist'])[:100] if entity.attributes.get('media_artist') else '')+' is playing on '+spoken_name(entity)+'.') if title and entity.state=='playing' else "I don't see anything playing on "+spoken_name(entity)+'.')
 if not domain:
  if re.match(r'^(?:lock|unlock|open|close)\b',q,re.I):return Result("I can move supported window coverings, but I don't operate doors, locks, gates or garages by voice.",'capability')
  return None
 entity=select(catalog,target,domain,area)
 if isinstance(entity,Result):return entity
 a=entity.attributes
 if entity.state=='unavailable' or entity.state=='unknown' and domain!='scene':return Result("I can't reach "+spoken_name(entity)+" right now. I haven't sent a command.",'unavailable')
 if domain=='cover' and a.get('device_class') not in {'blind','shade','curtain','shutter'}:return Result('I can move window coverings, but I will not open doors, gates or garages by voice.','capability')
 if feature and not int(a.get('supported_features') or 0)&feature:return Result("That device doesn't report support for this control.",'capability')
 if service=='set_hvac_mode' and params['hvac_mode'] not in a.get('hvac_modes',[]):return Result("That thermostat doesn't support that mode.",'capability')
 if mode=='relative-temperature':
  delta=params['_delta'];current=a.get('temperature')
  if not finite(delta) or not 0<delta<=5 or not finite(current):return Result('I need a current target temperature and an adjustment of five degrees or less.','capability')
  params={'temperature':current+params['_sign']*delta}
 if domain=='climate' and service=='set_temperature':
  value=params.get('temperature');unit=params.pop('_unit',None);reported=str(a.get('temperature_unit') or '')
  if unit and (not reported or unit[0].lower() not in reported.lower()):return Result('Please use the temperature unit configured on that thermostat.','capability')
  if not finite(value) or not finite(a.get('min_temp')) or not finite(a.get('max_temp')) or not a['min_temp']<=value<=a['max_temp']:return Result('That temperature is outside the range reported by your thermostat.','capability')
 if mode=='color' and not set(a.get('supported_color_modes') or [])&{'rgb','rgbw','rgbww','hs','xy'}:return Result("That light doesn't support color changes.",'capability')
 if mode=='relative-brightness':
  current=a.get('brightness');delta=params['_delta']
  if not finite(current) or not finite(delta) or not 0<delta<=100:return Result("I can't read the current brightness to adjust it safely.",'capability')
  params={'brightness_pct':max(0,min(100,round(current*100/255)+params['_sign']*delta))}
 for key in ('percentage','position','volume_level'):
  if key in params:
   if not finite(params[key]) or not 0<=params[key]<=100:return Result('Please choose a percentage from zero to one hundred.','capability')
   if key=='volume_level':params[key]/=100
 speech='Okay, '+({'climate':'adjusting ','fan':'adjusting ','cover':'moving ','light':'adjusting ','scene':'activating ','media_player':'updating '}[domain])+spoken_name(entity)+'.'
 if domain=='climate' and 'temperature' in params:speech='Okay, setting '+spoken_name(entity)+' to '+str(params['temperature']).removesuffix('.0')+' degrees.'
 return Result(speech,'command',[entity.entity_id],command={'domain':domain,'service':service,'data':{'entity_id':entity.entity_id,**params}})
