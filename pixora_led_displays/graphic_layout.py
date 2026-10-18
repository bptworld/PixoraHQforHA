"""Pixel-measured layouts for locally rendered priority graphics.

Installed after card imports so pinned, checksum-verified downloads stay intact.
The same functions serve event delivery, warming and the Test buttons.
"""
from functools import lru_cache
import sys
from types import ModuleType
from PIL import Image, ImageDraw, ImageFont


@lru_cache(maxsize=24)
def font(size):
    try:return ImageFont.truetype('assets/fonts/PixelifySans-Bold.ttf', size)
    except OSError:return ImageFont.load_default(size=size)


def text(image, value, box, color='white', size=10, name=False):
    """Place actual glyph ink inside an inclusive box, never a font baseline."""
    value=str(value or '').strip().upper()
    x0,y0,x1,y1=box
    width,height=x1-x0+1,y1-y0+1
    if not value or width<1 or height<1:return
    candidates=[value]
    if name and len(value.split())>1:
        parts=value.split();candidates += [parts[0][0]+'. '+parts[-1],parts[-1]]
    chosen=None
    for candidate in candidates:
        for pixels in range(size,5,-1):
            face=font(pixels);bounds=face.getbbox(candidate)
            if bounds[2]-bounds[0]<=width and bounds[3]-bounds[1]<=height:
                chosen=(candidate,face,bounds);break
        if chosen:break
    if not chosen:
        face=font(6);candidate=candidates[-1]
        while candidate and face.getbbox(candidate+'..')[2]>width:candidate=candidate[:-1]
        if not candidate:return
        chosen=(candidate+'..',face,face.getbbox(candidate+'..'))
    candidate,face,bounds=chosen
    # A 1-bit mask keeps glyphs crisp on the physical LED grid.
    mask=Image.new('1',(width,height));draw=ImageDraw.Draw(mask)
    draw.text(((width-(bounds[2]-bounds[0]))//2-bounds[0],
               (height-(bounds[3]-bounds[1]))//2-bounds[1]),candidate,font=face,fill=1)
    image.paste(color,(x0,y0,x1+1,y1+1),mask)


def panel(image, lines, left, right, color, accent='white'):
    if isinstance(color,tuple) and max(color[:3])<130:
        peak=max(color[:3]);color=tuple(min(255,int(c*160/max(1,peak))) for c in color[:3]) if peak else (180,180,180)
    ImageDraw.Draw(image).rectangle((left,4,right,28),fill=(2,8,12),outline=color)
    text(image,lines[0],(left+2,7,right-2,14),accent,12)
    text(image,lines[1],(left+2,18,right-2,25),color,10)


def paste_asset(image, asset, x, y):
    if asset is not None:image.paste(asset,(x,y),asset if asset.mode=='RGBA' else None)


_replacements={}


def install(selected):
    """Rebind imported aliases too; several league cards share helper functions."""
    def replace(module,name,replacement):
        original=getattr(module,name,None)
        if original and original not in _replacements.values():
            _replacements[original]=replacement
            setattr(module,name,replacement)

    breaking=sys.modules.get('_sports_breaking')
    if breaking and not getattr(breaking,'_local_layout',False):
        breaking._local_layout=True
        def scene(team,kind,timing=False):
            width=int(team.get('_width',64));sport=team.get('_sport','score')
            color=breaking._hex_color(team.get('color'),(117,231,214))
            alt=breaking._hex_color(team.get('alternateColor'),(245,250,255))
            lines=breaking._timing_text(kind,sport) if timing else breaking._sport_scene_label(kind,sport)
            if kind in ('win','wins','winner','final_win'):lines=('WINS',team.get('abbreviation','TEAM'))
            frames=[];durations=[]
            count=10 if timing else 16
            logo=breaking.fetch_logo(team.get('logo'),size=18) if team.get('logo') else None
            for step in range(count):
                image=Image.new('RGB',(width,32));draw=ImageDraw.Draw(image)
                breaking._draw_timing_surface(draw,width,step,color,sport)
                paste_asset(image,logo,2,7)
                if logo is None:text(image,team.get('abbreviation','TEAM'),(1,10,20,21),alt,8)
                if not timing:
                    t=min(1,step/9);mark_x=int(24+(width-34)*t)
                    mark_y=int(24-(10 if sport in ('basketball','volleyball') else 5)*(1-abs(t*2-1)))
                    breaking._draw_device_sport_mark(draw,sport,mark_x,mark_y,color,alt,step)
                if timing or step>=6:
                    left=24 if width==64 else max(26,(width-64)//2)
                    right=width-2 if width==64 else min(width-3,left+63)
                    panel(image,lines,left,right,color,alt)
                frames.append(image);durations.append((130 if step%2==0 else 90) if timing else (80 if step<10 else 130))
            return frames,durations
        replace(breaking,'_render_sport_scene_device_frames',lambda team,kind:scene(team,kind))
        replace(breaking,'_render_sport_timing_device_frames',lambda team,kind:scene(team,kind,True))
        replace(breaking,'_render_soccer_timing_device_frames',lambda team,kind:scene(team,kind,True))
        def player_goal(image,draw,team,kind,step,width,color,alt,small,big):
            if not team.get('playerName') or kind not in ('goal','hat_trick'):return False
            # Reserve separate portrait, caption and badge lanes, including at 64px.
            draw.rectangle((0,3,width-1,29),fill=(2,8,12))
            head=breaking.fetch_logo(team.get('playerHeadshot'),size=16 if width==64 else 22)
            badge=breaking.fetch_logo(team.get('playerLogo') or team.get('logo'),size=18) if width>64 else None
            paste_asset(image,head,1,8 if width==64 else 5)
            paste_asset(image,badge,width-(12 if width==64 else 20),10 if width==64 else 7)
            left,right=(19,62) if width==64 else (27,width-24)
            if width==64 and kind=='hat_trick':
                draw.rectangle((left,3,right,29),fill=(2,8,12),outline=color)
                text(image,str(team['playerName']).split()[-1],(left+2,5,right-2,10),alt,8)
                text(image,'HAT',(left+2,14,right-2,19),color,8)
                text(image,'TRICK',(left+2,23,right-2,27),color,8)
            else:panel(image,(str(team['playerName']).split()[-1], 'HAT TRICK' if kind=='hat_trick' else 'GOAL'),left,right,color,alt)
            return True
        replace(breaking,'_draw_player_goal_device_frame',player_goal)
        original_soccer_win=breaking._render_soccer_win_device_frames
        def soccer_win(team):
            frames,durations=original_soccer_win(team)
            color=breaking._hex_color(team.get('color'),(70,220,125))
            alt=breaking._hex_color(team.get('alternateColor'),(245,250,255))
            for step,image in enumerate(frames[9:]):
                width=image.width;draw=ImageDraw.Draw(image)
                draw.rectangle((0,0,width-1,31),fill=(0,15,10))
                breaking._draw_soccer_trophy(draw,3 if width==64 else width-24,4,color,alt,step)
                if width>64:paste_asset(image,breaking.fetch_logo(team.get('logo'),size=22),2,5)
                panel(image,('WINS',team.get('abbreviation','TEAM')),24 if width==64 else 29,width-2 if width==64 else width-28,color,alt)
            return frames,durations
        replace(breaking,'_render_soccer_win_device_frames',soccer_win)

    wall=sys.modules.get('_sports_wall')
    if wall and not getattr(wall,'_local_layout',False):
        wall._local_layout=True
        original_sharp=wall.draw_sharp_text
        def wall_text(image,xy,value,*args,**kwargs):
            # These decorative words were painted over the scorer's face and
            # team badge. The ball trail and fireworks already convey impact.
            if value in ('CRACK','BOOM'):return
            return original_sharp(image,xy,value,*args,**kwargs)
        wall.draw_sharp_text=wall_text
        original_baseball=wall._render_baseball_wall_frames
        def baseball_frames(team,kind='run',default_label='MLB'):
            frames,durations=original_baseball(team,kind,default_label)
            if team.get('playerHeadshot') or kind in ('home_run','grand_slam'):
                color=wall.hex_color(team.get('color'))
                alt=wall.readable_accent(color,wall.hex_color(team.get('alternateColor'),(255,255,255)))
                for phase,source in enumerate(frames):
                    image=source.convert('RGBA')
                    draw=ImageDraw.Draw(image)
                    draw.rectangle((0,3,26,29),fill=(2,8,12))
                    draw.rectangle((image.width-27,3,image.width-1,29),fill=(2,8,12))
                    wall._draw_scoring_edges(image,draw,team,color,alt,phase,default_label)
                    frames[phase]=image.convert('RGB')
            return frames,durations
        replace(wall,'_render_baseball_wall_frames',baseball_frames)
        def baseball_text(image,draw,width,headline,phase,color,alt,reveal=1,kind='run'):
            lane=124 if width>=256 else max(28,width-132) if width>=192 else width-58
            left=(width-lane)//2
            # Player plate owns rows 18-30; portraits own the outer lanes.
            draw.rectangle((left-2,2,left+lane+1,17),fill=(2,8,12))
            text(image,headline,(left,4,left+lane-1,15),alt,16)
        replace(wall,'_draw_baseball_wall_text',baseball_text)
        original=wall.render_wall_score_frames
        def wall_frames(team,kind='score',*args,**kwargs):
            result=original(team,kind,*args,**kwargs)
            sport=kwargs.get('sport') or team.get('_sport','score')
            frames,durations=result[:2];width=int(team.get('_width',64))
            if sport=='baseball':
                if kind in ('inning_start','inning_end'):
                    color=wall.hex_color(team.get('color'),(117,231,214))
                    alt=wall.readable_accent(color,wall.hex_color(team.get('alternateColor'),(255,255,255)))
                    for index,image in enumerate(frames[20:],20):
                        arena=Image.new('RGBA',(width,32),(0,0,0,255))
                        wall._draw_generic_arena_frame(arena,ImageDraw.Draw(arena),width,sport,index,color,alt)
                        image.paste(arena.crop((27,3,width-27,30)).convert('RGB'),(27,3))
                        panel(image,('START' if kind=='inning_start' else 'END','INNING'),max(28,width//2-30),min(width-29,width//2+30),(255,210,100))
                return frames,durations
            if width<192:return result
            # Preserve the flight/impact sequence. Caption reveal follows it.
            if kind not in ('goal','hat_trick','win','wins','winner','final_win'):return result
            color=wall.hex_color(team.get('color'),(117,231,214)) if hasattr(wall,'hex_color') else (117,231,214)
            alt=wall.readable_accent(color,wall.hex_color(team.get('alternateColor'),(255,255,255)))
            for index,image in enumerate(frames):
                if index<20:continue
                # Erase the original caption with the arena, not a wall-wide dark
                # rectangle. Only the replacement caption panel should hide it.
                arena=Image.new('RGBA',(width,32),(0,0,0,255))
                if sport=='soccer' and kind in ('win','wins','winner','final_win'):
                    wall._draw_full_soccer_pitch(ImageDraw.Draw(arena),width,index,color,alt)
                else:
                    wall._draw_generic_arena_frame(arena,ImageDraw.Draw(arena),width,sport,index,color,alt)
                image.paste(arena.crop((27,3,width-27,30)).convert('RGB'),(27,3))
                lane=124 if width>=256 else 60;left=(width-lane)//2
                name=str(team.get('playerName') or '').split()
                lines=(name[-1], 'HAT TRICK' if kind=='hat_trick' else 'GOAL') if name and kind in ('goal','hat_trick') else ('WINS',team.get('abbreviation','TEAM'))
                panel(image,lines,left-2,left+lane+1,color)
            return frames,durations
        replace(wall,'render_wall_score_frames',wall_frames)

    # Selected modules are intentionally not registered in sys.modules by the worker.
    modules=[selected]+[m for m in list(sys.modules.values()) if m and getattr(m,'__file__','') and '/addons/' in str(m.__file__).replace('\\','/')]
    for module in modules:
        for value in list(vars(module).values()):
            if isinstance(value,ModuleType) and '/addons/' in str(getattr(value,'__file__','')).replace('\\','/') and value not in modules:modules.append(value)
    for module in modules:
        for name,value in list(vars(module).items()):
            if callable(value):
                replacement=_replacements.get(value)
                if replacement:setattr(module,name,replacement)
    for module in modules:_install_card(module)
    for module in modules:
        for name,value in list(vars(module).items()):
            if callable(value) and value in _replacements:setattr(module,name,_replacements[value])


def _install_card(module):
    if getattr(module,'_local_card_layout',False):return
    module._local_card_layout=True
    if hasattr(module,'_draw_uprights') and hasattr(module,'_render_score_animation_frames'):
        original_score=module._render_score_animation_frames
        def football(team,kind='touchdown'):
            result=original_score(team,kind)
            if team.get('_wall') or kind not in ('touchdown','field_goal','safety','score'):return result
            frames,durations=result[:2]
            for image in frames[6:]:
                width=image.width
                ImageDraw.Draw(image).rectangle((23,0,width-1,31),fill=(2,8,12))
                lines={'touchdown':('TOUCH','DOWN'),'field_goal':('FIELD','GOAL'),'safety':('SAFETY',''),'score':('SCORE','')}
                panel(image,lines[kind],24,width-2,module._hex_color(team.get('color'),(120,220,255)))
            return frames,durations
        module._render_score_animation_frames=football
        # Other league modules import the original function by reference.
        _replacements[original_score]=football
    if hasattr(module,'_draw_winner_text'):
        def winner(image,draw,winner_name,moment_label,width,color,alt,phase,headshot_url='',flag_url=''):
            if width>=192:
                draw.rectangle((1,3,width-2,28),outline=color)
                draw.rectangle(((width-124)//2,3,(width+124)//2-1,28),fill=(5,5,8),outline=color)
            else:draw.rectangle((1,3,width-2,28),fill=(5,5,8),outline=color)
            size=12 if width==64 else 24
            head=module._fetch_headshot(headshot_url,size)
            # At 64px the portrait is more useful than a second image squeezing
            # the fighter's name down to an unreadable strip.
            flag=module._fetch_flag(flag_url,size) if width>64 else None
            paste_asset(image,head,2,(32-size)//2);paste_asset(image,flag,width-size-2,(32-size)//2)
            left=size+4 if head else 4;right=width-size-5 if flag else width-3
            if width>=192:left=max(left,(width-124)//2);right=min(right,(width+124)//2-1)
            text(image,winner_name,(left,6,right,14),alt,12,name=True)
            text(image,moment_label,(left,19,right,25),color,10)
        module._draw_winner_text=winner
        def matchup(team,kind='round_start'):
            width=module._animation_width(team);image=Image.new('RGB',(width,32),(4,5,8))
            left,right=(1,width-2) if width==64 else ((width-124)//2,(width+124)//2-1) if width>=192 else (27,width-28)
            if width>64:
                for key,x in [('leftHeadshot',1),('rightHeadshot',width-25)]:
                    head=module._fetch_headshot(team.get(key),24) if team.get(key) else None
                    paste_asset(image,head,x,7)
                    if head is None:
                        draw=ImageDraw.Draw(image)
                        draw.ellipse((x+8,9,x+16,17),fill=(100,110,125))
                        draw.ellipse((x+3,18,x+21,35),fill=(65,75,90))
            header='FIGHT START' if kind=='fight_start' else module._round_label(kind,team.get('roundNumber'))
            text(image,header,(left,0,right,5),(255,110,110),8)
            text(image,team.get('leftName','PEREIRA'),(left,8,right,14),'white',9,name=True)
            text(image,'VS',(left,16,right,20),(255,195,70),6)
            text(image,team.get('rightName','HILL'),(left,23,right,30),'white',9,name=True)
            return image
        module._render_round_matchup_frame=matchup
    if hasattr(module,'_draw_mlb_player_moment_layout'):
        def player(image,draw,*,label,name,stat_lines,text_left,text_width,color,width):
            right=min(width-2,text_left+text_width-1)
            draw.rectangle((text_left,0,right,31),fill=(2,8,12))
            text(image,label,(text_left,0,right,5),color,8)
            text(image,name,(text_left,8,right,15),'white',11,name=True)
            rows=[(19,23),(26,30)] if len(stat_lines)>1 else [(21,28)]
            for value,(top,bottom) in zip(stat_lines,rows):text(image,value,(text_left,top,right,bottom),'white',8)
        module._draw_mlb_player_moment_layout=player
        def home_run(image,draw,team,kind,color,alt,show_player=True):
            width=image.width
            left=2 if width==64 or not team.get('playerHeadshot') else 27
            right=width-3 if width==64 else width-27
            draw.rectangle((left,2,right,28),fill=(2,8,12))
            name=str(team.get('playerName') or '').split()
            if show_player and name:
                text(image,name[-1],(left,4,right,11),'white',9)
                text(image,module._home_run_headline(kind),(left,18,right,25),color,10)
            else:text(image,module._home_run_headline(kind),(left,10,right,21),color,12)
        module._draw_home_run_middle_text=home_run
        original_run=module._render_run_animation_frames
        def runs(team,kind='run'):
            result=original_run(team,kind)
            if team.get('_wall') or kind not in ('run','rbi','walk_off','win'):return result
            frames,durations=result[:2]
            lines={'run':('RUN','SCORED'),'rbi':('RUN','SCORED'),'walk_off':('WALK','OFF'),'win':('GAME','WIN')}
            color=module._hex_color(team.get('color'),(255,200,80))
            for image in frames[20:]:
                width=image.width
                ImageDraw.Draw(image).rectangle((24,0,width-1,31),fill=(2,8,12))
                panel(image,lines[kind],24 if width==64 else 29,width-2 if width==64 else width-27,color)
            return frames,durations
        module._render_run_animation_frames=runs
        _replacements[original_run]=runs
    if hasattr(module,'_render_weather_alert_frames'):
        original_weather=module._render_weather_alert_frames
        def weather(team,kind):
            frames,durations=original_weather(team,kind)
            severity=module._severity_key(team.get('severity') or kind)
            label='WEATHER' if severity=='unknown' else severity.upper()
            for image in frames:
                width=image.width;draw=ImageDraw.Draw(image)
                draw.rectangle((0,0,width-1,6),fill=(24,12,20))
                text(image,label,(1,0,width-2,5),'white',8)
                if width>=128:
                    draw.rectangle((0,9,width-30,31),fill=(1,3,7))
                    # The source footer's baseline extends below its old lane.
                    # Clear those remnants without touching the warning icon.
                    draw.rectangle((0,26,width-1,31),fill=(1,3,7))
                    words=str(team.get('event') or 'WEATHER ALERT').upper().split()
                    if width==128:
                        tail=words.pop() if words else 'ALERT'
                        heading=' '.join(words).replace('THUNDERSTORM','TSTM')
                        text(image,heading,(2,10,width-32,17),'white',9)
                        text(image,tail,(2,21,width-32,27),(255,210,100),9)
                    else:
                        text(image,' '.join(words),(3,10,width-32,18),'white',10)
                        text(image,'TAKE ACTION',(3,22,width-32,27),(255,210,100),8)
            return frames,durations
        module._render_weather_alert_frames=weather
    if hasattr(module,'_draw_alert'):
        def alert(title,line1,line2='',width=None,color=(255,190,90)):
            width=width or getattr(module,'_local_render_width',64)
            image=Image.new('RGB',(width,32),(2,8,12))
            text(image,title,(1,0,width-2,6),color,9)
            text(image,line1,(1,10,width-2,17),'white',10)
            detail=str(line2).replace('INTERNATIONAL','INTL')
            if width==64 and detail.endswith(' INTL'):detail=detail[:-5]
            text(image,detail,(1,23,width-2,30),color,9)
            return image
        module._draw_alert=alert
    if hasattr(module,'_new_order_animation'):
        original=module._new_order_animation
        def order(data,opts):
            body=original(data,opts)
            import io
            from PIL import ImageSequence
            with Image.open(io.BytesIO(body)) as source:
                frames=[];durations=[]
                for frame in ImageSequence.Iterator(source):
                    frame.load()
                    width=frame.width;image=Image.new('RGB',(width,32),(2,8,12))
                    color=(255,200,80) if len(frames)%2==0 else (190,130,40)
                    ImageDraw.Draw(image).rectangle((0,0,width-1,31),outline=color)
                    text(image,'NEW ORDER',(2,3,width-3,11),color,11)
                    text(image,str(data.get('newest_currency','USD'))+' '+format(float(data.get('newest_total',0)),'.2f'),(2,19,width-3,28),'white',11)
                    frames.append(image);durations.append(frame.info.get('duration',100))
            output=io.BytesIO();frames[0].save(output,'WEBP',save_all=True,append_images=frames[1:],duration=durations,loop=1,lossless=True)
            return output.getvalue()
        module._new_order_animation=order
    if hasattr(module,'_liftoff_frames'):
        original=module._liftoff_frames
        def liftoff(*args,**kwargs):
            frames,durations=original(*args,**kwargs)
            for image in frames[-4:]:
                text(image,'LIFTOFF',(3,10,image.width-4,21),(255,210,80),16)
            return frames,durations
        module._liftoff_frames=liftoff
