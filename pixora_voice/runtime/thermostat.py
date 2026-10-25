"""Thermostat decisions live in the app; HA retains protected controller routing."""
async def route(hass,command):return await hass.rpc('thermostat',command)

def request_kind(text, names=()):
    import re
    from .engine import normalized
    text = str(text).strip().rstrip('?.!')
    match = re.fullmatch(r"resume (?:the )?(.+?) schedule", text, re.I)
    kind = 'controller_resume'
    if not match:
        match = re.fullmatch(r"(?:why is|how long is|what is) (?:the )?(.+?) (off|override|status)", text, re.I)
        kind = 'controller_status'
    if not match:
        return None
    target = set(normalized(match[1])) - {'the', 'thermostat', 'heat', 'heating'}
    if not target or any(target <= set(normalized(name)) for name in names):
        return kind
    return None


def plan(text, catalog, area):
    import re
    from .controls import select
    from .engine import Result
    kind = request_kind(text, [e.name+" "+e.area+" "+" ".join(e.aliases) for e in catalog if e.domain == "climate"])
    if not kind:
        return None
    name = re.sub(r'^(resume|why is|how long is|what is) (?:the )?', '', text.strip().rstrip('?.!'), flags=re.I)
    name = re.sub(r' (schedule|off|override|status)$', '', name, flags=re.I)
    entity = select(catalog, name, 'climate', area)
    if isinstance(entity, Result):
        return entity
    return Result('', 'command', [entity.entity_id], command={'domain':'climate','service':kind,'data':{'entity_id':entity.entity_id}})
