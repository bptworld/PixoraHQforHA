"""Isolated local card renderer with Cloud-compatible result envelopes."""
import base64,contextlib,importlib.util,io,json,os,sys
from datetime import datetime,date
from pathlib import Path
from PIL import Image,ImageOps,ImageSequence


def pack(value,depth=0):
    if depth>20:raise ValueError('Event state is too deeply nested.')
    if value is None or isinstance(value,(str,int,float,bool)):return value
    if isinstance(value,(datetime,date)):return {'@datetime':value.isoformat()}
    if isinstance(value,tuple):return {'@tuple':[pack(v,depth+1) for v in value]}
    if isinstance(value,set):return {'@set':[pack(v,depth+1) for v in value]}
    if isinstance(value,list):return [pack(v,depth+1) for v in value]
    if isinstance(value,dict):return {'@dict':[[pack(k,depth+1),pack(v,depth+1)] for k,v in list(value.items())[-2000:]]}
    raise ValueError('Unsupported event state value.')


def unpack(value):
    if isinstance(value,list):return [unpack(v) for v in value]
    if not isinstance(value,dict):return value
    if '@datetime' in value:return datetime.fromisoformat(value['@datetime'])
    if '@tuple' in value:return tuple(unpack(v) for v in value['@tuple'])
    if '@set' in value:return set(unpack(v) for v in value['@set'])
    if '@dict' in value:return {unpack(k):unpack(v) for k,v in value['@dict']}
    return value


def artwork(body,width,durations=None,once=False):
    if not isinstance(body,(bytes,bytearray)) or not body or len(body)>5*1024*1024:raise ValueError('Card returned invalid artwork.')
    with Image.open(io.BytesIO(body)) as image:
        if image.width*image.height>16000000:raise ValueError('Card artwork too large.')
        frames=[];timing=[]
        for index,frame in enumerate(ImageSequence.Iterator(image)):
            if index>=240:raise ValueError('Animation exceeds 240 frames.')
            rgba=frame.convert('RGBA');rgb=Image.alpha_composite(Image.new('RGBA',rgba.size,'black'),rgba).convert('RGB')
            frames.append(ImageOps.pad(rgb,(width,32),color='black'))
            delay=durations[index] if durations and index<len(durations) else frame.info.get('duration',100)
            timing.append(max(20,min(60000,int(delay))))
        output=io.BytesIO()
        if len(frames)>1:frames[0].save(output,'WEBP',save_all=True,append_images=frames[1:],duration=timing,loop=1 if once else 0,lossless=True,method=0)
        else:frames[0].save(output,'PNG')
        return output.getvalue()


def renderer_body(module,spec,width):
    renderer=getattr(module,str(spec.get('renderer','')),None)
    if not callable(renderer):raise ValueError('Special graphic renderer is unavailable.')
    team=dict(spec.get('team') or {});team['_width']=width
    result=renderer(team,str(spec.get('kind') or spec.get('type') or 'score'))
    if isinstance(result,(bytes,bytearray)):return result,None
    if isinstance(result,tuple) and len(result)>=2 and result[0]:
        frames=result[0];timing=result[1];output=io.BytesIO()
        frames[0].save(output,'WEBP',save_all=True,append_images=frames[1:],duration=timing,loop=1,lossless=True,method=0)
        return output.getvalue(),timing
    raise ValueError('Special graphic renderer returned no artwork.')


def run(request):
    root=Path(request['root']).resolve();os.chdir(root);sys.path[:0]=[str(root),str(root/'addons')];sys.dont_write_bytecode=True
    spec=importlib.util.spec_from_file_location('selected_card',root/'addons'/(request['module']+'.py'))
    module=importlib.util.module_from_spec(spec);settings=request.get('settings',{})
    if (root/'card_utils.py').is_file():
        import card_utils
        card_utils._settings_value=lambda key,default='':settings.get(key,default)
        if callable(getattr(card_utils,'use_runtime_settings',None)):card_utils.use_runtime_settings(settings)
    spec.loader.exec_module(module)
    for name,value in request.get('event_state',{}).items():
        if isinstance(getattr(module,name,None),dict) and ('STATE' in name or name in ('_LAST_SEEN','_LAST_FLIGHT_POS')):
            getattr(module,name).update(unpack(value))
    if request['module']=='home_assistant_entity':
        state=request.get('ha_state')
        if state is None:raise ValueError('Choose an available HA entity.')
        module._state=lambda *_:state
        request['options'].update({'host':'local','token':'local'})
    options=dict(request['options']);options.update({'_pixora_target':'pixora-s3-wide' if request['width']==128 else 'pixora-s3','_settings':settings,'_width':request['width'],'_device_id':request.get('device_id','preview'),
        '_dwell':request.get('dwell',15),'_is_prefetch':not request.get('events',False)})
    result=module.render(options);event=None;state={}
    if request.get('events'):
        for name,value in vars(module).items():
            if isinstance(value,dict) and ('STATE' in name or name in ('_LAST_SEEN','_LAST_FLIGHT_POS')):
                try:state[name]=pack(value)
                except ValueError:continue
    duration=request.get('dwell',15);body=result
    if isinstance(result,dict):
        body=result.get('body');duration=result.get('dwell_secs') or duration
        wall=result.get('wallGraphic') or result.get('_group_wall')
        device=result.get('deviceGraphic') or result.get('_device_graphic') or {}
        special=bool(wall or device or any(result.get(k) for k in ('_priority','_priority_graphic','_no_replay','_stay')))
        if special and request.get('events'):
            width=request.get('wall_width',request['width']) if wall else request['width'];graphic_spec=wall or device
            timing=result.get('_frame_durations_ms')
            event_body=body
            if wall or not isinstance(event_body,(bytes,bytearray)):
                event_body,timing=renderer_body(module,graphic_spec,width)
            event={'body':base64.b64encode(artwork(event_body,width,timing,True)).decode(),'duration':max(1,min(300,int(graphic_spec.get('dwell_secs') or duration))),
                'kind':str(graphic_spec.get('kind') or graphic_spec.get('type') or 'special'),'wall':bool(wall),'width':width,'once':True}
            # An event is never stored as ordinary deck artwork.
            ordinary=module.render({**options,'_is_prefetch':True})
            body=ordinary.get('body') if isinstance(ordinary,dict) else ordinary
            if isinstance(ordinary,dict) and (ordinary.get('deviceGraphic') or ordinary.get('wallGraphic') or ordinary.get('_group_wall') or ordinary.get('_priority') or ordinary.get('_priority_graphic') or ordinary.get('_no_replay') or ordinary.get('_stay')):body=None
            duration=ordinary.get('dwell_secs',request.get('dwell',15)) if isinstance(ordinary,dict) else request.get('dwell',15)
        elif special:
            ordinary=module.render({**options,'_is_prefetch':True})
            body=ordinary.get('body') if isinstance(ordinary,dict) else ordinary
            if isinstance(ordinary,dict) and (ordinary.get('deviceGraphic') or ordinary.get('wallGraphic') or ordinary.get('_group_wall') or ordinary.get('_priority') or ordinary.get('_priority_graphic') or ordinary.get('_no_replay') or ordinary.get('_stay')):body=None
    normal=None if body is None else artwork(body,request['width'],result.get('_frame_durations_ms') if isinstance(result,dict) and not event else None)
    return {'body':base64.b64encode(normal).decode() if normal else None,'duration':max(1,min(300,int(duration))),
        'skip':normal is None,'event':event,'state':state}


if __name__=='__main__':
    request=json.loads(sys.stdin.buffer.read(2*1024*1024+1))
    # Third-party card print statements cannot corrupt the binary/JSON protocol.
    with contextlib.redirect_stdout(sys.stderr):result=run(request)
    if request.get('protocol')==2:sys.stdout.write(json.dumps(result,separators=(',',':')))
    else:
        if result['body'] is None:raise ValueError('Card has no active artwork.')
        sys.stdout.buffer.write(base64.b64decode(result['body']))
