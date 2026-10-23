"""Adapter contract tests with fixture HA registries; no HA installation touched."""
import asyncio,importlib,sys,types,unittest
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

    async def test_context_area_and_original_context_in_service_call(self):
        r=await self.ask('Turn on the ceiling light');self.assertIn('Sent',r.speech)
        call=self.hass.services.async_call.await_args;self.assertEqual(call.args[:2],('light','turn_on'));self.assertEqual(call.args[2]['entity_id'],'light.living');self.assertIs(call.kwargs['context'],self.context)

    async def test_exposure_and_read_permissions(self):
        self.hass.hidden.add('light.living');r=await self.ask('Turn on the ceiling light');self.assertIn('could not find',r.speech);self.hass.services.async_call.assert_not_awaited()
        self.hass.hidden.clear();self.read_denied.add('light.living');r=await self.ask('Turn on the ceiling light');self.assertIn('could not find',r.speech)

    async def test_control_permission_checked_for_every_target(self):
        self.control_denied.add('light.kitchen');r=await self.ask('Turn off all kitchen lights');self.assertIn('permission',r.speech);self.hass.services.async_call.assert_not_awaited()

    async def test_uncertain_command_not_retried(self):
        self.hass.services.async_call.side_effect=HAError('uncertain');r=await self.ask('Turn on the ceiling light');self.assertIn('could not confirm',r.speech);self.hass.services.async_call.assert_awaited_once()

    async def test_followup_scoped_to_conversation_and_current_states(self):
        self.request.device_id=None
        r=await self.ask('Turn on the ceiling light');self.assertTrue(r.continue_conversation);self.hass.services.async_call.assert_not_awaited()
        r=await self.ask('Kitchen');self.assertIn('Sent',r.speech);self.assertEqual(self.hass.services.async_call.await_args.args[2]['entity_id'],'light.kitchen')

    async def test_missing_user_fails_closed(self):
        self.hass.auth.async_get_user.return_value=None
        await self.ask('Turn on the ceiling light');self.hass.services.async_call.assert_not_awaited()

if __name__=='__main__':unittest.main()
