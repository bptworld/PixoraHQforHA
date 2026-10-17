"""Import dynamic sports cards with only their verified downloaded dependencies."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
catalog=json.loads((ROOT/'pixora_led_displays/card_catalog.json').read_text())
source=Path('D:/planner/.build-tmp/led-public-card-source')
cards={c['id']:c for c in catalog['cards']}
siblings={'college_football':'nfl','cfl':'nfl','ufl':'nfl','college_baseball':'mlb','college_softball':'mlb','mens_college_hockey':'nhl'}
required=sorted({name for ident in siblings for name in cards[ident]['files']})
queries=''.join(catalog['commit']+':cards/'+name+'\n' for name in required).encode()
raw=subprocess.check_output(['git','-C',str(source),'cat-file','--batch'],input=queries)
position=0;blobs={}
for name in required:
    end=raw.index(b'\n',position);size=int(raw[position:end].split()[-1]);body=raw[end+1:end+size+1];position=end+size+2
    assert hashlib.sha256(body).hexdigest()==catalog['files'][name]['sha256']
    blobs[name]=body

with tempfile.TemporaryDirectory() as temp:
    base=Path(temp)
    for ident,helper in siblings.items():
        assert 'addons/'+helper+'.py' in cards[ident]['files'],ident+' is missing its animation module'
        root=base/ident;root.mkdir()
        for name in cards[ident]['files']:
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(blobs[name])
        code="""import importlib.util,sys,io
from PIL import Image
from pathlib import Path
root=Path(sys.argv[1]);sys.path[:0]=[str(root),str(root/'addons')]
spec=importlib.util.spec_from_file_location('selected',root/'addons'/(sys.argv[2]+'.py'));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
# Render the actual card through its normal entry point with provider I/O isolated.
output=io.BytesIO();Image.new('RGB',(64,32),'blue').save(output,'PNG')
module.render_sport_card=lambda *args,**kwargs:output.getvalue()
body=module.render({'_is_prefetch':True,'_target':'matrixportal-s3-64x32'})
with Image.open(io.BytesIO(body)) as image:assert image.size==(64,32)
"""
        result=subprocess.run([sys.executable,'-c',code,str(root),cards[ident]['module']],capture_output=True,timeout=30,cwd=root)
        assert result.returncode==0,ident+': '+result.stderr.decode()
        print(ident+': isolated import and render passed')
print('All six dynamic sports dependency checks passed; no unrelated card installation required.')
