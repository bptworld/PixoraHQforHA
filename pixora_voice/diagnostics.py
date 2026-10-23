"""On-demand, bounded reads of HA's existing Assist traces; no recorder or poller."""
from datetime import datetime

def summarize(events):
    stamps={}
    for event in events[:200]:
        try:stamps[event['type']]=datetime.fromisoformat(event['timestamp'])
        except (KeyError,ValueError,TypeError):continue
    def elapsed(start,end):
        try:return round(max(0,(stamps[end]-stamps[start]).total_seconds()),3)
        except (KeyError,TypeError):return None
    return {'recognition_seconds':elapsed('stt-vad-end','stt-end'),
            'lookup_seconds':elapsed('intent-start','intent-end'),
            'speech_preparation_seconds':elapsed('tts-start','tts-end'),
            'complete':'run-end' in stamps,'error':'error' in stamps}


async def recent_runs(session,token,agents):
    # Close immediately after a user-requested read. Never return speech, audio
    # URLs, tokens or other assistants' traces to the ingress browser.
    async with session.ws_connect('ws://supervisor/core/websocket',max_msg_size=1024*1024) as ws:
        if (await ws.receive_json(timeout=8)).get('type')!='auth_required':raise ValueError('Assist timing is unavailable.')
        await ws.send_json({'type':'auth','access_token':token})
        if (await ws.receive_json(timeout=8)).get('type')!='auth_ok':raise ValueError('Assist timing access is unavailable.')
        ident=0
        async def call(kind,**data):
            nonlocal ident
            ident+=1
            await ws.send_json({'id':ident,'type':kind,**data})
            reply=await ws.receive_json(timeout=8)
            if reply.get('id')!=ident or not reply.get('success'):raise ValueError('Assist timing is unavailable on this Home Assistant version.')
            return reply['result']
        pipelines=(await call('assist_pipeline/pipeline/list')).get('pipelines',[])
        candidates=[]
        for pipeline in [p for p in pipelines if p.get('conversation_engine') in agents][:4]:
            runs=(await call('assist_pipeline/pipeline_debug/list',pipeline_id=pipeline['id'])).get('pipeline_runs',[])
            candidates.extend((r,pipeline) for r in runs[-5:])
        candidates.sort(key=lambda pair:pair[0].get('timestamp',''),reverse=True)
        output=[]
        for run,pipeline in candidates[:5]:
            data=await call('assist_pipeline/pipeline_debug/get',pipeline_id=pipeline['id'],pipeline_run_id=run['pipeline_run_id'])
            output.append({'timestamp':run.get('timestamp'),'pipeline':pipeline.get('name','Pixora Voice'),**summarize(data.get('events',[]))})
        return output
