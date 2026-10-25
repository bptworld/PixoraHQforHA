"""Bounded, local readiness checks; log content never leaves Home Assistant."""
import asyncio
import time
import os
import hashlib
import json
from pathlib import Path
from aiohttp import ClientTimeout,ClientError

def logs_ready(text):
    # The app logs Ready before it trains. Require a completed training after
    # its latest startup and latest training start, never a previous session.
    finished = text.rfind('Finished training:')
    started = text.rfind('Started training:')
    startup = max(text.rfind('INFO:root: Ready'), text.rfind('speech-to-phrase: starting'))
    return finished >= 0 and finished > started and finished > startup

async def uses_groq(hass):
    def read():
        try:return json.loads(Path(hass.config.path('.storage','pixora_voice_speech.json')).read_text()).get('enabled') is True
        except (OSError,ValueError,AttributeError):return False
    return await asyncio.to_thread(read)

async def read_status(hass):
    if await uses_groq(hass):return {'ready':True,'generation':'groq-no-training','training_required':False}
    from homeassistant.components.hassio.const import DATA_COMPONENT
    supervisor = hass.data[DATA_COMPONENT]
    info = await supervisor.send_command('/addons/core_speech-to-phrase/info', method='get', timeout=4)
    running = info.get('data', {}).get('state') == 'started'
    # Range is supported by Supervisor even on Core versions whose wrapper
    # cannot pass range headers. Keep a strict memory/read limit if ignored.
    url=supervisor.base_url.with_path('/addons/core_speech-to-phrase/logs')
    async with supervisor.websession.get(url,headers={'Authorization':'Bearer '+os.environ.get('SUPERVISOR_TOKEN',''),'Range':'bytes=-65536'},timeout=ClientTimeout(total=4),allow_redirects=False) as response:
        if response.status not in {200,206}:return {'ready':False,'generation':None}
        tail=bytearray();total=0
        async for chunk in response.content.iter_chunked(4096):
            total+=len(chunk)
            if total>1024*1024:return {'ready':False,'generation':None}
            tail.extend(chunk)
            if len(tail)>65536:del tail[:-65536]
    text=tail.decode('utf-8',errors='replace')
    line=next((line for line in reversed(text.splitlines()) if 'Finished training:' in line),None)
    return {'ready':running and logs_ready(text),'generation':hashlib.sha256(line.encode()).hexdigest() if line else None}

async def ready(hass):
    return (await read_status(hass))['ready']

async def wait_ready(hass, read=None, timeout=120, sleep=asyncio.sleep, now=time.monotonic, previous=None):
    read = read or read_status
    deadline = now() + timeout
    while now() < deadline:
        try:
            status=await read(hass)
            if isinstance(status,dict) and status.get('ready') and status.get('generation') != previous:return True
        except (RuntimeError, ValueError, OSError, KeyError, ClientError, asyncio.TimeoutError):
            pass
        await sleep(2)
    return False
