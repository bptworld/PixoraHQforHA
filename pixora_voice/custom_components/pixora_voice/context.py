"""Bounded hints for a later wake-word request; never continuous listening."""
import re,time
from .engine import canonical_request,words

class Followups:
    def __init__(self):self.items={}

    def key(self,request,conversation_id):
        return (request.context.user_id,getattr(request,'satellite_id',None) or getattr(request,'device_id',None) or conversation_id)

    def get(self,key):
        now=time.monotonic()
        self.items={k:v for k,v in self.items.items() if v['expires']>now}
        return self.items.get(key)

    def put(self,key,**value):
        self.get(key)
        if len(self.items)>=64:self.items.pop(next(iter(self.items)))
        if 'text' in value:value['text']=str(value['text'])[:500]
        if 'ids' in value:value['ids']=value['ids'][:20]
        self.items[key]={**value,'expires':time.monotonic()+90}

    def clear(self,key):self.items.pop(key,None)

def planner_followup(text,previous):
    if not previous or previous.get('source')!='planner':return None
    q=' '.join(words(text))
    if q not in {'and tomorrow','what about tomorrow','and today','what about today'}:return None
    original=previous['text']
    if not re.search(r'\b(schedule|calendar|agenda|appointments?|events?|game)\b',original,re.I):return None
    day='tomorrow' if q.endswith('tomorrow') else 'today'
    return re.sub(r'\b(today|tomorrow)\b',day,original,flags=re.I) if re.search(r'\b(today|tomorrow)\b',original,re.I) else original.rstrip('?. ')+ ' '+day

def duration_question(text):
    return bool(re.fullmatch(r'(?:and )?how long (?:has|have) (?:it|that|they) been(?: (?:open|closed|on|off|locked|unlocked))?[? .]*',text.strip(),re.I))

def reading_followup(text,previous):
    if not previous or previous.get('source')!='home':return None
    if re.fullmatch(r'(?:and )?(?:is|are) (?:it|that|they) (?:still )?(open|closed|on|off|locked|unlocked)[? .]*',canonical_request(text),re.I):return previous.get('ids')
    return None
