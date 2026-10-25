"""App-owned conversation decisions; execution remains in the authenticated HA bridge."""
import asyncio,re
from types import SimpleNamespace as NS
from .engine import Entity,Result,answer,words,duration_answer,canonical_request,NOT_FOUND_REPLY
from .context import Followups,planner_followup,duration_question,reading_followup
HomeAssistantError=RuntimeError
conversation=NS(AssistantContent=lambda **values:NS(**values),async_get_result_from_chat_log=lambda request,log:NS(speech=log.messages[-1].content,continue_conversation=False))
POLICY_CONTROL='control'
class LocalVoice:
    _attr_name='Pixora Voice (Beta)'
    _attr_has_entity_name=True



    def __init__(self,entry):
        self._attr_unique_id=entry.entry_id
        self.followups=Followups()

    @property
    def supported_languages(self):return ['en']

    async def _async_handle_message(self,user_input,chat_log):
        key=self.followups.key(user_input,chat_log.conversation_id)
        previous=self.followups.get(key)
        self.followups.clear(key)
        from .planner import is_planner_question,ask as ask_planner,enabled as planner_enabled,is_write_request
        from .flows import matches as matches_flow,ask as ask_flow
        if await matches_flow(self.hass,user_input.text):
            uid=user_input.context.user_id
            user=await self.hass.auth.async_get_user(uid) if uid else None
            speech=await ask_flow(self.hass,user_input.text) if not uid or user and getattr(user,'is_admin',False) else "I can't start voice Flows from this account. An administrator can help with access."
            chat_log.async_add_assistant_content_without_tools(conversation.AssistantContent(agent_id=self.entity_id,content=speech))
            return self.finish(user_input,chat_log)
        from .engine import clock_answer
        clock=clock_answer(user_input.text,getattr(getattr(self.hass,'config',None),'time_zone',None))
        if clock:
            chat_log.async_add_assistant_content_without_tools(conversation.AssistantContent(agent_id=self.entity_id,content=clock))
            return self.finish(user_input,chat_log)
        from .flows import variable_question
        variable_name=variable_question(user_input.text)
        if variable_name:
            uid=user_input.context.user_id
            user=await self.hass.auth.async_get_user(uid) if uid else None
            speech=await ask_flow(self.hass,'__pixora_voice_variable__:'+variable_name) if not uid or user and getattr(user,'is_admin',False) else "I can't read Flow variables from this account. Please check its permissions."
            chat_log.async_add_assistant_content_without_tools(conversation.AssistantContent(agent_id=self.entity_id,content=speech))
            return self.finish(user_input,chat_log)
        from .timers import reply as timer_reply
        timer=await timer_reply(self.hass,user_input)
        if timer:
            chat_log.async_add_assistant_content_without_tools(conversation.AssistantContent(agent_id=self.entity_id,content=timer))
            return self.finish(user_input,chat_log)
        from .thermostat import request_kind as thermostat_kind, plan as thermostat_plan
        from .extra_reads import request_kind
        planner_text=planner_followup(user_input.text,previous)
        from .engine import interpret,choose
        local_property,_=interpret(user_input.text)
        local_read=bool(local_property and choose(user_input.text,self.hass.catalog,local_property,self.hass.origin))
        if not local_read and not thermostat_kind(user_input.text, [str(s.name) for s in self.hass.states.async_all() if s.entity_id.startswith("climate.")]) and not request_kind(user_input.text) and (planner_text or is_planner_question(user_input.text)):
            uid=user_input.context.user_id
            allowed=not uid or await self.hass.auth.async_get_user(uid)
            speech=await ask_planner(self.hass,planner_text or user_input.text) if allowed else "I can't read Planner from this account. Please check its permissions."
            if allowed:self.followups.put(key,source='planner',text=planner_text or user_input.text)
            chat_log.async_add_assistant_content_without_tools(conversation.AssistantContent(agent_id=self.entity_id,content=speech))
            return self.finish(user_input,chat_log)
        user_id=user_input.context.user_id
        user=await self.hass.auth.async_get_user(user_id) if user_id else None
        catalog=self.hass.catalog
        origin=self.hass.origin
        text=user_input.text
        from .extra_reads import reply as extra_read
        from .controls import plan as control_plan
        extra=await extra_read(self.hass,text,catalog,origin)
        control_text=text;control_catalog=catalog
        if previous and previous.get('source')=='home' and len(previous.get('ids',[]))==1 and re.match(r'^(?:make|set|dim|brighten)\b',text,re.I):
            prior=next((e for e in catalog if e.entity_id==previous['ids'][0]),None)
            if prior:
                control_text,replaced=re.subn(r'\b(?:it|that)\b',lambda match:prior.name,text,flags=re.I)
                if replaced:control_catalog=[prior]
        extended=thermostat_plan(text,catalog,origin)
        if extended is None:extended=extra if extra is not None else control_plan(control_text,control_catalog,origin)
        if extended is not None:
            result=extended
        elif words(text) in (['cancel'],['never','mind'],['nevermind']):
            result=Result('Okay.','cancelled')
        elif duration_question(text):
            found=[e for e in catalog if previous and previous.get('source')=='home' and e.entity_id in previous.get('ids',[])]
            result=duration_answer(found[0]) if len(found)==1 else Result('Which device do you mean? Ask about it by name first, then ask how long.','clarify')
            if found:result.property=previous.get('property','')
        elif reading_followup(text,previous):
            found=[e for e in catalog if e.entity_id in previous['ids']]
            result=answer(re.sub(r'\b(it|that|they)\b',found[0].name,text,flags=re.I).replace('still ',''),found,origin) if len(found)==1 else Result('Which device do you mean? Please include its name.','clarify')
        elif previous and previous.get('source')=='room' and any(words(text)==words(e.area) for e in catalog if e.area):
            room=next(e.area for e in catalog if words(text)==words(e.area))
            result=answer(previous['text'].replace('in here','in '+room),catalog,room)
        elif previous and previous.get('source')=='clarify':
            # A room/name clarification may be spoken only after another wake word.
            from .engine import choose,interpret
            matches=choose(text,[e for e in catalog if e.entity_id in previous['ids']],previous['property']) if not interpret(text)[0] else []
            result=answer(previous['text'],[matches[0][1]],origin) if matches and (len(matches)==1 or matches[0][0]>matches[1][0]) else answer(text,catalog,origin)
        else:result=answer(text,catalog,origin)
        if result.kind=='unsupported' and not is_write_request(text):
            speech=NOT_FOUND_REPLY
            if (not user_id or user) and await planner_enabled(self.hass):
                speech=await ask_planner(self.hass,text)
                if speech!=NOT_FOUND_REPLY:self.followups.put(key,source='planner',text=text)
            if speech==NOT_FOUND_REPLY and not await planner_enabled(self.hass):speech="I can help with home devices, weather, timers, time and dates. For schedules or shared lists, enable Planner in the Voice app."
            result=Result(speech)
        if result.choices:self.followups.put(key,source='clarify',ids=[c['entity_id'] for c in result.choices][:20],property=result.property,text=text)
        elif result.kind=='clarify' and 'Which room' in result.speech:self.followups.put(key,source='room',text=canonical_request(text))
        if result.command:
            ids=result.entities
            if user_id and (not user or any(not user.permissions.check_entity(eid,POLICY_CONTROL) for eid in ids)):
                result=Result("I can't control those devices from this account. Please check its permissions.",'denied')
            elif result.command['service'] not in {'controller_status','controller_resume'} and not self.hass.services.has_service(result.command['domain'],result.command['service']):
                result=Result("I can't do that with this device. It doesn't support that control.",'unsupported')
            else:
                try:
                    reply = None
                    if result.command['domain'] == 'climate':
                        from .thermostat import route
                        reply = await route(self.hass, result.command)
                    if reply is not None:
                        result = Result(reply)
                    else:
                        await asyncio.wait_for(self.hass.services.async_call(result.command['domain'],result.command['service'],result.command['data'],blocking=True,context=user_input.context),10)
                except (HomeAssistantError,asyncio.TimeoutError):
                    # The device may have accepted the command. Never blindly retry.
                    result=Result("I'm not sure whether that command went through. Please check the device before trying again.",'uncertain')
        if result.entities and not result.command and result.kind=='answer':self.followups.put(key,source='home',ids=result.entities[:20],property=result.property,text=text)
        chat_log.async_add_assistant_content_without_tools(conversation.AssistantContent(agent_id=self.entity_id,content=result.speech))
        return self.finish(user_input,chat_log)

    def finish(self,user_input,chat_log):
        # Single request per wake word, including clarification and failure replies.
        result=conversation.async_get_result_from_chat_log(user_input,chat_log)
        result.continue_conversation=False
        return result
