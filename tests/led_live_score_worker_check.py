"""Actual public NBA/NFL cards report selected-game state through the HA worker."""
import base64,io,json,os,subprocess,sys,urllib.error,urllib.request
from datetime import datetime,timezone
from pathlib import Path
APP=Path(__file__).resolve().parents[1]/'pixora_led_displays'
sys.path.insert(0,str(APP))

if len(sys.argv)>1 and sys.argv[1]=='worker':
    request=json.loads(sys.stdin.read());phase=request['options'].pop('testPhase')
    team=request['options']['favoriteTeam']
    status={'state':phase,'shortDetail':'2nd quarter' if phase=='in' else 'Final' if phase=='post' else 'Scheduled','completed':phase=='post'}
    teams=[{'homeAway':'away','score':'10','team':{'id':'1','abbreviation':'OTHER','displayName':'Other','shortDisplayName':'Other','color':'445566'}},
           {'homeAway':'home','score':'14','team':{'id':'2','abbreviation':team,'displayName':'Selected','shortDisplayName':'Selected','color':'005544'}}]
    event={'id':'game','date':datetime.now(timezone.utc).isoformat(),'status':{'type':status},'competitions':[{'id':'game','status':{'type':status},'competitors':teams}]}
    def urlopen(request,*args,**kwargs):
        url=request.full_url if isinstance(request,urllib.request.Request) else str(request)
        if 'scoreboard' not in url:raise urllib.error.URLError('Offline worker check')
        response=io.BytesIO(json.dumps({'events':[event]}).encode());response.status=200;return response
    urllib.request.urlopen=urlopen
    import card_worker
    result=card_worker.run(request)
    assert result['live_sports'] is (phase=='in'),(request['module'],phase,result['live_sports'])
    from PIL import Image
    with Image.open(io.BytesIO(base64.b64decode(result['body']))) as image:assert image.size==(request['width'],32)
else:
    root=sys.argv[1]
    for module,team in (('nba','BOS'),('nfl','NE')):
        for width in (64,128):
            for phase in ('pre','in','post'):
                request={'root':root,'module':module,'width':width,'protocol':2,'dwell':25,'settings':{},'events':False,
                    'options':{'favoriteTeam':team,'testPhase':phase,'_target':f'matrixportal-s3-{width}x32'}}
                result=subprocess.run([sys.executable,__file__,'worker'],input=json.dumps(request).encode(),capture_output=True,timeout=30)
                assert result.returncode==0,result.stderr.decode()
    print('Public score workers passed: NBA and NFL at both sizes, selected-game pre/live/final state, real rendered artwork and no provider network.')
