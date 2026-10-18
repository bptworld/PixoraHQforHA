"""Keep baseball/pitch/UFC backgrounds visible beside captions on multi-panel walls."""
import importlib.util,os,sys
from pathlib import Path
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[1]
SOURCE=Path('D:/planner/.build-tmp/led-public-card-source/cards')
os.chdir(SOURCE);sys.path[:0]=[str(ROOT/'pixora_led_displays'),str(SOURCE),str(SOURCE/'addons')]
import _sports_wall as wall
from graphic_layout import install
wall._fetch_logo=lambda url:Image.new('RGBA',(22,22),(210,30,160,255)) if url else None
wall._fetch_headshot=lambda url,size=24:Image.new('RGBA',(size,size),(30,210,160,255)) if url else None
install(wall)
checked=0
for width in (192,256):
    team={'_width':width,'_wall':True,'abbreviation':'BOS','logo':'fixture','color':'008348','alternateColor':'FFFFFF'}
    color=wall.hex_color(team['color']);alt=wall.readable_accent(color,wall.hex_color(team['alternateColor']))
    for kind in ('inning_start','inning_end'):
        frames,timing=wall.render_wall_score_frames(team,kind,sport='baseball')
        assert len(frames)==len(timing)==40
        for index,frame in enumerate(frames[20:],20):
            expected=Image.new('RGBA',(width,32));wall._draw_generic_arena_frame(expected,ImageDraw.Draw(expected),width,'baseball',index,color,alt)
            for x in (40,width-41):assert frame.getpixel((x,24))==expected.convert('RGB').getpixel((x,24)),(width,kind,index,'Baseball background erased')
            checked+=1
    for kind in ('win','wins','winner','final_win'):
        frames,timing=wall.render_wall_score_frames(team,kind,sport='soccer')
        assert len(frames)==len(timing)==48
        for index,frame in enumerate(frames[20:],20):
            expected=Image.new('RGBA',(width,32));wall._draw_full_soccer_pitch(ImageDraw.Draw(expected),width,index,color,alt)
            for x in (40,width-41):
                for y in (8,24):assert frame.getpixel((x,y))==expected.convert('RGB').getpixel((x,y)),(width,kind,index,'Full pitch erased')
            checked+=1
spec=importlib.util.spec_from_file_location('checked_ufc',SOURCE/'addons/ufc.py')
ufc=importlib.util.module_from_spec(spec);spec.loader.exec_module(ufc);install(ufc)
ufc._fetch_headshot=lambda url,size:Image.new('RGBA',(size,size),(30,210,160,255)) if url else None
ufc._fetch_flag=lambda url,size:Image.new('RGBA',(size,size),(210,30,160,255)) if url else None
for width in (64,128,192,256):
    for kind in ('knockout','submission','decision','win'):
        team={'_width':width,'_wall':True,'winnerName':'ALEXANDER VOLKANOVSKI','winnerHeadshot':'fixture','winnerFlag':'fixture'}
        frames,timing=ufc._render_moment_animation_frames(team,kind)
        assert len(frames)==18 and timing==[140]*18
        for index,frame in enumerate(frames):
            if width>=192:
                expected=(3,4,7) if index%2 else (18,1,5)
                for x in (28,width-29):assert frame.getpixel((x,20))==expected,(width,kind,index,'UFC backdrop erased')
            assert frame.getpixel((5,12))==(30,210,160),'Portrait changed'
            checked+=1
print(f'Additional sports backgrounds passed: {checked} caption-phase frames; inning starts/ends, full soccer pitch, UFC results, preserved portraits and timing.')
