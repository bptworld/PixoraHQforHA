import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'pixora_voice'))
from app import install_component

class InstallTests(unittest.TestCase):
    def test_first_install_update_backup_and_other_integrations(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);config=root/'config';data=root/'data'
            unrelated=config/'custom_components/unrelated';unrelated.mkdir(parents=True);(unrelated/'__init__.py').write_text('untouched')
            install_component(config,data)
            target=config/'custom_components/pixora_voice'
            self.assertTrue((target/'engine.py').exists());(target/'version_marker').write_text('old')
            install_component(config,data)
            self.assertFalse((target/'version_marker').exists());self.assertEqual(len(list((data/'integration-backups').glob('*/version_marker'))),1)
            self.assertEqual((unrelated/'__init__.py').read_text(),'untouched')

    def test_unrecognized_existing_folder_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);target=root/'custom_components/pixora_voice';target.mkdir(parents=True);(target/'custom.txt').write_text('keep')
            with self.assertRaises(ValueError):install_component(root,root/'data')
            self.assertEqual((target/'custom.txt').read_text(),'keep')

if __name__=='__main__':unittest.main()
