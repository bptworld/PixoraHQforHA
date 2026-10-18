"""Use the public NHL live-game detector with local cache and isolated processes."""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

APP=Path(__file__).resolve().parents[1]/'pixora_led_displays'
SOURCE=Path('D:/planner/.build-tmp/led-public-card-source/cards')
with tempfile.TemporaryDirectory() as folder:
    root=Path(folder);(root/'addons').mkdir()
    shutil.copy2(SOURCE/'card_utils.py',root/'card_utils.py')
    (root/'addons/live_probe.py').write_text('''import importlib.util,sys,io
from pathlib import Path
from PIL import Image
sys.path[:0]=[SOURCE,SOURCE+'/addons']
spec=importlib.util.spec_from_file_location('live_nhl',SOURCE+'/addons/nhl.py')
nhl=importlib.util.module_from_spec(spec);spec.loader.exec_module(nhl)
_GOAL_STATE=nhl._GOAL_STATE
def _render_goal_animation_frames(team,kind):
 with Path('wall-renders.txt').open('a') as log:log.write(kind+'\\n')
 return nhl._render_goal_animation_frames(team,kind)
def render(options):
 out=io.BytesIO();Image.new('RGB',(64,32),'red').save(out,'PNG');body=out.getvalue()
 competitor={'score':str(options.get('score',0)),'team':{'abbreviation':'BOS','displayName':'Boston Bruins','color':'FFB81C','alternateColor':'000000'}}
 event={'id':'live-game','competitions':[{'status':{'type':{'state':'in'}},'competitors':[competitor]}]}
 nhl.fetch_sport_scoreboard=lambda *args,**kwargs:{'events':[event]}
 nhl.pick_sport_event=lambda *args:event
 nhl.animation_competitors=lambda *args:[competitor]
 nhl._selected_competitor=lambda *args:competitor
 nhl.game_moment_alert=lambda *args,**kwargs:None
 nhl.render_sport_card=lambda *args,**kwargs:body
 return nhl.render(options)
'''.replace('SOURCE',repr(str(SOURCE))),encoding='utf-8')
    card={'id':'nhl','options':[{'key':'goalAnimationTarget','label':'Goal'}]}
    request={'protocol':2,'root':str(root),'module':'live_probe','width':64,'dwell':10,'settings':{},'options':{'favoriteTeam':'BOS','goalAnimationTarget':'group:pair','score':0},'device_id':'left','events':True,'graphic_cache':str(root/'cache'),'revision':'cards-v1','renderer':'app-v1','card_metadata':card,'wall_groups':{'pair':[['left',64],['right',128]]}}
    def run(value):
        result=subprocess.run([sys.executable,str(APP/'card_worker.py')],input=json.dumps(value).encode(),capture_output=True,timeout=30)
        assert result.returncode==0,result.stderr.decode()
        return json.loads(result.stdout)
    baseline=run(request)
    assert not baseline['event'] and (root/'wall-renders.txt').read_text().splitlines()==['goal']
    scored=run({**request,'event_state':baseline['state'],'options':{**request['options'],'score':1}})
    assert scored['event'] and scored['event']['kind']=='goal'
    assert baseline['warm_graphics'][0]['body']==scored['event']['body'],'Warmed output differs from the later goal artwork'
    assert (root/'wall-renders.txt').read_text().splitlines()==['goal'],'Actual NHL event rebuilt its warmed group scene'
    repeated=run({**request,'event_state':scored['state'],'options':{**request['options'],'score':1}})
    assert not repeated['event'],'Cache warming replayed the actual NHL score event'
print('Public NHL live-game warming passed: baseline warms wall; subsequent worker goal reuses it; score history prevents replay.')
