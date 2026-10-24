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
            return None
        speech = reply.get("speech")
        return speech if isinstance(speech, str) else "I couldn't confirm the thermostat override. Please check the controller."
    except asyncio.TimeoutError:
        return "I couldn't reach Thermostat Controller. Please check it before trying again; I haven't sent a direct thermostat command."
    finally:
        remove()
