"""Small HA boundary: permitted snapshots, request-scoped operations and local transport."""
import asyncio,json,secrets,time
from datetime import datetime,timedelta,timezone
from functools import partial
from pathlib import Path
from aiohttp import ClientTimeout,ClientError
from homeassistant.components.homeassistant import async_should_expose
from homeassistant.auth.permissions.const import POLICY_READ,POLICY_CONTROL
from homeassistant.helpers import area_registry as ar,device_registry as dr,entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.exceptions import HomeAssistantError

DOMAIN='pixora_voice'
MAX_REQUESTS=4

async def transport(hass,path,body=None,audio=None):
    def read():return json.loads(Path(hass.config.path('.storage','pixora_voice_bridge.json')).read_text(encoding='utf-8'))
    config=await asyncio.to_thread(read)
    from urllib.parse import urlsplit
    url=urlsplit(config['url'])
    if url.scheme!='http' or not url.hostname or not url.hostname.endswith('-pixora-voice') or url.port!=4190 or url.path or url.username or url.password:
        raise ValueError('Invalid local Voice app address.')
    session=async_get_clientsession(hass)
    async with session.post(config['url']+'/bridge/'+path,json=body if audio is None else None,data=audio,
            headers={'X-Pixora-Bridge':config['token'],'X-Pixora-Timezone':str(hass.config.time_zone)},timeout=ClientTimeout(total=30),allow_redirects=False) as response:
        if response.status!=200:raise ValueError('Voice app is unavailable.')
        raw=bytearray()
        async for chunk in response.content.iter_chunked(4096):
            if len(raw)+len(chunk)>64000:raise ValueError('Oversized Voice response.')
            raw.extend(chunk)
        result=json.loads(raw)
        if not isinstance(result,dict):raise ValueError('Invalid Voice response.')
        return result

async def user_for(hass,context):
    uid=context.user_id
    user=await hass.auth.async_get_user(uid) if uid else None
    if uid and not user:raise HomeAssistantError('Account unavailable.')
    return user

async def permitted(hass,context,eid,control=False):
    user=await user_for(hass,context)
    if not async_should_expose(hass,'conversation',eid):return False
    entry=er.async_get(hass).async_get(eid)
    if entry and (entry.disabled_by or entry.hidden_by):return False
    return not context.user_id or user.permissions.check_entity(eid,POLICY_READ) and (not control or user.permissions.check_entity(eid,POLICY_CONTROL))

def origin_area(hass,request):
    entities=er.async_get(hass);devices=dr.async_get(hass);areas=ar.async_get(hass)
    device=devices.async_get(request.device_id) if request.device_id else None
    if not device and getattr(request,'satellite_id',None):
        entry=entities.async_get(request.satellite_id)
        if entry:
            area=areas.async_get_area(entry.area_id) if entry.area_id else None
            if area:return area.name
            device=devices.async_get(entry.device_id) if entry.device_id else None
    area=areas.async_get_area(device.area_id) if device and device.area_id else None
    return area.name if area else ''

async def snapshot(hass,request,conversation_id):
    user=await user_for(hass,request.context)
    entities=er.async_get(hass);devices=dr.async_get(hass);areas=ar.async_get(hass);catalog=[]
    for state in hass.states.async_all():
        if not async_should_expose(hass,'conversation',state.entity_id):continue
        if request.context.user_id and not user.permissions.check_entity(state.entity_id,POLICY_READ):continue
        entry=entities.async_get(state.entity_id)
        if entry and (entry.disabled_by or entry.hidden_by):continue
        device=devices.async_get(entry.device_id) if entry and entry.device_id else None
        area_id=(entry.area_id if entry else None) or (device.area_id if device else None)
        area=areas.async_get_area(area_id) if area_id else None
        catalog.append({'entity_id':state.entity_id,'name':str(state.name),'state':state.state,
            'attributes':dict(state.attributes),'area':area.name if area else '',
            'aliases':[a for a in entry.aliases if isinstance(a,str)] if entry else [],
            'last_changed':state.last_changed.isoformat() if getattr(state,'last_changed',None) else None,
            'control':not request.context.user_id or user.permissions.check_entity(state.entity_id,POLICY_CONTROL)})
    return {'text':request.text[:2000],'catalog':catalog,'origin':origin_area(hass,request),
        'user_id':request.context.user_id,'valid_user':not request.context.user_id or bool(user),
        'admin':not request.context.user_id or bool(user and user.is_admin),'device_id':request.device_id,
        'satellite_id':getattr(request,'satellite_id',None),'conversation_id':conversation_id,
        'timezone':str(hass.config.time_zone),'services':[d+'.'+s for d,services in hass.services.async_services().items() for s in services]}

async def converse(hass,request,conversation_id):
    active=hass.data.setdefault(DOMAIN,{}).setdefault('bridge_requests',{})
    if len(active)>=MAX_REQUESTS:return "I'm handling another request. Please try again in a moment."
    ident=secrets.token_hex(24)
    lease={'request':request,'until':time.monotonic()+30,'id':ident,'operations':set(),'mutation':False}
    active[ident]=lease
    try:
        payload=await snapshot(hass,request,conversation_id)
        lease['ids']={e['entity_id'] for e in payload['catalog']}
        payload['request_id']=ident
        response=await transport(hass,'request',json.loads(json.dumps(payload,default=str)))
        speech=response.get('speech')
        return speech if isinstance(speech,str) and 0<len(speech)<=6000 else "I couldn't read the Voice app's answer."
    except (OSError,ValueError,KeyError,TypeError,ClientError,HomeAssistantError,asyncio.TimeoutError):
        return "I couldn't finish that request. Voice may be updating. Please check any device you asked to control before trying again."
    finally:active.pop(ident,None)

# Strict bridge protocol: no arbitrary service or target supplied by the app.
SERVICES={
 'input_boolean':{'turn_on','turn_off'},'light':{'turn_on','turn_off'},'switch':{'turn_on','turn_off'},'fan':{'turn_on','turn_off','set_percentage'},
 'cover':{'open_cover','close_cover','set_cover_position'},'scene':{'turn_on'},
 'media_player':{'turn_on','turn_off','media_play','media_pause','media_stop','volume_set','volume_mute'},
 'climate':{'set_temperature','set_hvac_mode','turn_on','turn_off'},'weather':{'get_forecasts'}}
FIELDS={'entity_id','brightness_pct','rgb_color','percentage','position','volume_level','is_volume_muted','temperature','hvac_mode','type'}

async def execute(hass,lease,op,data):
    request=lease['request'];user=await user_for(hass,request.context)
    def live():
        if time.monotonic()>lease['until'] or hass.data.get(DOMAIN,{}).get('bridge_requests',{}).get(lease.get('id')) is not lease:raise HomeAssistantError('Voice request expired.')
    async def checked(eid,control=False):
        live()
        if not isinstance(eid,str) or eid not in lease['ids'] or not await permitted(hass,request.context,eid,control):
            raise HomeAssistantError('Device permission changed; request was stopped.')
    def mutate():
        live()
        if lease['mutation']:raise HomeAssistantError('A command was already attempted. It was not repeated.')
        lease['mutation']=True
    if op in {'planner','flow'}:
        if not isinstance(data.get('text'),str) or len(data['text'])>500:raise HomeAssistantError('Invalid request.')
        if op=='planner':
            from .planner import ask
        else:
            if request.context.user_id and not user.is_admin:raise HomeAssistantError('Administrator permission required.')
            mutate()
            from .flows import ask
        return await ask(hass,data['text'])
    if op=='history':
        eid=data.get('entity_id');await checked(eid)
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.history import get_significant_states
        state=hass.data.setdefault(DOMAIN,{})
        if state.get('history_task') and not state['history_task'].done():raise HomeAssistantError('History request is already running.')
        now=datetime.now(timezone.utc)
        task=asyncio.ensure_future(get_instance(hass).async_add_executor_job(partial(get_significant_states,hass,now-timedelta(hours=24),now,[eid],include_start_time_state=False,significant_changes_only=True,no_attributes=True)))
        state['history_task']=task
        task.add_done_callback(lambda done:done.exception() if not done.cancelled() else None)
        result=await asyncio.wait_for(asyncio.shield(task),5)
        return [{'state':s.state,'last_changed':s.last_changed.isoformat()} for s in result.get(eid,[])][-2000:]
    if op=='timer':
        from .native_timer import reply
        mutate()
        return await reply(hass,request,data)
    if op=='thermostat':
        if not isinstance(data.get('data'),dict) or set(data['data'])-{'entity_id','temperature','hvac_mode'}:raise HomeAssistantError('Invalid thermostat request.')
        if data.get('domain')!='climate' or data.get('service') not in {'set_temperature','set_hvac_mode','turn_on','turn_off','controller_status','controller_resume'}:raise HomeAssistantError('Unsupported thermostat operation.')
        await checked(data.get('data',{}).get('entity_id'),True)
        mutate()
        from .thermostat import route
        result=await route(hass,data)
        if result is None:
            lease['mutation']=False # Only an explicit unmanaged reply permits the direct fallback.
            lease['unmanaged']=data['data']['entity_id']
        return result
    if op=='service':
        domain=data.get('domain');service=data.get('service');fields=data.get('data')
        if service not in SERVICES.get(domain,set()) or not isinstance(fields,dict) or set(fields)-FIELDS:raise HomeAssistantError('Unsupported device operation.')
        if domain=='climate' and lease.get('unmanaged')!=fields.get('entity_id'):raise HomeAssistantError('Thermostat Controller must be checked first.')
        ids=fields.get('entity_id');ids=[ids] if isinstance(ids,str) else ids
        if not isinstance(ids,list) or not 1<=len(ids)<=100:raise HomeAssistantError('Invalid device targets.')
        for eid in ids:
            await checked(eid,domain!='weather')
            if not eid.startswith(domain+'.'):raise HomeAssistantError('Invalid target type.')
            state=hass.states.get(eid)
            if not state or state.state in {'unknown','unavailable'} and domain!='scene':raise HomeAssistantError('Device reading is unavailable.')
            if domain=='cover' and (not state or state.attributes.get('device_class') not in {'blind','shade','curtain','shutter'}):raise HomeAssistantError('Door and garage controls are not supported.')
        if domain!='weather':mutate()
        result=await asyncio.wait_for(hass.services.async_call(domain,service,fields,blocking=True,context=request.context,return_response=domain=='weather'),10)
        if domain!='weather':
            try:
                hass.bus.async_fire('pixora_insight',{'entity_id':ids,'source':'Pixora Voice',
                    'reason':'A Voice device request issued '+domain+'.'+service+'.',
                    'outcome':'requested','operation':domain+'.'+service,
                    'action_context':getattr(request.context,'id','')})
            except Exception:
                pass # Optional diagnostics must not change or repeat the device action.
        return result
    raise HomeAssistantError('Unknown Voice operation.')

def install_service(hass):
    async def action(call):
        value=call.data;lease=hass.data.get(DOMAIN,{}).get('bridge_requests',{}).get(value.get('request_id'))
        ident=value.get('operation_id')
        if not lease or time.monotonic()>lease['until'] or not isinstance(ident,str) or not 8<=len(ident)<=64 or ident in lease['operations'] or len(lease['operations'])>=8:
            raise HomeAssistantError('Voice request expired or operation already attempted.')
        if not isinstance(value.get('data',{}),dict):raise HomeAssistantError('Invalid Voice operation.')
        lease['operations'].add(ident) # Consume before awaiting: uncertain operations are never replayed.
        return {'result':await execute(hass,lease,value.get('op'),value.get('data',{}))}
    from homeassistant.core import SupportsResponse
    hass.services.async_register(DOMAIN,'runtime_action',action,supports_response=SupportsResponse.ONLY)
