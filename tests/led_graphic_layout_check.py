"""Layout bounds, imported league aliases, image lanes and unchanged timing."""
import hashlib, importlib.util, os, sys, urllib.request, urllib.error
from pathlib import Path
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
SOURCE=Path(os.environ.get('LED_CARD_SOURCE','D:/planner/.build-tmp/led-public-card-source/cards'))
os.chdir(SOURCE);sys.path[:0]=[str(ROOT/'pixora_led_displays'),str(SOURCE),str(SOURCE/'addons')]
from graphic_layout import install,text
import card_utils

def offline(*args,**kwargs):raise urllib.error.URLError('offline')
urllib.request.urlopen=offline
card_utils.warm_priority_graphic=lambda *args,**kwargs:None
card_utils.fetch_logo=lambda url,size=18,**kwargs: Image.new('RGBA',(size,size),(10,230,120,255)) if url else None

# Long strings must leave every pixel outside their assigned lane untouched.
for width in (64,128,192,256):
    for value in ('ALEXANDER VOLKANOVSKI','USD 12345.67','HAT TRICK','SEVERE THUNDERSTORM WARNING'):
        image=Image.new('RGB',(width,32));box=(20,7,width-3,14)
        text(image,value,box,size=12,name=True)
        bounds=image.getbbox();assert bounds is not None
        assert box[0]<=bounds[0]<bounds[2]<=box[2]+1 and box[1]<=bounds[1]<bounds[3]<=box[3]+1,(value,bounds,box)

cases={
 'cfl':('_render_score_animation_frames',['touchdown','field_goal','safety']),
 'mlb':('_render_run_animation_frames',['run','rbi','home_run','grand_slam','walk_off','now_batting','inning_start','inning_end']),
 'nhl':('_render_goal_animation_frames',['goal','hat_trick','win']),
 'soccer':('_render_goal_animation_frames',['goal','win','game_start']),
 'nba':('render_score_alert_frames',['three','bucket','free_throw','win','quarter_start']),
 'ufc':('_render_moment_animation_frames',['fight_start','round_start','knockout','submission','decision']),
 'launch_countdown':('_render_launch_animation_frames',['shake','liftoff']),
 'weather_alert':('_render_weather_alert_frames',['minor','moderate','severe','extreme','unknown']),
}
modules={};before={};hashes={}
for name,(renderer,kinds) in cases.items():
    path=SOURCE/'addons'/(name+'.py');hashes[path]=hashlib.sha256(path.read_bytes()).digest()
    spec=importlib.util.spec_from_file_location('layout_'+name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);modules[name]=module
    # Use solid asset fixtures to prove neither captions nor effects cover logos.
    for helper in (module,sys.modules.get('_sports_breaking')):
        if helper and hasattr(helper,'fetch_logo'):helper.fetch_logo=card_utils.fetch_logo
    if name=='ufc':
        module._fetch_headshot=lambda url,size:card_utils.fetch_logo(url,size)
        module._fetch_flag=lambda url,size:card_utils.fetch_logo(url,size)
    for width in (64,128,192,256):
        for kind in kinds:
            team={'_width':width,'_wall':width>=192,'_sport':{'nba':'basketball','soccer':'soccer','mlb':'baseball','nhl':'hockey','cfl':'football'}.get(name,name),
                  'abbreviation':'BOS','color':'000020','alternateColor':'FFFFFF','logo':'fixture',
                  'playerName':'ALEXANDER OVECHKIN','winnerName':'ALEXANDER VOLKANOVSKI',
                  'winnerHeadshot':'fixture','winnerFlag':'fixture','roundNumber':5,
                  'leftName':'ALEXANDER VOLKANOVSKI','rightName':'ISLAM MAKHACHEV','event':'Severe Thunderstorm Warning'}
            frames,timing=getattr(module,renderer)(team,kind)
            before[name,width,kind]=(team,len(frames),list(timing))

for module in modules.values():install(module)
for (name,width,kind),(team,count,timing) in before.items():
    frames,after=getattr(modules[name],cases[name][0])(team,kind)
    assert len(frames)==count and list(after)==timing,(name,width,kind,'timing changed')
    assert all(frame.size==(width,32) for frame in frames),(name,width,kind,'dimensions')
    if name=='cfl' and width==64:
        # Private, dynamically imported NFL renderer must receive the correction.
        assert frames[-1].getpixel((24,4))==(0,0,160),('CFL alias did not receive layout')
    if name=='ufc' and kind=='knockout':
        assert frames[-1].getpixel((5,12))==(10,230,120),('portrait covered')
    if name=='weather_alert' and width>=128:
        assert all(frames[-1].getpixel((x,30))==(1,3,7) for x in range(width)),('stale footer pixels')
for path,digest in hashes.items():assert hashlib.sha256(path.read_bytes()).digest()==digest,'Pinned card changed'
print(f'Layout checks passed: bounded long text, {len(before)} scene/profile timings, private league aliases, portrait lanes and pinned file hashes.')
