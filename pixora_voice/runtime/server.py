"""App runtime gateway. HA owns authorization and all device side effects."""
import asyncio,json,secrets
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace as NS
from aiohttp import ClientError
from .engine import Entity
from .conversation import LocalVoice
from .context import Followups

class Runtime:
    def __init__(self,config_root,ha):
        self.config_root=config_root;self.ha=ha;self.followups=Followups();self.active=0
    async def answer(self,payload):
        if self.active>=4:raise RuntimeError('Voice is busy.')
        self.active+=1
        try:
            gateway=Gateway(self,payload)
            voice=LocalVoice(NS(entry_id='runtime'));voice.hass=gateway;voice.entity_id='conversation.pixora_voice_beta';voice.followups=self.followups
            request=NS(text=payload['text'],context=NS(user_id=payload.get('user_id')),device_id=payload.get('device_id'),satellite_id=payload.get('satellite_id'))
            log=NS(messages=[],conversation_id=payload.get('conversation_id'))
            log.async_add_assistant_content_without_tools=log.messages.append
            result=await voice._async_handle_message(request,log)
            return {'speech':result.speech}
        finally:self.active-=1

class Gateway:
    def __init__(self,runtime,payload):
        self.runtime=runtime;self.payload=payload;self.origin=payload.get('origin','');self.catalog=[];self.data={}
        for item in payload['catalog']:
            at=item.get('last_changed')
            self.catalog.append(Entity(item['entity_id'],item['name'],item['state'],item['attributes'],item.get('area',''),item.get('aliases',[]),last_changed=datetime.fromisoformat(at) if at else None))
        self.config=NS(time_zone=payload.get('timezone','UTC'),path=lambda *parts:str(runtime.config_root.joinpath(*parts)))
        def read(name,default):
            try:return json.loads(runtime.config_root.joinpath('.storage',name).read_text(encoding='utf-8'))
            except (OSError,ValueError):return default
        self.planner_enabled=read('pixora_voice_planner.json',{}).get('enabled') is True
        phrases=read('pixora_voice_flows.json',[])
        self.phrases=phrases[:64] if isinstance(phrases,list) and all(isinstance(p,str) for p in phrases) else []
        allowed={e['entity_id'] for e in payload['catalog'] if e.get('control')}
        async def user(uid):
            return NS(is_admin=payload.get('admin',False),permissions=NS(check_entity=lambda eid,policy:eid in allowed)) if payload.get('valid_user') else None
        self.auth=NS(async_get_user=user)
        self.states=NS(async_all=lambda:[NS(entity_id=e.entity_id,name=e.name) for e in self.catalog])
        async def call(domain,service,data,**kwargs):return await self.rpc('service',{'domain':domain,'service':service,'data':data})
        self.services=NS(has_service=lambda domain,service:domain+'.'+service in payload.get('services',[]),async_call=call)
    async def rpc(self,op,data):
        try:
            result=await self.runtime.ha('services/pixora_voice/runtime_action?return_response',{
                'request_id':self.payload['request_id'],'operation_id':secrets.token_hex(16),'op':op,'data':data})
            return result['service_response']['result']
        except (ValueError,KeyError,OSError,ClientError,asyncio.TimeoutError) as exc:raise RuntimeError('HA could not confirm the operation. It was not retried.') from exc
