import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'pixora_voice'))
from app import install_component,prepare_integration_update,finish_integration_update,VERSION

class InstallTests(unittest.TestCase):
    def test_first_install_update_backup_and_other_integrations(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);config=root/'config';data=root/'data'
            unrelated=config/'custom_components/unrelated';unrelated.mkdir(parents=True);(unrelated/'__init__.py').write_text('untouched')
            install_component(config,data)
            target=config/'custom_components/pixora_voice'
            self.assertTrue((target/'phrase_tools.py').exists());self.assertTrue((target/'engine.py').exists());(target/'version_marker').write_text('old')
            install_component(config,data)
            self.assertFalse((target/'version_marker').exists());self.assertEqual(len(list((data/'integration-backups').glob('*/version_marker'))),1)
            self.assertEqual((unrelated/'__init__.py').read_text(),'untouched')

    def test_unrecognized_existing_folder_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);target=root/'custom_components/pixora_voice';target.mkdir(parents=True);(target/'custom.txt').write_text('keep')
            with self.assertRaises(ValueError):install_component(root,root/'data')
            self.assertEqual((target/'custom.txt').read_text(),'keep')

if __name__=='__main__':unittest.main()

class AutomaticUpdateTests(unittest.IsolatedAsyncioTestCase):
 async def test_update_copies_both_and_restarts_once(self):
  from unittest.mock import AsyncMock
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);config=root/'config';data=root/'data'
   install_component(config,data)
   manifest=config/'custom_components/pixora_voice/manifest.json'
   value=json.loads(manifest.read_text());value['version']='0.1.6';manifest.write_text(json.dumps(value))
   record=prepare_integration_update(config,data,root/'phrases.yaml')
   self.assertEqual(json.loads(manifest.read_text())['version'],VERSION)
   self.assertTrue((root/'phrases.yaml').exists())
   calls=[];loaded=False
   async def ha(path,body=None):
    nonlocal loaded
    if body is not None:
     calls.append((path,body))
     if path=='services/homeassistant/restart':loaded=True
     return []
    return [{'entity_id':'conversation.pixora_voice_beta','attributes':{'friendly_name':'Pixora Voice (Beta)','pixora_voice_version':VERSION if loaded else '0.1.6'}}]
   notice={}
   await finish_integration_update(record,config,data,ha,notice,sleep=AsyncMock())
   self.assertEqual([c[0] for c in calls],['services/homeassistant/restart','services/hassio/addon_restart'])
   self.assertIsNone(prepare_integration_update(config,data,root/'phrases.yaml'))
   self.assertFalse(notice['pending'])

 async def test_uncertain_restart_is_never_reissued(self):
  from unittest.mock import AsyncMock
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);record={'version':VERSION,'phase':'restart-requested','needRestart':True}
   ha=AsyncMock(return_value=[{'entity_id':'conversation.pixora_voice_beta','attributes':{'friendly_name':'Pixora Voice (Beta)'}}])
   notice={}
   await finish_integration_update(record,root,root,ha,notice,sleep=AsyncMock())
   self.assertTrue(all(call.args==('states',) for call in ha.await_args_list))
   self.assertIn('not repeated',notice['message'])

 async def test_foreign_install_is_preserved(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);manifest=root/'config/custom_components/pixora_voice/manifest.json';manifest.parent.mkdir(parents=True)
   manifest.write_text(json.dumps({'version':VERSION,'domain':'pixora_voice','codeowners':['someone else']}))
   before=manifest.read_text()
   with self.assertRaises(ValueError):prepare_integration_update(root/'config',root/'data')
   self.assertEqual(manifest.read_text(),before)

 async def test_first_install_needs_no_ha_restart(self):
  from unittest.mock import AsyncMock
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);record=prepare_integration_update(root/'config',root/'data');notice={};ha=AsyncMock(return_value=[])
   await finish_integration_update(record,root/'config',root/'data',ha,notice,sleep=AsyncMock())
   ha.assert_awaited_once_with('states')
   self.assertFalse(notice['pending'])

class AutomaticRecoveryTests(unittest.IsolatedAsyncioTestCase):
 async def test_copied_component_resumes_unfinished_phrases(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);config=root/'config';data=root/'data';install_component(config,data);data.mkdir(exist_ok=True)
   journal=data/'integration-update.json'
   journal.write_text(json.dumps({'version':VERSION,'phase':'prepared','needRestart':True,'speechNeeded':True}))
   phrases=root/'phrases.yaml'
   from planner_phrases import MARKER
   phrases.write_text(MARKER+'{}')
   record=prepare_integration_update(config,data,phrases)
   self.assertEqual(record['phase'],'installed')
   self.assertIn('PixoraVoiceLanguage',phrases.read_text())

 async def test_journal_failure_is_visible_and_sends_no_restart(self):
  from unittest.mock import AsyncMock,patch
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);ha=AsyncMock(return_value=[]);notice={'pending':True}
   with patch('planner_phrases.write_owned',side_effect=OSError('disk unavailable')):
    await finish_integration_update({'version':VERSION,'phase':'installed','needRestart':True},root,root,ha,notice,sleep=AsyncMock())
   self.assertFalse(notice['pending'])
   self.assertIn('paused',notice['message'])
   self.assertTrue(all(call.args==('states',) for call in ha.await_args_list))
