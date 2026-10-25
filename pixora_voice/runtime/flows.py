import re
def normalized(text):return ' '.join(re.findall(r'[a-z0-9]+',str(text).lower()))

async def phrases(hass):return hass.phrases

async def matches(hass,text):return any(normalized(p)==normalized(text) for p in await phrases(hass))


async def ask(hass,text):return await hass.rpc('flow',{'text':text})

def variable_question(text):
 q=str(text).strip().rstrip('?.!')
 match=re.fullmatch(r"(?:what is|what's|read|tell me) (?:the )?(?:value of (?:the )?|variable )(.+?)(?: variable)?",q,re.I)
 if match:return match[1].strip()
 match=re.fullmatch(r"(?:what is|what's|read|tell me) (?:the )?(.+?) variable",q,re.I)
 return match[1].strip() if match else None
