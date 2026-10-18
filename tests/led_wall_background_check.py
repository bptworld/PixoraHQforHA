"""Caption reveal must preserve arena pixels outside its box and keep timing/assets."""
import importlib.util,json,os,subprocess,sys,tempfile
from pathlib import Path
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[1]
SOURCE=Path('D:/planner/.build-tmp/led-public-card-source/cards')

def render(layout,folder):
    os.chdir(SOURCE);sys.path[:0]=[str(ROOT/'pixora_led_displays'),str(SOURCE),str(SOURCE/'addons')]
    import _sports_wall as wall
    wall._fetch_logo=lambda url:Image.new('RGBA',(22,22),(220,20,120,255))
    wall._fetch_headshot=lambda url,size=24:Image.new('RGBA',(size,size),(20,220,120,255)) if url else None
    spec=importlib.util.spec_from_file_location('checked_layout',layout)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);module.install(wall)
    rows=[]
    for sport,kind in [('basketball','win'),('football','win'),('football','touchdown'),('hockey','goal'),('soccer','goal')]:
        for width in (64,128,192,256):
            team={'_width':width,'_wall':True,'_sport':sport,'abbreviation':'BOS','color':'008348','alternateColor':'FFFFFF','logo':'fixture'}
            frames,durations=wall.render_wall_score_frames(team,kind,sport=sport)
            key=f'{sport}-{kind}-{width}'
            for i,frame in enumerate(frames):frame.save(folder/f'{key}-{i}.png')
            rows.append({'key':key,'sport':sport,'kind':kind,'width':width,'count':len(frames),'durations':durations})
    (folder/'index.json').write_text(json.dumps(rows))

if len(sys.argv)>1:
    render(Path(sys.argv[1]),Path(sys.argv[2]));sys.exit()

with tempfile.TemporaryDirectory() as temp:
    root=Path(temp);old=root/'before';new=root/'after';old.mkdir();new.mkdir()
    baseline=root/'baseline.py'
    baseline.write_bytes(subprocess.check_output(['git','-C',str(ROOT),'show','5ffd963:pixora_led_displays/graphic_layout.py']))
    for layout,folder in [(baseline,old),(ROOT/'pixora_led_displays/graphic_layout.py',new)]:
        subprocess.run([sys.executable,__file__,str(layout),str(folder)],check=True)
    rows=json.loads((old/'index.json').read_text())
    assert rows==json.loads((new/'index.json').read_text()),'Frame count or timing changed'
    for row in rows:
        width=row['width'];lane=124 if width>=256 else 60;left=(width-lane)//2
        for i in range(row['count']):
            a=Image.open(old/f"{row['key']}-{i}.png").convert('RGB')
            b=Image.open(new/f"{row['key']}-{i}.png").convert('RGB')
            if width<192 or i<20 or row['kind']=='touchdown':
                assert a.tobytes()==b.tobytes(),(row['key'],i,'unaffected artwork changed')
                continue
            assert a.crop((left-2,4,left+lane+2,29)).tobytes()==b.crop((left-2,4,left+lane+2,29)).tobytes(),'Caption changed'
            for box in [(0,0,27,32),(width-27,0,width,32)]:
                assert a.crop(box).tobytes()==b.crop(box).tobytes(),'Side artwork changed'
            # Court/field/rink must survive in both bands between artwork and caption.
            for x in (40,width-41):
                assert a.getpixel((x,20))==(2,8,12),'Baseline no longer reproduces erased arena'
                assert b.getpixel((x,20))!=(2,8,12),(row['key'],i,'Arena erased at caption reveal')
print('Wall background passed: NBA/NFL wins, hockey/soccer goals, both wall widths; unchanged captions, assets, early frames, touchdown, 64/128 artwork and timing.')
