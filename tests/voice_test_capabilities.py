"""Capability, routing and resource-bound tests; no live HA or device writes."""
import asyncio,sys,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,patch
from datetime import datetime,timedelta,timezone
sys.path.insert(0,str(Path(__file__).resolve().parent))
import voice_test_conversation as adapter_fixture
module=adapter_fixture.module
from custom_components.pixora_voice.engine import Entity,Result
from custom_components.pixora_voice.controls import plan
from custom_components.pixora_voice.timers import timer_request,reply as timer_reply
from custom_components.pixora_voice.extra_reads import reply as extra_reply
from custom_components.pixora_voice.flows import variable_question

class ControlTests(unittest.TestCase):
 def setUp(self):
  self.catalog=[Entity('climate.home','Thermostat','heat',{'supported_features':385,'temperature':70,'min_temp':50,'max_temp':85,'temperature_unit':'°F','hvac_modes':['heat','cool','off']},'Living Room'),Entity('fan.kitchen','Kitchen fan','on',{'supported_features':1},'Kitchen'),Entity('cover.kitchen','Kitchen blinds','closed',{'supported_features':7,'device_class':'blind'},'Kitchen'),Entity('light.ceiling','Ceiling light','on',{'brightness':128,'supported_color_modes':['rgb']},'Living Room'),Entity('scene.movie','Movie','unknown',{},'Living Room'),Entity('media_player.living','Living Room TV','playing',{'supported_features':16781,'media_title':'Fixture song','media_artist':'Fixture artist'},'Living Room')]
 def test_each_supported_control(self):
  for text,domain,service,field,value in [('Set the thermostat to seventy two degrees','climate','set_temperature','temperature',72),('Turn the heat up two degrees','climate','set_temperature','temperature',72),('Set kitchen fan to high','fan','set_percentage','percentage',100),('Close kitchen blinds','cover','close_cover',None,None),('Set kitchen blinds to 50 percent','cover','set_cover_position','position',50),('Set ceiling light to red','light','turn_on','rgb_color',(255,0,0)),('Make ceiling light brighter','light','turn_on','brightness_pct',60),('Pause the Living Room TV','media_player','media_pause',None,None),('Set Living Room TV volume to 30 percent','media_player','volume_set','volume_level',.3)]:
   result=plan(text,self.catalog,'Living Room');self.assertIsNotNone(result,text);self.assertIsNotNone(result.command,(text,result.speech));self.assertEqual((result.command['domain'],result.command['service']),(domain,service))
   if field:self.assertEqual(result.command['data'][field],value,text)
 def test_scenes_have_no_state_and_are_still_valid(self):
  result=plan('Activate Movie scene',self.catalog,'Living Room');self.assertEqual(result.command['service'],'turn_on')
 def test_bounds_features_and_ambiguity(self):
  for text in ('Set thermostat to 90 degrees','Turn heat up ten degrees','Set kitchen fan to 200 percent','Set kitchen blinds to 101 percent'):
   self.assertIsNone(plan(text,self.catalog,'Living Room').command,text)
  self.catalog[1].attributes['supported_features']=0;self.assertIsNone(plan('Set kitchen fan to high',self.catalog).command)
  self.catalog.append(Entity('light.other','Other light','on',{'brightness':100},'Living Room'))
  self.assertIsNone(plan('Make it brighter',self.catalog,'Living Room').command)
 def test_security_and_compounds_are_not_planned(self):
  for text in ('Unlock the front door','Open the garage','Set thermostat to 72 degrees and close kitchen blinds','Do not close kitchen blinds'):
   result=plan(text,self.catalog,'Living Room');self.assertTrue(result is None or result.command is None,text)
  self.catalog[2].attributes['device_class']='garage';self.assertIsNone(plan('Open kitchen blinds',self.catalog).command)
 def test_explicit_media_room_is_never_discarded(self):
  kitchen=Entity('media_player.kitchen','Kitchen speaker','playing',{'supported_features':1},'Kitchen')
  self.assertIsNone(plan('Pause the Media Room speaker',[kitchen],'Living Room').command)
  media=Entity('media_player.media','Speaker','playing',{'supported_features':1},'Media Room')
  self.assertEqual(plan('Pause the Media Room speaker',[kitchen,media],'Kitchen').command['data']['entity_id'],media.entity_id)
 def test_weather_does_not_intercept_titles_or_device_names(self):
  from custom_components.pixora_voice.extra_reads import request_kind
  for text in ('When is the Rain concert tomorrow?','Turn off the rain light','What time is the Weather Report concert?'):
   self.assertIsNone(request_kind(text),text)
  for text in ("What's the weather like outside?",'Will it rain tomorrow?','Is it raining?','What is the forecast for tomorrow?'):
   self.assertEqual(request_kind(text),'weather',text)
 def test_media_reading(self):
  self.assertIn('Fixture song',plan("What's playing on Living Room TV?",self.catalog).speech)
 def test_variable_question(self):
  for text in ("What's the value of isKitchenMotion?",'Read isKitchenMotion variable','What is isKitchenMotion variable?'):
   self.assertEqual(variable_question(text),'isKitchenMotion')
  self.assertIsNone(variable_question('Set isKitchenMotion to true'))

class TimerTests(unittest.IsolatedAsyncioTestCase):
 def test_parser(self):
  self.assertEqual(timer_request('set a timer for ten minutes'),('HassStartTimer',{'minutes':10}))
  self.assertEqual(timer_request('set a 1 hour and 5 minute timer'),('HassStartTimer',{'hours':1,'minutes':5}))
  self.assertEqual(timer_request('how much time is left'),('HassTimerStatus',{}))
  self.assertEqual(timer_request('pause the pizza timer'),('HassPauseTimer',{'name':'pizza'}))
  for text in ('set a timer for 25 hours','set a timer for 0 seconds','set a timer for ten minutes then unlock the door'):
   self.assertEqual(timer_request(text)[0],'unsupported',text)
 async def test_native_handoff_and_no_retries(self):
  handler=AsyncMock(return_value=NS(response_type=NS(value='action_done')));module('homeassistant.helpers.intent',async_handle=handler)
  hass=NS(auth=NS(async_get_user=AsyncMock(return_value=NS())))
  request=NS(text='Set a timer for ten minutes',device_id='speaker',satellite_id='assist_satellite.living',context=NS(user_id=None))
  self.assertIn('10 minutes',await timer_reply(hass,request));handler.assert_awaited_once();self.assertEqual(handler.await_args.kwargs['device_id'],'speaker')
  handler.reset_mock();handler.side_effect=asyncio.TimeoutError
  self.assertIn('not sure',await timer_reply(hass,request));handler.assert_awaited_once()
  request.device_id=None;handler.reset_mock();self.assertIn('satellite',await timer_reply(hass,request));handler.assert_not_awaited()

class ReadTests(unittest.IsolatedAsyncioTestCase):
 async def test_weather_uses_configured_entity_and_bounded_forecast(self):
  tomorrow=datetime.now(timezone.utc)+timedelta(days=1)
  service=AsyncMock(return_value={'weather.home':{'forecast':[{'datetime':tomorrow.isoformat(),'condition':'rainy','precipitation_probability':80}]}})
  hass=NS(config=NS(time_zone='UTC'),services=NS(has_service=lambda *a:True,async_call=service))
  entity=Entity('weather.home','Home','sunny',{'temperature':60,'temperature_unit':'°F','supported_features':1})
  self.assertIn('sunny', (await extra_reply(hass,"What's it like outside?",[entity])).speech);service.assert_not_awaited()
  self.assertIn('80 percent',(await extra_reply(hass,'Will it rain tomorrow?',[entity])).speech);service.assert_awaited_once()
  self.assertIn('share one weather',(await extra_reply(hass,'Will it rain today?',[])).speech)
 async def test_history_single_device_one_day(self):
  now=datetime.now(timezone.utc);calls=[]
  async def execute(fn):calls.append(fn);return {'binary_sensor.front':[NS(state='on',last_changed=now-timedelta(minutes=10))]}
  module('homeassistant.components.recorder',get_instance=lambda hass:NS(async_add_executor_job=execute))
  module('homeassistant.components.recorder.history',get_significant_states=lambda *a,**kw:None)
  hass=NS(config=NS(time_zone='UTC'),data={});entity=Entity('binary_sensor.front','Front door','off',{'device_class':'door'})
  result=await extra_reply(hass,'When did the front door last open?',[entity]);self.assertIn('last recorded open',result.speech)
  self.assertEqual(calls[0].args[3],['binary_sensor.front']);self.assertEqual(calls[0].args[2]-calls[0].args[1],timedelta(hours=24));self.assertFalse(calls[0].keywords['include_start_time_state'])
  pending=asyncio.create_task(asyncio.sleep(10));hass.data['pixora_voice']['history_task']=pending
  self.assertIn('still checking',(await extra_reply(hass,'When did the front door last open?',[entity])).speech);pending.cancel()

class SpeechCoverageTests(unittest.TestCase):
 def test_local_examples_use_real_bounded_grammar(self):
  import json,tempfile
  from planner_phrases import update_local_phrases,MARKER
  from hassil import Intents,recognize
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'local.yaml';update_local_phrases(path)
   payload=json.loads(path.read_text(encoding='utf-8').removeprefix(MARKER))
   payload['lists']['name']={'values':['thermostat','kitchen fan','kitchen blinds','ceiling light','Movie','Living Room TV','front door']};payload['lists']['area']={'values':['Kitchen','Living Room']}
   intents=Intents.from_dict(payload)
   for text in ('why is the heat off','what is the thermostat status','how long is the thermostat override','resume the thermostat schedule','what time is it','will it rain tomorrow','set a timer for ten minutes','pause the timer','set the thermostat to seventy two degrees','turn the heat up two degrees','set kitchen fan to high','close kitchen blinds','set ceiling light to red','make it brighter','activate Movie scene','pause the Living Room TV','when did the front door last open'):
    self.assertIsNotNone(recognize(text,intents),text)
   self.assertLess(path.stat().st_size,12000)
 def test_planner_dates_and_variable_names(self):
  import json,tempfile
  from planner_phrases import update_phrases,update_voice_phrases,MARKER
  from hassil import Intents,recognize
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'planner.yaml';update_phrases(path,{'people':['Bryan'],'events':['Dentist']})
   intents=Intents.from_dict(json.loads(path.read_text(encoding='utf-8').removeprefix(MARKER)))
   for text in ("what is on the calendar this weekend","what is Bryans schedule next week","when is Bryan next appointment"):
    self.assertIsNotNone(recognize(text,intents),text)
   path=Path(folder)/'flows.yaml';update_voice_phrases(path,[],['isKitchenMotion'])
   intents=Intents.from_dict(json.loads(path.read_text(encoding='utf-8').removeprefix(MARKER)))
   self.assertIsNotNone(recognize('what is the value of is kitchen motion',intents))

class AdapterCapabilityTests(unittest.IsolatedAsyncioTestCase):
 def setUp(self):adapter_fixture.AdapterTests.setUp(self)
 async def ask(self,text):return await adapter_fixture.AdapterTests.ask(self,text)
 async def test_device_not_found_never_becomes_calendar_search(self):
  with patch('custom_components.pixora_voice.planner.ask',AsyncMock()) as ask:
   result=await self.ask('Is the missing door open?');ask.assert_not_awaited();self.assertIn('device',result.speech)
 async def test_control_permissions_and_single_turn(self):
  self.states.append(NS(entity_id='fan.living',name='Living fan',state='on',attributes={'supported_features':1}));self.control_denied.add('fan.living')
  result=await self.ask('Set Living fan to high');self.assertIn('permissions',result.speech);self.assertFalse(result.continue_conversation);self.hass.services.async_call.assert_not_awaited()
 async def test_named_relative_control_uses_exposed_prior_device(self):
  self.context.user_id=None
  self.states[1].attributes={'brightness':128}
  await self.ask('Is the Living Room ceiling light on?')
  self.hass.services.async_call.reset_mock()
  reply=await self.ask('Make it brighter')
  self.assertIn('adjusting',reply.speech);self.assertFalse(reply.continue_conversation)
  self.assertEqual(self.hass.services.async_call.await_args.args[2]['entity_id'],'light.living')
 async def test_invalid_account_cannot_read_variables(self):
  self.hass.auth.async_get_user=AsyncMock(return_value=None)
  with patch('custom_components.pixora_voice.flows.ask',AsyncMock()) as read:
   reply=await self.ask('Read isKitchenMotion variable');self.assertIn('permissions',reply.speech);read.assert_not_awaited()
 async def test_variable_read_goes_to_existing_flow_connection(self):
  self.context.user_id=None
  with patch('custom_components.pixora_voice.flows.ask',AsyncMock(return_value='isKitchenMotion is true.')) as read:
   result=await self.ask("What's the value of isKitchenMotion?")
   self.assertEqual(result.speech,'isKitchenMotion is true.');self.assertFalse(result.continue_conversation);read.assert_awaited_once_with(self.hass,'__pixora_voice_variable__:isKitchenMotion')
if __name__=='__main__':unittest.main()

class ThermostatRequestTests(unittest.TestCase):
 def test_named_requests_and_unrelated_topics(self):
  from custom_components.pixora_voice.thermostat import request_kind
  for text, kind in [('Resume Nest schedule','controller_resume'),('What is Nest status','controller_status'),('How long is Nest override','controller_status'),('Why is Nest off','controller_status')]:
   self.assertEqual(request_kind(text,['Nest']),kind)
  self.assertIsNone(request_kind('Why is the light off',['Nest']))
  self.assertIsNone(request_kind('What is Amy status',['Nest']))
