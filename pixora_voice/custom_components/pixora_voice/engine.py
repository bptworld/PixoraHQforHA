"""Deterministic English home questions and commands. No network or model dependencies."""
from dataclasses import dataclass, field
import re
import unicodedata


def words(text):
    text=unicodedata.normalize('NFKC',str(text)).lower().replace('’',"'")
    text=re.sub(r"\bwhat's\b",'what is',text)
    text=re.sub(r"\bit's\b",'it is',text)
    text=re.sub(r"\b([a-z]+)'s\b",r'\1',text)
    text=text.replace('_',' ').replace('-',' ')
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
NORMAL={'doors':'door','windows':'window','lamps':'lamp','lights':'light','batteries':'battery','temp':'temperature','shut':'closed','dr':'door','rm':'room','bath':'bathroom'}


def normalized(text):return [NORMAL.get(w,w) for w in words(text)]


def target_words(text):return {w for w in normalized(text) if not w.isdigit()}-STOP-{'door','window','heat','heating','heater','hvac','thermostat','activity','much','remaining'}


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
    if prop=='heating':return domain=='climate'
    if prop=='temperature':return (domain=='sensor' and cls=='temperature') or (domain=='climate' and 'current_temperature' in entity.attributes)
    if prop=='humidity':return domain=='sensor' and cls=='humidity'
    if prop=='battery':return domain=='sensor' and cls=='battery'
    if prop=='motion':return domain=='binary_sensor' and cls in {'motion','occupancy','presence'}
    if prop=='brightness':return domain=='light' and 'brightness' in entity.attributes
    if prop=='power':
        requested=set(normalized(text))
        if requested & {'light','lamp'}:return domain=='light'
        if 'fan' in requested:return domain=='fan'
        if 'switch' in requested:return domain in {'switch','input_boolean'}
        return domain in {'light','switch','fan','input_boolean'}
    return False


def describe(entity,prop):
    name=entity.name;state=str(entity.state);attrs=entity.attributes
    if state in {'unknown','unavailable','None',''}:return f'{name} is unavailable; I cannot confirm its {prop}.'
    if prop=='opening':
        value={'on':'open','off':'closed'}.get(state,state) if entity.domain=='binary_sensor' else state
        if value not in {'open','closed','opening','closing'}:return f'I cannot determine whether {name} is open or closed.'
        return f'{name} is {value}.'
    if prop=='lock':return f'{name} is {state}.'
    if prop=='heating':
        action=attrs.get('hvac_action')
        if action=='heating':return f'{name} is actively heating.'
        if action in {'idle','off','cooling','drying','fan'}:return f'{name} is not heating right now. Its mode is {state}.'
        return f'{name} is set to {state} mode, but it does not report whether the heat is running.'
    if prop=='motion':return f'{name} {"detects activity" if state=="on" else "is clear" if state=="off" else "has an unknown activity state"}.'
    if prop=='power':return f'{name} is {state}.'
    if prop=='brightness':
        if state=='off':return f'{name} is off.'
        value=attrs.get('brightness')
        return f'{name} brightness is {round(float(value)*100/255)} percent.' if isinstance(value,(int,float)) else f'{name} brightness is unknown.'
    value=attrs.get('current_temperature') if entity.domain=='climate' else state
    if value is None:return f'{name} has no current {prop} reading.'
    unit=attrs.get('unit_of_measurement','')
    if prop in {'humidity','battery'}:unit='percent'
    return f'{name} {prop} is {value}{" "+unit if unit else ""}.'


def interpret(text):
    """Return a property and optional explicit command; never guess an intent."""
    sentence=' '.join(normalized(text))
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
    if re.search(r'\b(locked|unlocked|lock)\b',sentence):return 'lock',None
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
        return Result('Please ask one short question about your home.','unsupported')
    prop,command=interpret(text)
    if not prop:return Result('I do not understand that request yet. Try asking whether a door is open, whether a lock is locked, or a temperature reading.','unsupported')
    if 'here' in words(text) and not area:return Result('Which room do you mean? The listening speaker has no assigned area.','clarify',property=prop)
    candidates=choose(text,entities,prop,area)
    explicit_area=any(set(normalized(e.area))<=set(normalized(text)) for e in entities if e.area)
    if command and area and not explicit_area:
        candidates=[pair for pair in candidates if normalized(pair[1].area)==normalized(area)]
    if not candidates:return Result(f'I could not find an exposed device that can report {prop} for that location.','not_found',property=prop)
    # Unqualified room requests use the listening satellite's registered area.
    # An explicit room/entity wins on its own; context only breaks equal matches.
    best=candidates[0][0]
    tied=[pair for pair in candidates if pair[0]==best]
    local=[pair for pair in tied if area and normalized(pair[1].area)==normalized(area)]
    if local and len(tied)>1 and not set(words(text))&{'all','any','which','many'}:candidates=local
    group=bool(re.search(r'\b(which|any|all|how many)\b',' '.join(words(text)))) and not command
    if group:
        found=[e for _,e in candidates]
        if prop=='opening' and 'open' in words(text) and 'all' not in words(text):
            active=[e for e in found if e.state==('on' if e.domain=='binary_sensor' else 'open')]
            unknown=[e for e in found if e.state not in ({'on','off'} if e.domain=='binary_sensor' else {'open','closed'})]
            speech=('Open: '+', '.join(e.name for e in active)+'.') if active else 'No matching doors or windows are open.'
            if unknown:speech+=' I cannot confirm '+', '.join(e.name for e in unknown)+'.'
            if 'how many' in text.lower():speech=f'{len(active)} are open. '+speech
        else:speech=' '.join(describe(e,prop) for e in found[:20])+(f' There are {len(found)-20} more matches.' if len(found)>20 else '')
        return Result(speech,entities=[e.entity_id for e in found],property=prop)
    best=candidates[0][0];found=[e for score,e in candidates if score==best]
    if command and 'all' in words(text):
        found=[e for _,e in candidates]
        if len({e.domain for e in found})!=1:return Result('Please specify one kind of device, such as all kitchen lights.','clarify',property=prop)
        unavailable=[e for e in found if e.state in {'unknown','unavailable'}]
        if unavailable:return Result('I cannot confirm all those devices are available: '+', '.join(e.name for e in unavailable)+'. No command was sent.','unavailable',property=prop)
        ids=[e.entity_id for e in found]
        return Result(f'Sent the command to {len(ids)} devices.','command',ids,property=prop,command={'domain':found[0].domain,**command,'data':{**command['data'],'entity_id':ids}})
    if len(found)>1:
        labels=[e.name for e in found[:5]]
        return Result('Which device did you mean: '+', '.join(labels)+'?','clarify',choices=[{'entity_id':e.entity_id,'name':e.name} for e in found],property=prop)
    entity=found[0]
    if command:
        if entity.state in {'unknown','unavailable'}:return Result(f'{entity.name} is unavailable. I did not send a command.','unavailable',property=prop)
        if command['service']=='turn_on' and prop=='brightness' and entity.domain!='light':return Result('That device does not support light brightness.','unsupported')
        command={'domain':entity.domain,**command,'data':{**command['data'],'entity_id':entity.entity_id}}
        return Result(f'Sent the command to {entity.name}.','command',[entity.entity_id],property=prop,command=command)
    return Result(describe(entity,prop),entities=[entity.entity_id],property=prop)
