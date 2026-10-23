"""Assist adapter: fresh HA state, exposure, user permissions and satellite areas."""
import time
from homeassistant.components import conversation
from homeassistant.components.homeassistant import async_should_expose
from homeassistant.auth.permissions.const import POLICY_READ,POLICY_CONTROL
from homeassistant.helpers import area_registry as ar,device_registry as dr,entity_registry as er
from homeassistant.exceptions import HomeAssistantError
from .engine import Entity,Result,answer,choose,interpret


async def async_setup_entry(hass,entry,async_add_entities):
    async_add_entities([LocalVoice(entry)])


class LocalVoice(conversation.ConversationEntity):
    _attr_name='Pixora Voice (Beta)'
    _attr_has_entity_name=True
    _attr_supported_features=conversation.ConversationEntityFeature.CONTROL

    def __init__(self,entry):
        self._attr_unique_id=entry.entry_id
        self.pending={}

    @property
    def supported_languages(self):return ['en']

    def origin_area(self,user_input,entities,devices,areas):
        device=devices.async_get(user_input.device_id) if user_input.device_id else None
        if not device and getattr(user_input,'satellite_id',None):
            entry=entities.async_get(user_input.satellite_id)
            if entry:
                area=areas.async_get_area(entry.area_id) if entry.area_id else None
                if area:return area.name
                device=devices.async_get(entry.device_id) if entry.device_id else None
        area=areas.async_get_area(device.area_id) if device and device.area_id else None
        return area.name if area else ''

    async def _async_handle_message(self,user_input,chat_log):
        entities=er.async_get(self.hass);devices=dr.async_get(self.hass);areas=ar.async_get(self.hass)
        user_id=user_input.context.user_id
        user=await self.hass.auth.async_get_user(user_id) if user_id else None
        catalog=[]
        for state in self.hass.states.async_all():
            if not async_should_expose(self.hass,'conversation',state.entity_id):continue
            if user_id and (not user or not user.permissions.check_entity(state.entity_id,POLICY_READ)):continue
            entry=entities.async_get(state.entity_id)
            if entry and (entry.disabled_by or entry.hidden_by):continue
            device=devices.async_get(entry.device_id) if entry and entry.device_id else None
            area_id=(entry.area_id if entry else None) or (device.area_id if device else None)
            area=areas.async_get_area(area_id) if area_id else None
            aliases=list(entry.aliases) if entry else []
            catalog.append(Entity(state.entity_id,state.name,state.state,dict(state.attributes),area.name if area else '',aliases))
        origin=self.origin_area(user_input,entities,devices,areas)
        key=(chat_log.conversation_id,user_id,user_input.device_id)
        self.pending={k:v for k,v in self.pending.items() if v['expires']>time.monotonic()}
        previous=self.pending.pop(key,None)
        text=user_input.text
        if previous and not interpret(text)[0]:
            matches=choose(text,[e for e in catalog if e.entity_id in previous['ids']],previous['property'])
            if matches and (len(matches)==1 or matches[0][0]>matches[1][0]):
                result=answer(previous['text'],[matches[0][1]],origin)
            else:result=Result('Please repeat the full request with the room and device name.','clarify')
        else:result=answer(text,catalog,origin)
        if result.choices:
            if len(self.pending)>=100:self.pending.pop(next(iter(self.pending)))
            self.pending[key]={'ids':[c['entity_id'] for c in result.choices],'property':result.property,'text':text,'expires':time.monotonic()+120}
        if result.command:
            ids=result.entities
            if user_id and (not user or any(not user.permissions.check_entity(eid,POLICY_CONTROL) for eid in ids)):
                result=Result('You do not have permission to control those devices.','denied')
            elif not self.hass.services.has_service(result.command['domain'],result.command['service']):
                result=Result('That device does not support the requested control.','unsupported')
            else:
                try:
                    await self.hass.services.async_call(result.command['domain'],result.command['service'],result.command['data'],blocking=True,context=user_input.context)
                except HomeAssistantError:
                    # The device may have accepted the command. Never blindly retry.
                    result=Result('I could not confirm that command. Please check the device.','uncertain')
        chat_log.async_add_assistant_content_without_tools(conversation.AssistantContent(agent_id=self.entity_id,content=result.speech))
        return conversation.async_get_result_from_chat_log(user_input,chat_log)
