"""On-demand local controller bridge; no polling or direct fallback on failure."""
import asyncio
import secrets
import time

async def route(hass, command):
    ident = secrets.token_hex(16)
    future = asyncio.get_running_loop().create_future()
    def receive(event):
        data = event.data
        if data.get("request_id") == ident and not future.done():
            future.set_result(data)
    remove = hass.bus.async_listen("pixora_thermostat_voice_reply", receive)
    try:
        hass.bus.async_fire("pixora_thermostat_voice_request", {
            "request_id": ident, "expires_at": time.time() + 10,
            "entity_id": command["data"]["entity_id"],
            "service": command["service"], "temperature": command["data"].get("temperature")})
        reply = await asyncio.wait_for(future, 8)
        if reply.get("unmanaged") is True:
            return "That thermostat is not managed by Thermostat Controller." if command["service"].startswith("controller_") else None
        speech = reply.get("speech")
        return speech if isinstance(speech, str) else "I couldn't confirm the thermostat override. Please check the controller."
    except asyncio.TimeoutError:
        return "I couldn't reach Thermostat Controller. Please check it before trying again; I haven't sent a direct thermostat command."
    finally:
        remove()

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
