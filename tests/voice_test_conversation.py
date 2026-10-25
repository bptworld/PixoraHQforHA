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
class HAError(RuntimeError):pass
module('homeassistant.exceptions',HomeAssistantError=HAError)
module('homeassistant.components.homeassistant',async_should_expose=lambda hass,assistant,eid:eid not in hass.hidden)
module('homeassistant.components.conversation',ConversationEntity=object,ConversationEntityFeature=NS(CONTROL=1),AssistantContent=lambda **kw:NS(**kw),async_get_result_from_chat_log=lambda request,log:NS(speech=log.messages[-1].content,continue_conversation=log.messages[-1].content.endswith('?')))
for name in ('area_registry','device_registry','entity_registry'):module('homeassistant.helpers.'+name,async_get=lambda hass:None)
module('homeassistant.helpers.aiohttp_client',async_get_clientsession=lambda h:None)
bridge=importlib.import_module('custom_components.pixora_voice.bridge')
adapter=importlib.import_module('runtime.conversation')
adapter.er=bridge.er;adapter.dr=bridge.dr;adapter.ar=bridge.ar


class Registry:
    def __init__(self,values):self.values=values
    def async_get(self,key):return self.values.get(key)
    def async_get_area(self,key):return self.values.get(key)


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_device_capability_wins_over_planner_keywords_in_names(self):
        from unittest.mock import patch
        for name,area in [('Home Office window','Home Office'),('Dinner room window','Dinner Room')]:
            state=NS(entity_id='binary_sensor.office',name=name,state='on',attributes={'device_class':'window'})
            self.states.append(state)
            adapter.er.async_get(self.hass).values[state.entity_id]=NS(device_id=None,area_id='living',aliases=[],disabled_by=None,hidden_by=None)
            with patch('runtime.planner.ask',AsyncMock()) as planner:
                reply=await self.ask('Is the '+name+' open?')
                self.assertIn('open',reply.speech);planner.assert_not_awaited()
            self.states.remove(state)
        with patch('runtime.planner.ask',AsyncMock(return_value='Amy is home.')) as planner:
            self.assertIn('Amy is home',(await self.ask('Is Amy home?')).speech)
            planner.assert_awaited_once()

    async def test_tv_tonight_goes_to_planner_instead_of_device_matching(self):
        from unittest.mock import patch
        with patch('runtime.planner.ask',AsyncMock(return_value='Fire Country at 9 PM.')) as ask:
            result=await self.ask("What's on TV tonight?")
            self.assertEqual(result.speech,'Fire Country at 9 PM.');self.assertFalse(result.continue_conversation)
            ask.assert_awaited_once_with(self.hass,"What's on TV tonight?")
            self.hass.services.async_call.assert_not_awaited()

    async def test_actual_fish_tank_transcript_is_local_read_only_not_planner_search(self):
        from unittest.mock import patch
        state=NS(entity_id='switch.living_room_living_room_fishtank_light',name='Living Room Fishtank Light',state='on',attributes={})
        self.states.append(state)
        adapter.er.async_get(self.hass).values[state.entity_id]=NS(device_id=None,area_id='living',aliases=[],disabled_by=None,hidden_by=None)
        with patch('runtime.planner.enabled',AsyncMock(return_value=True)),patch('runtime.planner.ask',AsyncMock()) as planner:
            reply=await self.ask('The fish tank lights on.')
            self.assertIn('is on',reply.speech);self.assertFalse(reply.continue_conversation)
            planner.assert_not_awaited();self.hass.services.async_call.assert_not_awaited()

    async def test_recognized_and_typed_setpoint_text_have_identical_answers(self):
        self.states.append(NS(entity_id='climate.hall',name='Hall thermostat',state='heat',attributes={'temperature':68,'current_temperature':66,'hvac_action':'idle','temperature_unit':'°F'}))
        registry=adapter.er.async_get(self.hass)
        registry.values['climate.hall']=NS(device_id=None,area_id='living',aliases=[],disabled_by=None,hidden_by=None)
        self.request.device_id=None
        typed=await self.ask('what is the heat set to')
        self.request.device_id='speaker';self.context.user_id=None
        spoken=await self.ask('what is the heat set to')
        self.assertEqual(typed.speech,spoken.speech)
        self.assertIn('68 degrees Fahrenheit',spoken.speech)
        self.assertFalse(typed.continue_conversation);self.assertFalse(spoken.continue_conversation)
        self.hass.services.async_call.assert_not_awaited()

    async def test_computed_alias_sentinel_does_not_break_unrelated_questions(self):
        from enum import Enum
        class ComputedNameType(Enum):
            COMPUTED_NAME = 0
        state=NS(entity_id='climate.hall',name='Hall thermostat',state='heat',attributes={'current_temperature':68})
        self.states.append(state)
        registry=adapter.er.async_get(self.hass)
        registry.values[state.entity_id]=NS(device_id=None,area_id='living',aliases=[ComputedNameType.COMPUTED_NAME,'Hall heat'],disabled_by=None,hidden_by=None)
        reply=await self.ask('Is the heat running?')
        self.assertTrue(reply.speech)
        self.assertFalse(reply.continue_conversation)
        self.hass.services.async_call.assert_not_awaited()

    def setUp(self):
        self.agent=adapter.LocalVoice(NS(entry_id='local'));self.agent.entity_id='conversation.pixora_voice'
        self.read_denied=set();self.control_denied=set()
        permissions=NS(check_entity=lambda eid,policy:eid not in (self.read_denied if policy=='read' else self.control_denied))
        self.hass=NS(hidden=set(),auth=NS(async_get_user=AsyncMock(return_value=NS(permissions=permissions,is_admin=False))),services=NS(has_service=lambda *args:True,async_call=AsyncMock()))
        self.states=[NS(entity_id='light.kitchen',name='Ceiling light',state='on',attributes={}),NS(entity_id='light.living',name='Ceiling light',state='off',attributes={})]
        self.hass.states=NS(async_all=lambda:self.states);self.agent.hass=self.hass
        self.hass.phrases=[];self.hass.planner_enabled=False;self.hass.rpc=AsyncMock();self.hass.config=NS(time_zone='America/New_York')
        self.hass.services.async_services=lambda:{}
        entities=Registry({s.entity_id:NS(device_id=None,area_id='kitchen' if 'kitchen' in s.entity_id else 'living',aliases=set(),disabled_by=None,hidden_by=None) for s in self.states})
        devices=Registry({'speaker':NS(area_id='living')});areas=Registry({'living':NS(name='Living Room'),'kitchen':NS(name='Kitchen')})
        adapter.er.async_get=lambda h:entities;adapter.dr.async_get=lambda h:devices;adapter.ar.async_get=lambda h:areas
        self.context=NS(user_id='user');self.request=NS(text='',context=self.context,device_id='speaker',satellite_id=None)

    async def ask(self,text):
        self.request.text=text
        try:payload=await bridge.snapshot(self.hass,self.request,'test')
        except HAError:payload={'catalog':[],'origin':''}
        from runtime.engine import Entity
        self.hass.catalog=[Entity(e['entity_id'],e['name'],e['state'],e['attributes'],e['area'],e['aliases'],last_changed=next((getattr(s,'last_changed',None) for s in self.states if s.entity_id==e['entity_id']),None)) for e in payload['catalog']]
        self.hass.origin=payload['origin']
        log=NS(conversation_id='test',messages=[]);log.async_add_assistant_content_without_tools=log.messages.append
        return await self.agent._async_handle_message(self.request,log)

    async def test_configured_voice_flow_is_exact_and_stops_listening(self):
        from unittest.mock import patch
        with patch('runtime.flows.matches',AsyncMock(return_value=True)),patch('runtime.flows.ask',AsyncMock(return_value='Started Bedtime.')) as start:
            self.context.user_id=None
            reply=await self.ask('Good night')
            self.assertEqual(reply.speech,'Started Bedtime.');self.assertFalse(reply.continue_conversation)
            start.assert_awaited_once_with(self.hass,'Good night')
            self.hass.services.async_call.assert_not_awaited()
    async def test_non_admin_cannot_start_voice_flow(self):
        from unittest.mock import patch
        with patch('runtime.flows.matches',AsyncMock(return_value=True)),patch('runtime.flows.ask',AsyncMock()) as start:
            reply=await self.ask('Good night')
            self.assertIn('administrator',reply.speech);self.assertFalse(reply.continue_conversation);start.assert_not_awaited()
    async def test_clock_bypasses_planner_and_stops_listening(self):
        from unittest.mock import patch
        self.hass.config=NS(time_zone='America/New_York')
        with patch('runtime.planner.ask',AsyncMock()) as planner_ask:
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
        next(e for e in self.hass.catalog if e.entity_id=='light.living').last_changed=self.states[1].last_changed
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
        with patch('runtime.planner.ask',new=AsyncMock(return_value='A shared event.')) as ask:
            self.assertFalse((await self.ask("What's Bryan's schedule today?")).continue_conversation)
            self.assertFalse((await self.ask('And tomorrow?')).continue_conversation)
            self.assertEqual(ask.await_args.args[1],"What's Bryan's schedule tomorrow?")
            self.request.device_id='other'
            await self.ask('And tomorrow?');self.assertEqual(ask.await_count,2)

    async def test_unknown_question_searches_enabled_planner(self):
        from unittest.mock import patch
        with patch('runtime.planner.enabled',new=AsyncMock(return_value=True)), patch('runtime.planner.ask',new=AsyncMock(return_value='School concert is at Town Hall.')) as ask:
            result=await self.ask('Tell me about the school concert')
            ask.assert_awaited_once_with(self.hass,'Tell me about the school concert')
            self.assertIn('Town Hall',result.speech)
            self.assertFalse(result.continue_conversation)
            self.hass.services.async_call.assert_not_awaited()

    async def test_missing_answer_uses_requested_fallback(self):
        from unittest.mock import patch
        from runtime.engine import NOT_FOUND_REPLY
        with patch('runtime.planner.enabled',new=AsyncMock(return_value=True)), patch('runtime.planner.ask',new=AsyncMock(return_value=NOT_FOUND_REPLY)):
            result=await self.ask('Tell me about the lunar cheese festival')
            self.assertEqual(result.speech,NOT_FOUND_REPLY)
            self.assertFalse(result.continue_conversation)

    async def test_playing_question_followup_keeps_calendar_subject(self):
        from unittest.mock import patch
        with patch('runtime.planner.ask',new=AsyncMock(return_value='A shared game.')) as ask:
            await self.ask('Are the Kraken playing today?')
            result=await self.ask('And tomorrow?')
            self.assertEqual(ask.await_args.args[1],'Are the Kraken playing tomorrow?')
            self.assertFalse(result.continue_conversation)

    async def test_unknown_device_command_never_falls_through_to_search(self):
        from unittest.mock import patch
        with patch('runtime.planner.ask',new=AsyncMock()) as ask:
            await self.ask('Turn on the unknown lamp')
            ask.assert_not_awaited()
            self.hass.services.async_call.assert_not_awaited()

    async def test_command_word_inside_read_only_question_still_searches(self):
        from unittest.mock import patch
        with patch('runtime.planner.enabled',new=AsyncMock(return_value=True)), patch('runtime.planner.ask',new=AsyncMock(return_value='The manual is in the drawer.')) as ask:
            reply=await self.ask('Tell me about the TV set manual')
            ask.assert_awaited_once_with(self.hass,'Tell me about the TV set manual')
            self.assertIn('drawer',reply.speech)
            self.hass.services.async_call.assert_not_awaited()

if __name__=='__main__':unittest.main()
