"""Isolated card render subprocess. Never gets Supervisor credentials."""
import base64,importlib.util,io,json,os,sys
from pathlib import Path
from PIL import Image,ImageOps,ImageSequence
request=json.loads(sys.stdin.buffer.read(65537))
root=Path(request['root']).resolve();os.chdir(root)
sys.path[:0]=[str(root),str(root/'addons')]
sys.dont_write_bytecode=True
spec=importlib.util.spec_from_file_location('selected_card',root/'addons'/(request['module']+'.py'))
module=importlib.util.module_from_spec(spec)
import card_utils
settings=request.get('settings',{})
card_utils._settings_value=lambda key,default='':settings.get(key,default)
spec.loader.exec_module(module)
if request['module']=='home_assistant_entity':
    state=request.get('ha_state')
    if state is None:raise ValueError('Choose an available HA entity.')
    module._state=lambda *_:state
    request['options'].update({'host':'local','token':'local'})
body=module.render(request['options'])
if not isinstance(body,bytes) or len(body)>5*1024*1024:raise ValueError('Card returned invalid artwork.')
# Normalize card artwork locally; retain bounded animation frames for deck playback.
with Image.open(io.BytesIO(body)) as image:
    if image.width*image.height>16000000:raise ValueError('Card artwork too large.')
    frames=[];durations=[]
    for index,frame in enumerate(ImageSequence.Iterator(image)):
        if index>=120:break
        rgba=frame.convert('RGBA')
        rgb=Image.alpha_composite(Image.new('RGBA',rgba.size,'black'),rgba).convert('RGB')
        frames.append(ImageOps.pad(rgb,(request['width'],32),color='black'))
        durations.append(max(250,min(2000,int(frame.info.get('duration',250)))))
    out=io.BytesIO()
    if len(frames)>1:frames[0].save(out,'WEBP',save_all=True,append_images=frames[1:],duration=durations,loop=0,lossless=True)
    else:frames[0].save(out,'PNG')
    sys.stdout.buffer.write(out.getvalue())
