"""Adapter contract tests with fixture HA registries; no HA installation touched."""
import asyncio,importlib,sys,types,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'pixora_voice'))

def module(name,**attrs):
    mod=types.ModuleType(name);mod.__dict__.update(attrs);sys.modules[name]=mod;return mod

module('homeassistant');module('homeassistant.components');module('homeassistant.helpers')
module('homeassistant.auth');module('homeassistant.auth.permissions')
module('homeassistant.auth.permissions.const',POLICY_READ='read',POLICY_CONTROL='control')
module('homeassistant.const',Platform=NS(CONVERSATION='conversation'))
class HAError(Exception):pass
module('homeassistant.exceptions',HomeAssistantError=HAError)
module('homeassistant.components.homeassistant',async_should_expose=lambda hass,assistant,eid:eid not in hass.hidden)
module('homeassistant.components.conversation',ConversationEntity=object,ConversationEntityFeature=NS(CONTROL=1),AssistantContent=lambda **kw:NS(**kw),async_get_result_from_chat_log=lambda request,log:NS(speech=log.messages[-1].content,continue_conversation=log.messages[-1].content.endswith('?')))
for name in ('area_registry','device_registry','entity_registry'):module('homeassistant.helpers.'+name,async_get=lambda hass:None)
adapter=importlib.import_module('custom_components.pixora_voice.conversation')


class Registry:
    def __init__(self,values):self.values=values
    def async_get(self,key):return self.values.get(key)
    def async_get_area(self,key):return self.values.get(key)


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.agent=adapter.LocalVoice(NS(entry_id='local'));self.agent.entity_id='conversation.pixora_voice'
        self.read_denied=set();self.control_denied=set()
        permissions=NS(check_entity=lambda eid,policy:eid not in (self.read_denied if policy=='read' else self.control_denied))
        self.hass=NS(hidden=set(),auth=NS(async_get_user=AsyncMock(return_value=NS(permissions=permissions))),services=NS(has_service=lambda *args:True,async_call=AsyncMock()))
        self.states=[NS(entity_id='light.kitchen',name='Ceiling light',state='on',attributes={}),NS(entity_id='light.living',name='Ceiling light',state='off',attributes={})]
        self.hass.states=NS(async_all=lambda:self.states);self.agent.hass=self.hass
        entities=Registry({s.entity_id:NS(device_id=None,area_id='kitchen' if 'kitchen' in s.entity_id else 'living',aliases=set(),disabled_by=None,hidden_by=None) for s in self.states})
        devices=Registry({'speaker':NS(area_id='living')});areas=Registry({'living':NS(name='Living Room'),'kitchen':NS(name='Kitchen')})
        adapter.er.async_get=lambda h:entities;adapter.dr.async_get=lambda h:devices;adapter.ar.async_get=lambda h:areas
        self.context=NS(user_id='user');self.request=NS(text='',context=self.context,device_id='speaker',satellite_id=None)

    async def ask(self,text):
        self.request.text=text
        log=NS(conversation_id='test',messages=[]);log.async_add_assistant_content_without_tools=log.messages.append
        return await self.agent._async_handle_message(self.request,log)

    async def test_configured_voice_flow_is_exact_and_stops_listening(self):
        from unittest.mock import patch
        with patch('custom_components.pixora_voice.flows.matches',AsyncMock(return_value=True)),patch('custom_components.pixora_voice.flows.ask',AsyncMock(return_value='Started Bedtime.')) as start:
            self.context.user_id=None
            reply=await self.ask('Good night')
            self.assertEqual(reply.speech,'Started Bedtime.');self.assertFalse(reply.continue_conversation)
            start.assert_awaited_once_with(self.hass,'Good night')
            self.hass.services.async_call.assert_not_awaited()
    async def test_non_admin_cannot_start_voice_flow(self):
        from unittest.mock import patch
        with patch('custom_components.pixora_voice.flows.matches',AsyncMock(return_value=True)),patch('custom_components.pixora_voice.flows.ask',AsyncMock()) as start:
            reply=await self.ask('Good night')
            self.assertIn('administrator',reply.speech);self.assertFalse(reply.continue_conversation);start.assert_not_awaited()
    async def test_clock_bypasses_planner_and_stops_listening(self):
        from unittest.mock import patch
        self.hass.config=NS(time_zone='America/New_York')
        with patch('custom_components.pixora_voice.planner.ask',AsyncMock()) as planner_ask:
            reply=await self.ask('what time is it')
            self.assertTrue(reply.speech.startswith("It's "));self.assertFalse(reply.continue_conversation)
            planner_ask.assert_not_awaited();self.hass.services.async_call.assert_not_awaited()

    async def test_context_area_and_original_context_in_service_call(self):
        r=await self.ask('Turn on the ceiling light');self.assertIn('Okay, turning on',r.speech)
        call=self.hass.services.async_call.await_args;self.assertEqual(call.args[:2],('light','turn_on'));self.assertEqual(call.args[2]['entity_id'],'light.living');self.assertIs(call.kwargs['context'],self.context)

    async def test_exposure_and_read_permissions(self):
        self.hass.hidden.add('light.living');r=await self.ask('Turn on the ceiling light');self.assertIn("can't find",r.speech);self.hass.services.async_call.assert_not_awaited()
        self.hass.hidden.clear();self.read_denied.add('light.living');r=await self.ask('Turn on the ceiling light');self.assertIn("can't find",r.speech)

    async def test_control_permission_checked_for_every_target(self):
        self.control_denied.add('light.kitchen');r=await self.ask('Turn off all kitchen lights');self.assertIn('permission',r.speech);self.hass.services.async_call.assert_not_awaited()

    async def test_uncertain_command_not_retried(self):
        self.hass.services.async_call.side_effect=HAError('uncertain');r=await self.ask('Turn on the ceiling light');self.assertIn("not sure whether",r.speech);self.hass.services.async_call.assert_awaited_once()

    async def test_followup_scoped_to_conversation_and_current_states(self):
        self.request.device_id=None
        r=await self.ask('Turn on the ceiling light');self.assertFalse(r.continue_conversation);self.hass.services.async_call.assert_not_awaited()
        r=await self.ask('Kitchen');self.assertIn('Okay, turning on',r.speech);self.assertEqual(self.hass.services.async_call.await_args.args[2]['entity_id'],'light.kitchen')

    async def test_cancel_clarification_does_not_send_command(self):
        self.request.device_id=None
        await self.ask('Turn on the ceiling light')
        r=await self.ask('Never mind')
        self.assertEqual(r.speech,'Okay.');self.hass.services.async_call.assert_not_awaited()
        r=await self.ask('Kitchen')
        self.hass.services.async_call.assert_not_awaited()

    async def test_every_reply_ends_listening_including_clarification(self):
        self.request.device_id=None
        for text in ['Turn on the ceiling light','Kitchen','Is the ceiling light on?','How long has it been on?','Never mind']:
            self.assertFalse((await self.ask(text)).continue_conversation)

    async def test_context_memory_is_bounded(self):
        for i in range(1000):self.agent.followups.put(('user',str(i)),source='home',ids=['light.living'])
        self.assertEqual(len(self.agent.followups.items),64)

    async def test_timeout_returns_once_and_stops_listening(self):
        self.hass.services.async_call.side_effect=asyncio.TimeoutError
        result=await self.ask('Turn on the ceiling light')
        self.assertIn("not sure whether",result.speech);self.assertFalse(result.continue_conversation)
        self.hass.services.async_call.assert_awaited_once()

    async def test_context_survives_new_wake_conversation_but_not_new_user(self):
        await self.ask('Is the ceiling light off?')
        self.states[1].last_changed=datetime.now(timezone.utc)-timedelta(minutes=3)
        self.request.text='How long has it been off?'
        log=NS(conversation_id='new-wake',messages=[]);log.async_add_assistant_content_without_tools=log.messages.append
        result=await self.agent._async_handle_message(self.request,log)
        self.assertIn('3 minutes',result.speech);self.assertFalse(result.continue_conversation)
        self.context.user_id='different-user'
        self.assertIn('Which device',(await self.ask('How long has it been off?')).speech)

    async def test_missing_user_fails_closed(self):
        self.hass.auth.async_get_user.return_value=None
        await self.ask('Turn on the ceiling light');self.hass.services.async_call.assert_not_awaited()

    async def test_read_followup_is_fresh_and_does_not_command(self):
        self.states[1].last_changed=datetime.now(timezone.utc)-timedelta(minutes=5)
        await self.ask('Is the ceiling light off?')
        self.states[1].state='on'
        result=await self.ask('Is it still off?');self.assertIn('is on',result.speech)
        result=await self.ask('How long has it been on?');self.assertIn('5 minutes',result.speech)
        self.hass.services.async_call.assert_not_awaited()

    async def test_followup_permission_and_speaker_isolation(self):
        await self.ask('Is the ceiling light off?')
        self.request.satellite_id='another_speaker'
        self.assertIn('Which device', (await self.ask('How long has it been off?')).speech)
        self.request.satellite_id=None
        self.read_denied.add('light.living')
        self.assertIn('Which device',(await self.ask('How long has it been off?')).speech)

    async def test_followup_expiry_cancel_and_no_pronoun_commands(self):
        await self.ask('Is the ceiling light off?')
        for item in self.agent.followups.items.values():item['expires']=0
        self.assertIn('Which device',(await self.ask('How long has it been off?')).speech)
        await self.ask('Is the ceiling light off?');await self.ask('Never mind')
        self.assertIn('Which device',(await self.ask('How long has it been off?')).speech)
        await self.ask('Is the ceiling light off?');await self.ask('Turn it on')
        self.hass.services.async_call.assert_not_awaited()

    async def test_room_clarification(self):
        self.request.device_id=None
        self.assertIn('Which room',(await self.ask('Turn off the lights')).speech)
        self.assertIn('turning off',(await self.ask('Kitchen')).speech)
        self.assertEqual(self.hass.services.async_call.await_args.args[2]['entity_id'],['light.kitchen'])

    async def test_planner_date_followup_uses_same_question(self):
        from unittest.mock import patch
        with patch('custom_components.pixora_voice.planner.ask',new=AsyncMock(return_value='A shared event.')) as ask:
            self.assertFalse((await self.ask("What's Bryan's schedule today?")).continue_conversation)
            self.assertFalse((await self.ask('And tomorrow?')).continue_conversation)
            self.assertEqual(ask.await_args.args[1],"What's Bryan's schedule tomorrow?")
            self.request.device_id='other'
            await self.ask('And tomorrow?');self.assertEqual(ask.await_count,2)

    async def test_unknown_question_searches_enabled_planner(self):
        from unittest.mock import patch
        with patch('custom_components.pixora_voice.planner.enabled',new=AsyncMock(return_value=True)), patch('custom_components.pixora_voice.planner.ask',new=AsyncMock(return_value='School concert is at Town Hall.')) as ask:
            result=await self.ask('Tell me about the school concert')
            ask.assert_awaited_once_with(self.hass,'Tell me about the school concert')
            self.assertIn('Town Hall',result.speech)
            self.assertFalse(result.continue_conversation)
            self.hass.services.async_call.assert_not_awaited()

    async def test_missing_answer_uses_requested_fallback(self):
        from unittest.mock import patch
        from custom_components.pixora_voice.engine import NOT_FOUND_REPLY
        with patch('custom_components.pixora_voice.planner.enabled',new=AsyncMock(return_value=True)), patch('custom_components.pixora_voice.planner.ask',new=AsyncMock(return_value=NOT_FOUND_REPLY)):
            result=await self.ask('Tell me about the lunar cheese festival')
            self.assertEqual(result.speech,NOT_FOUND_REPLY)
            self.assertFalse(result.continue_conversation)

    async def test_playing_question_followup_keeps_calendar_subject(self):
        from unittest.mock import patch
        with patch('custom_components.pixora_voice.planner.ask',new=AsyncMock(return_value='A shared game.')) as ask:
            await self.ask('Are the Kraken playing today?')
            result=await self.ask('And tomorrow?')
            self.assertEqual(ask.await_args.args[1],'Are the Kraken playing tomorrow?')
            self.assertFalse(result.continue_conversation)

    async def test_unknown_device_command_never_falls_through_to_search(self):
        from unittest.mock import patch
        with patch('custom_components.pixora_voice.planner.ask',new=AsyncMock()) as ask:
            await self.ask('Turn on the unknown lamp')
            ask.assert_not_awaited()
            self.hass.services.async_call.assert_not_awaited()

    async def test_command_word_inside_read_only_question_still_searches(self):
        from unittest.mock import patch
        with patch('custom_components.pixora_voice.planner.enabled',new=AsyncMock(return_value=True)), patch('custom_components.pixora_voice.planner.ask',new=AsyncMock(return_value='The manual is in the drawer.')) as ask:
            reply=await self.ask('Tell me about the TV set manual')
            ask.assert_awaited_once_with(self.hass,'Tell me about the TV set manual')
            self.assertIn('drawer',reply.speech)
            self.hass.services.async_call.assert_not_awaited()

if __name__=='__main__':unittest.main()
