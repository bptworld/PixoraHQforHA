"""Generated voice phrases use literal list values, never executable templates."""
import sys,json,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'pixora_voice'))
from planner_phrases import update_voice_phrases,MARKER
from hassil import Intents,recognize
class FlowPhraseTests(unittest.TestCase):
 def test_real_recognition_and_bounds(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'flows.yaml';update_voice_phrases(path,['Good night','Movie time!'])
   intents=Intents.from_dict(json.loads(path.read_text().removeprefix(MARKER)))
   self.assertIsNotNone(recognize('good night',intents));self.assertIsNone(recognize('not good night',intents))
   for values in (['{anything}'],['x']*65,['!!!']):
    with self.assertRaises(ValueError):update_voice_phrases(path,values)
   update_voice_phrases(path,[]);self.assertEqual(json.loads(path.read_text().removeprefix(MARKER))['intents'],{})
 def test_foreign_file_preserved(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'flows.yaml';path.write_text('user data')
   with self.assertRaises(ValueError):update_voice_phrases(path,['Good night'])
   self.assertEqual(path.read_text(),'user data')
if __name__=='__main__':unittest.main()

class FlowRefreshServiceTests(unittest.IsolatedAsyncioTestCase):
 async def test_refresh_writes_once_then_requests_one_restart(self):
  import types,importlib
  from unittest.mock import AsyncMock,patch
  flows=importlib.import_module('custom_components.pixora_voice.flows')
  tools=types.ModuleType('custom_components.pixora_voice.phrase_tools')
  writes=[];tools.update_voice_phrases=lambda *args:writes.append(('phrases',args))
  tools.write_owned=lambda *args:writes.append(('names',args))
  core=types.ModuleType('homeassistant.core');core.SupportsResponse=types.SimpleNamespace(ONLY='only')
  handlers={}
  services=types.SimpleNamespace(has_service=lambda *args:False,async_register=lambda domain,name,fn,**kw:handlers.update({name:fn}),async_call=AsyncMock())
  hass=types.SimpleNamespace(data={},services=services,config=types.SimpleNamespace(path=lambda *parts:str(Path('D:/planner/.build-tmp')/Path(*parts))))
  with patch.dict(sys.modules,{'homeassistant.core':core,'custom_components.pixora_voice.phrase_tools':tools}),patch.object(flows,'ask',AsyncMock(return_value=json.dumps({'phrases':['Good night'],'variables':['isDark']}))):
   flows.install_services(hass)
   await handlers['refresh_flow_phrases'](types.SimpleNamespace(data={'phrases':['Good night'],'variables':['isDark']}))
   flows.ask.assert_not_awaited()
   self.assertEqual(len(writes),2)
   services.async_call.assert_awaited_once_with('hassio','addon_restart',{'addon':'core_speech-to-phrase'},blocking=True)
   self.assertFalse(hass.data['pixora_voice']['flow_refresh_busy'])
   hass.auth=types.SimpleNamespace(async_get_user=AsyncMock(return_value=types.SimpleNamespace(is_admin=False)))
   with self.assertRaises(flows.HomeAssistantError):
    await handlers['refresh_flow_phrases'](types.SimpleNamespace(context=types.SimpleNamespace(user_id='reader'),data={'phrases':['Good night'],'variables':[]}))
   self.assertEqual(len(writes),2)
   self.assertEqual(services.async_call.await_count,1)
