"""Structured card events, cross-process history, timing and preview isolation."""
import base64
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from PIL import Image

WORKER=Path(__file__).resolve().parents[1]/'pixora_led_displays/card_worker.py'


with tempfile.TemporaryDirectory() as temp:
    root=Path(temp);(root/'addons').mkdir()
    (root/'addons/probe.py').write_text('''from PIL import Image
from datetime import datetime,timezone
import io
_SCORE_STATE={}
def frame(color,width=64):
 out=io.BytesIO();Image.new('RGB',(width,32),color).save(out,'PNG');return out.getvalue()
def celebration(team,kind):
 return [Image.new('RGB',(team['_width'],32),'blue'),Image.new('RGB',(team['_width'],32),'green')],[70,350]
def render(options):
 print('Card diagnostic output')
 if options.get('skip'):return None
 if options['_is_prefetch']:return {'body':frame('red',options['_width']),'dwell_secs':10}
 key=(options['_device_id'],'game');score=options.get('score',0);old=_SCORE_STATE.get(key)
 _SCORE_STATE[key]={'score':score,'seen':datetime.now(timezone.utc)}
 if old is not None and score>old['score']:
  return {'deviceGraphic':{'renderer':'celebration','kind':'goal','team':{}},'dwell_secs':6,'_priority':True,'_no_replay':True,'_stay':True,
   'wallGraphic':{'renderer':'celebration','kind':'goal','team':{}} if options.get('wall') else None}
 return frame('red',options['_width'])
''')
    request={'protocol':2,'root':str(root),'module':'probe','width':64,'dwell':10,'settings':{},'options':{'score':0},'device_id':'panel','events':True}
    def run(value):
        result=subprocess.run([sys.executable,str(WORKER)],input=json.dumps(value).encode(),capture_output=True,timeout=30)
        assert result.returncode==0,result.stderr.decode()
        return json.loads(result.stdout)
    baseline=run(request);assert baseline['event'] is None and baseline['state']
    # A new renderer process must remember the baseline score.
    request.update(event_state=baseline['state'],options={'score':1})
    scored=run(request);assert scored['event']['kind']=='goal' and scored['event']['once']
    assert scored['duration']==10, 'Event duration poisoned ordinary deck timing'
    with Image.open(io.BytesIO(base64.b64decode(scored['body']))) as normal:assert normal.convert('RGB').getpixel((0,0))==(255,0,0)
    with Image.open(io.BytesIO(base64.b64decode(scored['event']['body']))) as event:
        assert event.n_frames==2
        times=[]
        for i in range(2):event.seek(i);event.load();times.append(event.info['duration'])
        assert times==[70,350],times
    request['event_state']=scored['state']
    assert run(request)['event'] is None,'Celebration replayed after renderer restart'
    preview=run({**request,'events':False,'options':{'score':2}})
    assert preview['event'] is None and preview['state']=={},'Preview consumed event history'
    wall=run({**request,'wall_width':192,'options':{'score':2,'wall':True}})
    with Image.open(io.BytesIO(base64.b64decode(wall['event']['body']))) as image:assert image.size==(192,32)
    skipped=run({**request,'options':{'skip':True}});assert skipped['skip'] and skipped['body'] is None
    # Exercise the actual public NFL score-transition logic, replacing only provider/artwork I/O.
    source=Path('D:/planner/.build-tmp/led-public-card-source/cards')
    (root/'addons/probe.py').write_text("""import importlib.util,sys,io
+from PIL import Image
+sys.path[:0]=[SOURCE,SOURCE+'/addons']
+spec=importlib.util.spec_from_file_location('actual_nfl',SOURCE+'/addons/nfl.py');nfl=importlib.util.module_from_spec(spec);spec.loader.exec_module(nfl)
+_SCORE_STATE=nfl._SCORE_STATE
+def render(options):
+ out=io.BytesIO();Image.new('RGB',(64,32),'blue').save(out,'PNG');body=out.getvalue()
+ competitor={'score':str(options.get('score',0)),'team':{'abbreviation':'TEST','displayName':'Test Team'}}
+ event={'id':'test-game','competitions':[{'status':{'type':{'state':'in'}},'competitors':[competitor]}]}
+ nfl.fetch_sport_scoreboard=lambda *args,**kwargs:{'events':[event]}
+ nfl.pick_sport_event=lambda *args:event
+ nfl.animation_competitors=lambda *args:[competitor]
+ nfl._selected_competitor=lambda *args:competitor
+ nfl.game_moment_alert=lambda *args,**kwargs:None
+ nfl.warm_priority_graphic=lambda *args:None
+ nfl.cached_priority_graphic=lambda *args:body
+ nfl._latest_score_play=lambda *args:{}
+ nfl._classify_score_play=lambda *args:'touchdown'
+ nfl._scorer_for_play=lambda *args:{}
+ nfl.render_sport_card=lambda *args:body
+ return nfl.render(options)
+""".replace('SOURCE',repr(str(source).replace('\\','/'))).replace('\n+','\n'))
    real_request={**request,'event_state':{},'options':{'favoriteTeam':'TEST','score':0}}
    baseline=run(real_request);assert baseline['event'] is None
    real_request.update(event_state=baseline['state'],options={'favoriteTeam':'TEST','score':7})
    touchdown=run(real_request);assert touchdown['event'] is not None and touchdown['event']['once']
    real_request['event_state']=touchdown['state'];assert run(real_request)['event'] is None

print('Event worker passed: structured results, persistent typed history, no replay, clean regular cache, 70/350ms timing, preview isolation, wall canvas and intentional skips.')
