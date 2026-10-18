"""Render public special-graphic variants offline at both panel sizes and wall width."""
import ast,importlib.util,io,json,os,sys,urllib.error,urllib.request
from pathlib import Path
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
source=Path('D:/planner/.build-tmp/led-public-card-source/cards')
os.chdir(source);sys.path[:0]=[str(source),str(source/'addons'),str(ROOT/'pixora_led_displays')]
def offline(*args,**kwargs):raise urllib.error.URLError('Offline artwork audit')
urllib.request.urlopen=offline
import card_utils
card_utils.fetch_logo=lambda *args,**kwargs:None
card_utils.warm_priority_graphic=lambda *args,**kwargs:None
from card_worker import renderer_body,artwork
from special_graphics import tests_for,render_test
from graphic_layout import install

catalog=json.loads((ROOT/'pixora_led_displays/card_catalog.json').read_text(encoding='utf-8'))
rendered=0;aliases=0;seen=set();button_tests=0
for card in catalog['cards']:
    path=source/'addons'/(card['module']+'.py')
    text=path.read_text(encoding='utf-8-sig')
    if not tests_for(card) and not any(token in text for token in ('maybe_score_alert','_priority','_group_wall')):continue
    spec=importlib.util.spec_from_file_location('audit_'+card['module'],path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);install(module)
    import base64
    for key in tests_for(card):
        for width in (64,128,192):
            opts={o['key']:o.get('default','') for o in card.get('options',[])}
            opts.update({'_target':'matrixportal-s3-'+str(width)+'x32','favoriteTeam':'ALA',key:'group_wall' if width==192 else 'device'})
            try:result=render_test(module,card,key,opts,width)
            except Exception as exc:raise AssertionError((card['id'],key,width)) from exc
            with Image.open(io.BytesIO(base64.b64decode(result['body']))) as image:assert image.size==(width,32)
            assert result['once'] and result['duration']>0
            button_tests+=1
    names={name for name in ('_render_score_alert_frames','_render_score_animation_frames','_render_run_animation_frames','_render_goal_animation_frames') if callable(getattr(module,name,None))}
    # Every literal wall renderer referenced by a result must resolve on the card module.
    for node in ast.walk(ast.parse(text)):
        if isinstance(node,ast.keyword) and node.arg=='renderer_name' and isinstance(node.value,ast.Constant):names.add(node.value.value)
        if isinstance(node,ast.Dict):
            for key,value in zip(node.keys,node.values):
                if isinstance(key,ast.Constant) and key.value=='renderer' and isinstance(value,ast.Constant):
                    assert callable(getattr(module,value.value,None)),(card['id'],value.value)
                    names.add(value.value)
    for name in sorted(names):
        fn=getattr(module,name);aliases+=1
        identity=(str(Path(fn.__code__.co_filename).resolve()),fn.__name__)
        if identity in seen:continue
        seen.add(identity)
        origin=Path(fn.__code__.co_filename).stem
        if origin in ('nfl','ufl'):kinds=['touchdown','field_goal','safety','score','win']
        elif origin=='mlb':kinds=['run','home_run','grand_slam','rbi','walk_off','win','now_batting','inning_start','inning_end']
        elif origin=='ufc':kinds=['fight_start','round_start','round_end','knockout','submission','decision','win']
        elif origin=='weather_alert':kinds=['minor','moderate','severe','extreme','unknown']
        elif origin=='launch_countdown':kinds=['shake','liftoff']
        elif origin=='flight_track':kinds=['landing']
        else:kinds=['score','goal','bucket','three','free_throw','point','win','period_start','period_end','quarter_start','quarter_end','game_start','game_end','half_start','half_end']
        for width in (64,128,192):
            for kind in kinds:
                team={'_width':width,'abbreviation':'ALA','displayName':'Alabama','color':'9E1B32','alternateColor':'FFFFFF','destination':'Boston','event':'Severe Thunderstorm Warning','roundNumber':2,'winnerName':'Test Winner'}
                try:body,timing=renderer_body(module,{'renderer':name,'kind':kind,'team':team},width)
                except Exception as exc:raise AssertionError((card['id'],name,kind,width)) from exc
                normalized=artwork(body,width,timing,True)
                with Image.open(io.BytesIO(normalized)) as image:assert image.size==(width,32)
                rendered+=1
print(f'Graphic buttons passed: {button_tests} option/width tests.')
print(f'Special artwork passed: {aliases} card renderer aliases, {len(seen)} implementations, {rendered} variant/width renders; provider traffic blocked.')
