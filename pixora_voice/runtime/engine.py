"""Deterministic English home questions and commands. No network or model dependencies."""
from dataclasses import dataclass, field
from datetime import datetime,timezone
import re
import math
import unicodedata

NOT_FOUND_REPLY = "Sorry, I can't find the information you're looking for."


def words(text):
    text=unicodedata.normalize('NFKC',str(text)).lower().replace('’',"'")
    text=re.sub(r"\bwhat's\b",'what is',text)
    text=re.sub(r"\bit's\b",'it is',text)
    text=re.sub(r"\b([a-z]+)'s\b",r'\1',text)
    text=text.replace('_',' ').replace('-',' ')
    text=re.sub(r'\bfishtank\b','fish tank',text)
    return re.findall(r'[a-z0-9]+',text)


@dataclass
class Entity:
    entity_id: str
    name: str
    state: str
    attributes: dict=field(default_factory=dict)
    area: str=''
    aliases: list=field(default_factory=list)
    exposed: bool=True
    last_changed: datetime|None=None

    @property
    def domain(self):return self.entity_id.split('.')[0]


@dataclass
class Result:
    speech: str
    kind: str='answer'
    entities: list=field(default_factory=list)
    choices: list=field(default_factory=list)
    property: str=''
    command: dict|None=None


# Functional words and type suffixes are removed only after capability filtering.
STOP=set('is are was were the a an my our your please tell me what which how many any all of in at to for it its there here right now currently status state reading value does do have has get give show on off open opened opening close closed closing shut locked unlocked lock locking unlocking contact contacts sensor sensors device devices temperature degrees degree humidity percent level battery motion occupancy detected detecting occupied unoccupied presence present lights light lamps lamp switches switch fans fan brightness dim bright set turn make change'.split())
NORMAL={'doors':'door','windows':'window','lamps':'lamp','lights':'light','batteries':'battery','temp':'temperature','bulbs':'light','bulb':'light','fans':'fan','switches':'switch','shut':'closed','shut':'closed','dr':'door','rm':'room','bath':'bathroom'}


def normalized(text):return [NORMAL.get(w,w) for w in words(text)]


def target_words(text):return set(normalized(re.sub(r'\b\d{1,3}\s+(?:percent|brightness)\b','',str(text),flags=re.I)))-STOP-{'can','could','would','you','check','whether','this','room','air','conditioning','cooling','running','door','window','heat','heating','heater','hvac','thermostat','cool','setpoint','activity','much','remaining'}


def canonical_request(text):
    # Only remove a polite prefix. Negation and conditionals remain visible.
    text=re.sub(r"^(?:can|could|would) you (?:please )?",'',text.strip(),flags=re.I)
    text=re.sub(r"^do you know (?:whether|if) ",'is ',text,flags=re.I)
    text=re.sub(r"^do you know (?:what )?(?:the )?temperature",'what is the temperature',text,flags=re.I)
    text=re.sub(r"^tell me (?:the )?(temperature|humidity)\b",r'what is the \1',text,flags=re.I)
    text=re.sub(r"\btemp\b",'temperature',text,flags=re.I)
    text=re.sub(r"\b(?:switched|powered) (on|off)\b",r'\1',text,flags=re.I)
    text=re.sub(r"\b(?:ajar)\b",'open',text,flags=re.I)
    text=re.sub(r'^please\s+','',text,flags=re.I)
    text=re.sub(r'\b(?:in this room|in my room|in the room)\b','in here',text,flags=re.I)
    text=re.sub(r'^(?:check|tell me) (?:whether|if)\s+','is ',text,flags=re.I)
    text=re.sub(r'^how (?:warm|cold) is it\b',"what is the temperature",text,flags=re.I)
    text=re.sub(r'^how humid is it\b',"what is the humidity",text,flags=re.I)
    text=re.sub(r'\b(?:air conditioning|air conditioner|a c)\b','cooling',text,flags=re.I)
    text=re.sub(r'\b(?:heat|heating) running\b','heat on',text,flags=re.I)
    # Spoken numbers are bounded to the brightness range, without another model.
    units={'zero':0,'one':1,'two':2,'three':3,'four':4,'five':5,'six':6,'seven':7,'eight':8,'nine':9,'ten':10,'eleven':11,'twelve':12,'thirteen':13,'fourteen':14,'fifteen':15,'sixteen':16,'seventeen':17,'eighteen':18,'nineteen':19}
    tens={'twenty':20,'thirty':30,'forty':40,'fifty':50,'sixty':60,'seventy':70,'eighty':80,'ninety':90}
    def number(m):
        parts=m.group(1).lower().replace('-',' ').split()
        if parts==['one','hundred']:return '100 percent'
        if len(parts)==1 and parts[0] in units:return str(units[parts[0]])+' percent'
        if parts[0] in tens and (len(parts)==1 or (len(parts)==2 and 0<units.get(parts[1],99)<10)):
            return str(tens[parts[0]]+(units[parts[1]] if len(parts)>1 else 0))+' percent'
        return m.group(0)
    return re.sub(r'\b((?:one hundred)|(?:(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?:[ -](?:one|two|three|four|five|six|seven|eight|nine))?)|(?:'+ '|'.join(units)+r')) percent\b',number,text,flags=re.I)


def duration_answer(entity,now=None):
    """Describe only the current reported state's age, without history downloads."""
    if entity.state in {'unknown','unavailable','None',''}:return Result(f"I can't check {spoken_name(entity)} right now. It’s unavailable at the moment.",'unavailable')
    changed=entity.last_changed;now=now or datetime.now(timezone.utc)
    if not isinstance(changed,datetime) or changed.tzinfo is None or changed>now:return Result("I don't have a reliable time for that reading.",'unavailable')
    seconds=int((now-changed).total_seconds())
    if seconds<60:age='less than a minute'
    else:
        count,unit=(seconds//60,'minute') if seconds<3600 else (seconds//3600,'hour') if seconds<86400 else (seconds//86400,'day')
        age=f'{count} {unit}'+('s' if count!=1 else '')
    state={'on':'open','off':'closed'}.get(entity.state,entity.state) if entity.domain=='binary_sensor' and capable(entity,'opening','') else entity.state
    return Result(f'{subject(entity)} has been reporting {state} for {age}.',entities=[entity.entity_id])


def clock_answer(text,time_zone,now=None):
    """Answer clock questions on the hub; never treat an event time as current time."""
    query=' '.join(words(canonical_request(str(text))))
    time_questions={'what time is it','what is the time','tell me the time','tell me what time it is','what is the current time','what time is it now'}
    date_questions={'what is the date','what is the date today','what is today date','what date is it','what day is it','what day is today','what day of the week is it','what is today','tell me the date'}
    if query not in time_questions|date_questions:return None
    from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
    try:zone=ZoneInfo(str(time_zone))
    except (ZoneInfoNotFoundError,ValueError):return "I need the correct time zone in Home Assistant before I can tell you the local time."
    local=(now or datetime.now(timezone.utc)).astimezone(zone)
    if query in time_questions:return "It's "+local.strftime('%I:%M %p').lstrip('0').replace(':00 ',' ')+'.'
    return "It's "+local.strftime('%A, %B')+' '+str(local.day)+'.'


def capable(entity,prop,text):
    domain=entity.domain;cls=entity.attributes.get('device_class','')
    if prop=='opening':
        if domain=='binary_sensor':
            if cls not in {'door','window','garage_door','opening'}:return False
            if 'window' in normalized(text) and cls not in {'window','opening'}:return False
            if 'door' in normalized(text) and cls=='window':return False
            return True
        if domain!='cover':return False
        if 'door' in normalized(text):return cls in {'door','garage'}
        if 'window' in normalized(text):return cls=='window'
        return True
    if prop=='lock':return domain=='lock'
    if prop in {'heating','cooling','heat_setpoint','cool_setpoint','thermostat_setpoint'}:return domain=='climate'
    if prop=='temperature':return (domain=='sensor' and cls=='temperature') or (domain=='climate' and 'current_temperature' in entity.attributes)
    if prop=='humidity':return domain=='sensor' and cls=='humidity'
    if prop=='battery':return domain=='sensor' and cls=='battery'
    if prop=='motion':return domain=='binary_sensor' and cls in {'motion','occupancy','presence'}
    if prop=='brightness':return domain=='light' and 'brightness' in entity.attributes
    if prop=='power':
        requested=set(normalized(text))
        if requested & {'light','lamp'}:
            named_light=any(set(normalized(name)) & {'light','lamp'} for name in [entity.name,*entity.aliases])
            return domain=='light' or domain=='switch' and named_light
        if 'fan' in requested:return domain=='fan'
        if 'switch' in requested:return domain in {'switch','input_boolean'}
        return domain in {'light','switch','fan','input_boolean'}
    return False


def spoken_name(entity):
    """Clean technical suffixes for speech only; keep matching identities intact."""
    name=re.sub(r'\s+(?:contact\s+sensor|contact|sensor)$','',entity.name,flags=re.I).strip()
    if entity.area and name.lower().startswith(entity.area.lower()+' '):
        remainder=name[len(entity.area):].strip()
        if re.match(r'^(front|back|side) door$',remainder,re.I):name=remainder.lower()
    if entity.attributes.get('device_class')=='window' and 'window' not in words(name):name+=' window'
    return name or entity.name


def subject(entity):
    name=spoken_name(entity)
    return 'The '+name[0].lower()+name[1:]


def spoken_list(names):
    if len(names)<2:return ''.join(names)
    return ', '.join(names[:-1])+' and '+names[-1]


def describe(entity,prop):
    name=subject(entity);state=str(entity.state);attrs=entity.attributes
    if state in {'unknown','unavailable','None',''}:return f"I can't check {spoken_name(entity)} right now. It’s unavailable at the moment."
    if prop=='opening':
        value={'on':'open','off':'closed'}.get(state,state) if entity.domain=='binary_sensor' else state
        if value not in {'open','closed','opening','closing'}:return f"I can't tell whether {spoken_name(entity)} is open or closed right now."
        return f'{name} is {value}.'
    if prop=='lock':return f'{name} is {state}.'
    if prop in {'heat_setpoint','cool_setpoint','thermostat_setpoint'}:
        keys = [('heat','target_temp_low'),('cool','target_temp_high')] if state=='heat_cool' else [(state,'temperature')] if state in {'heat','cool'} else []
        if prop=='heat_setpoint':keys=[pair for pair in keys if pair[0]=='heat']
        if prop=='cool_setpoint':keys=[pair for pair in keys if pair[0]=='cool']
        readings=[str(attrs[key])+' degrees'+(' '+{'°F':'Fahrenheit','°C':'Celsius','F':'Fahrenheit','C':'Celsius'}.get(attrs.get('temperature_unit'),str(attrs.get('temperature_unit'))) if attrs.get('temperature_unit') else '')+' for '+('heating' if label=='heat' else 'cooling') for label,key in keys if isinstance(attrs.get(key),(int,float)) and not isinstance(attrs.get(key),bool) and math.isfinite(attrs[key])]
        if not readings:return f"I can't confirm the requested setpoint for {spoken_name(entity)} right now. Its mode is {state}."
        return f'{name} is set to '+ ' and '.join(readings)+'.'
    if prop in {'heating','cooling'}:
        action=attrs.get('hvac_action')
        if prop=='cooling':
            if action=='cooling':return f'{name} is cooling right now.'
            if action in {'idle','off','heating','drying','fan'}:return f'{name} is not cooling right now.'
            return f'{name} does not report whether the air conditioning is actually running.'
        if action=='heating':return f'{name} is actively heating right now.'
        if action in {'idle','off','cooling','drying','fan'}:return f'{name} is not heating right now.'
        return f'{name} is set to {state}, but it does not report whether the heat is actually running.'
    if prop=='motion':return f'{name} {"detects activity" if state=="on" else "is clear" if state=="off" else "has an unknown activity state"}.'
    if prop=='power':return f'{name} is {state}.'
    if prop=='brightness':
        if state=='off':return f'{name} is off.'
        value=attrs.get('brightness')
        return f'{name} is at {round(float(value)*100/255)} percent brightness.' if isinstance(value,(int,float)) else f"I can't read the brightness of {spoken_name(entity)} right now."
    value=attrs.get('current_temperature') if entity.domain=='climate' else state
    if value is None:return f"I can't get a current {prop} reading from {spoken_name(entity)}."
    unit=attrs.get('unit_of_measurement','')
    if prop=='temperature':
        unit={'°F':'degrees Fahrenheit','°C':'degrees Celsius'}.get(unit,unit)
        location=entity.area or spoken_name(entity)
        return f"It's {value}{' '+unit if unit else ''} in {location}."
    if prop=='humidity':return f"The humidity in {entity.area or spoken_name(entity)} is {value} percent."
    if prop=='battery':return f'{name} has {value} percent battery left.'
    return f'{name} is {value}{" "+unit if unit else ""}.'


def reply_to_question(entity,prop,text):
    """Answer yes/no questions directly only when the reported state proves it."""
    speech=describe(entity,prop)
    if not re.match(r'^(is|are|does|do)\b',text,re.I):return speech
    state=str(entity.state);query=set(words(text));actual=None;wanted=None
    if prop=='opening':
        actual={'on':'open','off':'closed'}.get(state,state) if entity.domain=='binary_sensor' else state
        wanted=next((w for w in ('open','closed') if w in query),None)
        if actual not in {'open','closed'}:return speech
    elif prop in {'power','lock'}:
        actual=state;wanted=next((w for w in (('on','off') if prop=='power' else ('locked','unlocked')) if w in query),None)
        if actual not in ({'on','off'} if prop=='power' else {'locked','unlocked'}):return speech
    elif prop in {'heating','cooling'}:
        action=entity.attributes.get('hvac_action')
        if state in {'unknown','unavailable','None',''} or action not in {'idle','off','heating','cooling','drying','fan'}:return speech
        actual=action==prop;wanted='off' not in query
    elif prop=='motion':
        if state not in {'on','off'}:return speech
        actual=state;wanted='off' if query & {'clear','unoccupied'} else 'on' if query & {'occupied','activity','motion','detected'} else None
    if wanted is None:return speech
    return ('Yes, ' if actual==wanted else 'No, ')+speech[0].lower()+speech[1:]


def interpret(text):
    """Return a property and optional explicit command; never guess an intent."""
    sentence=' '.join(normalized(canonical_request(text)))
    # Missing copulas in recognized status questions are read-only. Never infer
    # a device command from a noun phrase such as "the fish tank lights on".
    fragment=bool(re.fullmatch(r'(?:the )?[a-z0-9 ]+ (?:on|off)',sentence) and set(sentence.split()) & {'light','lamp','switch','fan'} and not re.match(r'^(is|are|what|which|how|does|do|tell|show|give|can|turn|switch|set|dim|brighten|make|start|stop)\b',sentence) and not re.search(r'\b(not|never|unless|except|if|when|and|then)\b',sentence))
    if fragment:return 'power',None
    if re.search(r'\b(not|never|unless|except|if|when|and|then)\b',sentence) and re.match(r'^(turn|switch|set|dim|brighten)\b',sentence):return '',None
    if re.search(r'\b(unlock|lock|open|close) (the |my )?',sentence) and not re.match(r'^(is|are|what|which|how|does|do|tell|show)\b',sentence):
        return '',None
    if re.match(r'^(please )?(turn|switch)\b',sentence) and re.search(r'\b(on|off)\b',sentence):
        if re.search(r'\b(not|never|unless|except|if|when|and|then)\b',sentence):return '',None
        match=re.search(r'\b(on|off)\b',sentence)
        return 'power',{'service':'turn_'+match.group(1),'data':{}}
    if re.match(r'^(please )?(set|dim|brighten)\b',sentence):
        match=re.search(r'\b(\d{1,3}) (percent|brightness)\b',sentence)
        if match and 0<=int(match.group(1))<=100:
            return 'brightness',{'service':'turn_on','data':{'brightness_pct':int(match.group(1))}}
        return '',None
    if not re.match(r'^(is|are|what|which|how|does|do|tell|show|give|can you tell)\b',sentence):return '',None
    if ('set to' in sentence or 'setpoint' in sentence) and re.match(r"^what\b",sentence):
        return ('cool_setpoint' if re.search(r'\b(cool|cooling|air conditioning)\b',sentence) else 'heat_setpoint' if re.search(r'\b(heat|heating)\b',sentence) else 'thermostat_setpoint'),None
    if re.search(r'\b(locked|unlocked|lock)\b',sentence):return 'lock',None
    if 'cooling' in sentence.split() and 'temperature' not in sentence.split():return 'cooling',None
    if re.search(r'\b(heat|heating|heater|hvac|thermostat)\b',sentence) and 'temperature' not in sentence.split():return 'heating',None
    if re.search(r'\b(open|closed|opened|opening|closing|closed|contact)\b',sentence):return 'opening',None
    for prop in ('temperature','humidity','battery','brightness'):
        if prop in sentence.split():return prop,None
    if re.search(r'\b(motion|occupancy|occupied|unoccupied|activity|presence|present)\b',sentence):return 'motion',None
    if re.search(r'\b(on|off)\b',sentence):return 'power',None
    return '',None


def choose(text,entities,prop,area=''):
    target=target_words(text)
    if 'here' in words(text) and area:target|=target_words(area)
    candidates=[]
    for entity in entities:
        if not entity.exposed or not capable(entity,prop,text):continue
        names=[entity.name,*entity.aliases]
        best=-1
        for name in names:
            name_tokens=set(normalized(name));combined=name_tokens|set(normalized(entity.area))
            if target and not target<=combined:continue
            # Prefer the dedicated temperature sensor over a thermostat at the
            # same location; don't prioritize entities merely because they're online.
            score=10*len(target&name_tokens)+2*len(target&set(normalized(entity.area)))
            if target==target_words(name):score+=4
            if prop=='temperature' and entity.domain=='sensor':score+=1
            best=max(best,score)
        if best>=0:candidates.append((best,entity))
    candidates.sort(key=lambda pair:(-pair[0],pair[1].name.lower(),pair[1].entity_id))
    return candidates


def answer(text,entities,area=''):
    if not isinstance(text,str) or not text.strip() or len(text)>500:
        return Result('What would you like to know about your home? Try asking one thing at a time.','unsupported')
    text=canonical_request(text)
    prop,command=interpret(text)
    if not prop:return Result(NOT_FOUND_REPLY,'unsupported')
    if 'here' in words(text) and not area:return Result("Which room do you mean? I don't know which room this speaker is in yet.",'clarify',property=prop)
    room_reading=prop in {'temperature','humidity'} and not target_words(text)
    if room_reading and not area:return Result('Which room do you mean? Say the room name so I can check the right place.','clarify',property=prop)
    if set(words(text))&{'it','them','those'} and not target_words(text):return Result('Which device do you mean? Say its name so I can check the right one.','clarify',property=prop)
    candidates=choose(text,entities,prop,area)
    if 'here' in words(text):candidates=[pair for pair in candidates if normalized(pair[1].area)==normalized(area)]
    if room_reading and area:candidates=[pair for pair in candidates if normalized(pair[1].area)==normalized(area)]
    explicit_area=any(set(normalized(e.area))<=set(normalized(text)) for e in entities if e.area)
    if command and area and not explicit_area:
        candidates=[pair for pair in candidates if normalized(pair[1].area)==normalized(area)]
    if not candidates:return Result("I can't find the right device to check that. Make sure it's shared with Assist, and include its room or name.",'not_found',property=prop)
    # Unqualified room requests use the listening satellite's registered area.
    # An explicit room/entity wins on its own; context only breaks equal matches.
    best=candidates[0][0]
    tied=[pair for pair in candidates if pair[0]==best]
    local=[pair for pair in tied if area and normalized(pair[1].area)==normalized(area)]
    if local and len(tied)>1 and not set(words(text))&{'all','any','which','many'}:candidates=local
    group=bool(re.search(r'\b(which|any|all|how many)\b',' '.join(words(text)))) and not command
    if group:
        found=[e for _,e in candidates]
        if prop in {'power','lock','motion'}:
            desired=next((w for w in words(text) if w in ({'on','off'} if prop=='power' else {'locked','unlocked'} if prop=='lock' else {'occupied','unoccupied','detected','clear'})),None)
            if desired:
                expected={'occupied':'on','detected':'on','unoccupied':'off','clear':'off'}.get(desired,desired)
                known={'on','off'} if prop in {'power','motion'} else {'locked','unlocked'}
                active=[e for e in found if e.state==expected]
                unknown=[e for e in found if e.state not in known]
                if 'all' in words(text):
                    speech=(f'All {len(found)} are {desired}.' if len(active)==len(found) else f'{len(active)} of {len(found)} are {desired}.')
                else:speech=(spoken_list([subject(e) for e in active])+(' is ' if len(active)==1 else ' are ')+desired+'.') if active else f'None of the devices I can check are {desired}.'
                if unknown:speech+=" I can't confirm "+spoken_list([spoken_name(e) for e in unknown])+'.'
                if 'how many' in text.lower():speech=f'{len(active)} '+('device is ' if len(active)==1 else 'devices are ')+desired+'. '+speech
                return Result(speech,entities=[e.entity_id for e in found],property=prop)
        if prop=='opening' and 'open' in words(text) and 'all' not in words(text):
            active=[e for e in found if e.state==('on' if e.domain=='binary_sensor' else 'open')]
            unknown=[e for e in found if e.state not in ({'on','off'} if e.domain=='binary_sensor' else {'open','closed'})]
            noun='windows' if 'window' in normalized(text) else 'doors' if 'door' in normalized(text) else 'doors or windows'
            speech=(spoken_list([subject(e) for e in active])+(' is open.' if len(active)==1 else ' are open.')) if active else ('None of the '+noun+' I can check are open.' if unknown else 'All the '+noun+' I can check are closed.')
            if unknown:speech+=" I can't check "+spoken_list([spoken_name(e) for e in unknown])+" right now."
            if 'how many' in text.lower():speech=f'{len(active)} '+('is open. ' if len(active)==1 else 'are open. ')+speech
        else:speech=' '.join(describe(e,prop) for e in found[:20])+(f' There are {len(found)-20} more matches.' if len(found)>20 else '')
        return Result(speech,entities=[e.entity_id for e in found],property=prop)
    best=candidates[0][0];found=[e for score,e in candidates if score==best]
    plural_command=bool(command and set(words(text))&{'lights','lamps','fans','switches'})
    if plural_command and not area and not explicit_area:return Result('Which room do you mean? Say the room name so I can check the right place.','clarify',property=prop)
    if command and ('all' in words(text) or plural_command):
        found=[e for _,e in candidates]
        if len({e.domain for e in found})!=1:return Result('Which kind of device do you mean? For example, say all kitchen lights.','clarify',property=prop)
        unavailable=[e for e in found if e.state in {'unknown','unavailable'}]
        if unavailable:return Result("I can't reach all of those devices right now: "+', '.join(e.name for e in unavailable)+". I haven't sent a command.",'unavailable',property=prop)
        ids=[e.entity_id for e in found]
        return Result(f"Okay, turning {'off' if command['service']=='turn_off' else 'on'} {len(ids)} {found[0].domain.replace('_',' ')}s.",'command',ids,property=prop,command={'domain':found[0].domain,**command,'data':{**command['data'],'entity_id':ids}})
    if len(found)>1:
        labels=[e.name for e in found[:5]]
        return Result('Which one did you mean: '+', '.join(labels)+'?','clarify',choices=[{'entity_id':e.entity_id,'name':e.name} for e in found],property=prop)
    entity=found[0]
    if command:
        if entity.state in {'unknown','unavailable'}:return Result(f"I can't reach {spoken_name(entity)} right now, so I haven't sent a command.",'unavailable',property=prop)
        if command['service']=='turn_on' and prop=='brightness' and entity.domain!='light':return Result("I can't adjust the brightness on that device.",'unsupported')
        command={'domain':entity.domain,**command,'data':{**command['data'],'entity_id':entity.entity_id}}
        return Result((f"Okay, setting {spoken_name(entity)} to {command['data']['brightness_pct']} percent." if prop=='brightness' else f"Okay, turning {'off' if command['service']=='turn_off' else 'on'} {spoken_name(entity)}."),'command',[entity.entity_id],property=prop,command=command)
    return Result(reply_to_question(entity,prop,text),entities=[entity.entity_id],property=prop)
