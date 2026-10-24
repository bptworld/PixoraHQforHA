"""Planner opt-in, correlation and owned vocabulary contracts."""
import asyncio,json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'pixora_voice'))
from planner_phrases import update_phrases,write_owned,MARKER
from custom_components.pixora_voice import planner
class PhraseTests(unittest.TestCase):
 def test_manual_calendar_team_and_search_are_recognized(self):
  from hassil import Intents,recognize
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'phrases.yaml';update_phrases(p,{'events':['Red Sox vs Yankees','School concert (spring)']})
   value=json.loads(p.read_text()[len(MARKER):]);intents=Intents.from_dict(value)
   for text in ['are the Red Sox playing tomorrow','do the Yankees play today','tell me about Red Sox vs Yankees','when is School concert spring tomorrow']:
    self.assertIsNotNone(recognize(text,intents),text)
   self.assertLessEqual(len(value['lists']['pv_team']['values']),32)

 def test_tv_title_alias_and_tonight_are_recognized(self):
  from hassil import Intents,recognize
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'phrases.yaml';update_phrases(p,{'events':['Fire Country — New Episode','Boston Blue - New Episode','School concert']})
   value=json.loads(p.read_text(encoding='utf-8')[len(MARKER):]);intents=Intents.from_dict(value)
   for text in ('is Fire Country on tonight','what time is Fire Country tonight','when is Fire Country on tonight','is Boston Blue on tomorrow','when is School concert today'):
    self.assertIsNotNone(recognize(text,intents),text)
    self.assertTrue(planner.is_planner_question(text),text)
   self.assertIn('Fire Country',value['lists']['pv_calendar_event']['values'])
   self.assertIn('Fire Country New Episode',value['lists']['pv_calendar_event']['values'])
   update_phrases(p,{'events':[str(i)+' — New Episode' for i in range(50)]})
   self.assertLessEqual(len(json.loads(p.read_text(encoding='utf-8')[len(MARKER):])['lists']['pv_calendar_event']['values']),48)

 def test_playing_questions_use_saved_team_vocabulary(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'phrases.yaml';update_phrases(p,{'teams':['Boston Red Sox'],'events':['School concert']})
   value=json.loads(p.read_text()[len(MARKER):])
   self.assertIn('Red Sox',value['lists']['pv_team']['values'])
   sentences=value['intents']['PixoraPlanner']['data'][0]['sentences']
   self.assertIn('(is|are) [the] {pv_team} playing [today|tomorrow]',sentences)
   self.assertIn('School concert',value['lists']['pv_calendar_event']['values'])

 def test_owned_phrases_and_preserve_foreign_file(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'phrases.yaml';update_phrases(p,{'people':['Bryan','Amy','bad{slot}'],'teams':['Boston Bruins']})
   value=json.loads(p.read_text()[len(MARKER):]);self.assertIn('Amy',value['lists']['pv_person']['values']);self.assertIn('Bruins',value['lists']['pv_team']['values']);self.assertNotIn('bad{slot}',value['lists']['pv_person']['values'])
   update_phrases(p);self.assertFalse(p.exists());p.write_text('user content')
   with self.assertRaises(ValueError):update_phrases(p,{})
   self.assertEqual(p.read_text(),'user content')
 def test_atomic_settings(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'settings.json';write_owned(p,'{"enabled":true}');self.assertTrue(json.loads(p.read_text())['enabled'])
class BridgeTests(unittest.IsolatedAsyncioTestCase):
 async def test_red_sox_question_routes_to_planner_without_game_keyword(self):
  self.assertTrue(planner.is_planner_question('are the red sox playing tomorrow?'))
  self.assertTrue(planner.is_planner_question('Are the Boston Red Sox playing today?'))
  self.assertFalse(planner.is_planner_question('turn on the ceiling light'))
  self.assertFalse(planner.is_planner_question('is the front door open?'))
  self.assertTrue(planner.is_planner_question('Are the Kraken playing tomorrow?'))
  self.assertTrue(planner.is_planner_question('What time is the school concert tomorrow?'))

 async def test_connection_failure_speaks_and_cleans_pending(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'.storage').mkdir();(root/'.storage'/planner.SETTINGS).write_text('{"enabled":true}')
   def fail(*args):raise OSError('fixture connection failure')
   hass=NS(config=NS(path=lambda *p:str(root.joinpath(*p))),data={},bus=NS(async_fire=fail))
   self.assertIn("can't reach Planner",await planner.ask(hass,'calendar today'))
   self.assertEqual(hass.data[planner.DOMAIN]['planner_pending'],{})
 async def test_disabled_never_sends(self):
  with tempfile.TemporaryDirectory() as d:
   fired=[];hass=NS(config=NS(path=lambda *p:str(Path(d).joinpath(*p))),data={},bus=NS(async_fire=lambda *a:fired.append(a)))
   self.assertIn('off',await planner.ask(hass,'calendar today'));self.assertEqual(fired,[])
 async def test_reply_correlation_and_cleanup(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'.storage').mkdir();(root/'.storage'/planner.SETTINGS).write_text('{"enabled":true}')
   handlers={};hass=NS(config=NS(path=lambda *p:str(root.joinpath(*p))),data={},services=NS(has_service=lambda *a:False,async_register=lambda domain,name,handler,**kw:handlers.update({name:handler})))
   # The response enum is an HA runtime type; use a fixture in this isolated contract.
   import types
   with patch.dict(sys.modules,{'homeassistant.core':types.SimpleNamespace(SupportsResponse=NS(ONLY=1))}):planner.install_reply_service(hass)
   def fire(kind,data):
    async def reply():
     await handlers['planner_reply'](NS(data={'request_id':'wrong','speech':'wrong'}))
     await handlers['planner_reply'](NS(data={'request_id':data['request_id'],'speech':'Calendar answer'}))
    asyncio.create_task(reply())
   hass.bus=NS(async_fire=fire)
   self.assertEqual(await planner.ask(hass,'calendar today'),'Calendar answer');self.assertEqual(hass.data[planner.DOMAIN]['planner_pending'],{})
if __name__=='__main__':unittest.main()
