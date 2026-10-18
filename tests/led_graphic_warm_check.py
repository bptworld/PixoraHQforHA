"""Cross-process priority warming, wall reuse, freshness and scorer isolation."""
import base64
import io
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from PIL import Image

APP=Path(__file__).resolve().parents[1]/'pixora_led_displays'
sys.path.insert(0,str(APP))
from graphic_cache import GraphicCache

with tempfile.TemporaryDirectory() as folder:
    root=Path(folder);(root/'addons').mkdir()
    (root/'card_utils.py').write_text('''def fetch_json_request(url,seconds=600):return {'score':1}
def warm_priority_graphic(key,render):return render()
def cached_priority_graphic(key,render):return render()
''',encoding='utf-8')
    (root/'addons/probe.py').write_text('''from PIL import Image
from pathlib import Path
import io
from card_utils import warm_priority_graphic,cached_priority_graphic
_SCORE_STATE={}
def body(color):
 out=io.BytesIO();Image.new('RGB',(64,32),color).save(out,'PNG');return out.getvalue()
def _render_goal_animation_frames(team,kind):
 assert team['_wall']
 with Path('renders.txt').open('a') as log:log.write(kind+' '+str(team['_width'])+' '+str(team.get('playerName',''))+'\\n')
 return [Image.new('RGB',(team['_width'],32),'blue'),Image.new('RGB',(team['_width'],32),'green')],[70,350]
def render(options):
 if options['_is_prefetch']:return body('red')
 team={'abbreviation':'BOS','_width':64}
 warm_priority_graphic('bos-goal',lambda team=team: body('blue'))
 old=_SCORE_STATE.get('score',0);score=options.get('score',0);_SCORE_STATE['score']=score
 if score>old:
  if options.get('playerName'):team['playerName']=options['playerName']
  return {'wallGraphic':{'renderer':'_render_goal_animation_frames','kind':'goal','team':team},'dwell_secs':6}
 return body('red')
''',encoding='utf-8')
    card={'id':'nhl','options':[{'key':'goalAnimationTarget','label':'Goal'}]}
    request={'protocol':2,'root':str(root),'module':'probe','width':64,'dwell':10,'settings':{},'options':{'goalAnimationTarget':'group:pair','score':0},'device_id':'left','events':True,'graphic_cache':str(root/'cache'),'revision':'cards-v1','renderer':'app-v1','card_metadata':card,'wall_groups':{'pair':[['left',64],['right',128]]}}
    def run(value):
        result=subprocess.run([sys.executable,str(APP/'card_worker.py')],input=json.dumps(value).encode(),capture_output=True,timeout=30)
        assert result.returncode==0,result.stderr.decode()
        return json.loads(result.stdout)
    baseline=run(request)
    assert baseline['event'] is None
    assert (root/'renders.txt').read_text().splitlines()==['goal 192 ']
    again=run({**request,'event_state':baseline['state']})
    assert (root/'renders.txt').read_text().splitlines()==['goal 192 '],'Warm wall was rebuilt in a new worker'
    scored=run({**request,'event_state':again['state'],'options':{**request['options'],'score':1}})
    assert scored['event']['wall_members']==[['left',64],['right',128]]
    assert len((root/'renders.txt').read_text().splitlines())==1,'Real goal did not reuse the warmed wall'
    with Image.open(io.BytesIO(base64.b64decode(scored['event']['body']))) as image:
        assert image.size==(192,32) and image.n_frames==2
        timing=[]
        for i in range(2):image.seek(i);image.load();timing.append(image.info['duration'])
        assert timing==[70,350],timing
    assert run({**request,'event_state':scored['state'],'options':{**request['options'],'score':1}})['event'] is None
    fresh=run({**request,'event_state':scored['state'],'options':{**request['options'],'score':2,'playerName':'New scorer'}})
    assert fresh['event'] and len((root/'renders.txt').read_text().splitlines())==2,'New scorer incorrectly reused old artwork'
    cache=GraphicCache(root/'unit','v1');calls=[]
    utils=SimpleNamespace(fetch_json_request=lambda url,seconds=600:(calls.append(url) or {'score':len(calls)}))
    cache.install(utils)
    assert utils.fetch_json_request('scoreboard',seconds=15)==utils.fetch_json_request('scoreboard',seconds=15)
    assert len(calls)==1
    path=cache.path('provider-json','scoreboard');os.utime(path,(time.time()-16,time.time()-16))
    assert utils.fetch_json_request('scoreboard',seconds=15)['score']==2,'Scoreboard TTL was extended'
    def missing_image():cache.asset_failures+=1;return b'fallback'
    assert utils.cached_priority_graphic('missing-logo',missing_image)==b'fallback'
    assert cache.get('priority','missing-logo') is None,'A failed logo fallback was cached as complete artwork'
    cache.put('priority','team',b'art')
    assert GraphicCache(root/'unit','v2').get('priority','team') is None,'Revision failed to invalidate artwork'
    os.utime(cache.path('priority','team'),(time.time()-901,time.time()-901))
    assert cache.get('priority','team') is None
    cache.put('priority','corrupt',b'original')
    cache.path('priority','corrupt').write_bytes(b'corrupted partial write')
    assert cache.get('priority','corrupt') is None,'Corrupted cached artwork was reused'
    for i in range(260):cache.put('bounded',i,b'a')
    assert len(list(cache.root.glob('*.cache')))<=256

print('Graphic warm cache passed: cross-process wall reuse, 70/350ms timing, no replay, fresh scorer, provider TTL, revision/expiry and bounded storage.')
