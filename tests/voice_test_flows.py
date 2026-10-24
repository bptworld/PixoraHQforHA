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
