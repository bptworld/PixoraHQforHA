"""Opt-in, read-only Planner requests over the already paired HA connector."""
import asyncio,json,re,secrets,time

from pathlib import Path
DOMAIN='pixora_voice'
SETTINGS='pixora_voice_planner.json'
def is_write_request(text):
 from .engine import canonical_request
 q=canonical_request(str(text)).lower()
 return bool(re.match(r"^(?:(?:do not|don't|dont|never) )?(?:turn|switch|set|dim|brighten|delete|remove|add|create|send|buy|order|cancel|reschedule|complete|mark|move)\b",q))

def is_planner_question(text):
 from .engine import canonical_request,words
 q=canonical_request(str(text)).lower()
 if re.match(r'^(?:(?:can|could|would) you |please )?(turn|switch|set|dim|brighten)\b',q) and 'planner' not in q:return False
 if re.fullmatch(r"(?:what (?:is|s) on (?:the )?(?:tv|television)|what (?:tv |television )?shows are on|(?:show|read|tell) (?:me )?(?:the )?(?:tv|television) (?:schedule|listings))(?: (?:today|tonight|tomorrow|this evening))?[?.!]*"," ".join(words(q))):return True
 calendar_search=re.match(r'^(?:when\b|what time\b|(?:is|are|do|does|will)\b.+\bplay(?:ing)?\b)',q)
 return bool(calendar_search or re.match(r'^(?:is|are) .+ on (?:today|tonight|tomorrow)[?.!]*$',q) or re.search(r"\b(planner|schedule|calendar|agenda|appointments?|events?|games?|dinner|lunch|breakfast|meals?|menu|chores?|tasks?|grocer(?:y|ies)|shopping|pantry|notes?|messages?|countdowns?|alarms?|routines?|lists?)\b",q) or re.match(r'^(is|are|where)\b.*\b(home|away|arrived)\b',q) or re.match(r'^where is \w',q))
async def enabled(hass):return hass.planner_enabled
async def ask(hass,text):return await hass.rpc('planner',{'text':text})
