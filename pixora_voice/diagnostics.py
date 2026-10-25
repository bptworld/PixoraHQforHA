"""On-demand, bounded reads of HA's existing Assist traces; no recorder or poller."""
from datetime import datetime

ERRORS = {
 'stt-no-text-recognized': ('Speech recognition', 'The recognizer could not match the spoken request.', 'This request may not be in Speech-to-Phrase’s trained vocabulary, even with clear audio. HA returned no text, so it cannot tell us which words were spoken or prove the exact cause. Try the same question in Ask Pixora: if it works there, check phrase coverage and training. If a known trained phrase also fails, then check microphone mute, audio, distance and background noise.'),
 'stt-provider-missing': ('Speech recognition', 'The speech recognition provider is missing.', 'Check the assistant’s speech-to-text selection and that Speech-to-Phrase is installed and running.'),
 'stt-provider-unsupported-metadata': ('Speech recognition', 'The recognizer rejected the audio format.', 'Check satellite firmware and the selected local speech recognizer.'),
 'stt-stream-failed': ('Speech recognition', 'The speech recognition stream failed.', 'Check Speech-to-Phrase logs and the satellite connection. Do not assume the question reached Pixora.'),
 'intent-failed': ('Question handling', 'The conversation agent failed.', 'Check HA Core logs for the matching time and verify Voice and Assist versions. Do not repeat a device command until its outcome is known.'),
 'intent-not-supported': ('Question handling', 'The selected assistant could not handle this request.', 'Check the assistant selection and supported phrases.'),
 'tts-failed': ('Speech generation', 'The spoken reply could not be generated.', 'Check Piper logs and the selected voice. A device action may already have happened; check its state before repeating it.'),
 'tts-provider-missing': ('Speech generation', 'The speech provider is missing.', 'Check Piper and the assistant’s text-to-speech selection.'),
 'wake-word-timeout': ('Wake word', 'No wake word was detected before the timeout.', 'Check the wake word selection and satellite microphone.'),
 'wake-word-detection-aborted': ('Wake word', 'Wake-word detection was stopped.', 'Check whether the satellite was muted, disconnected, or the request was cancelled.'),
}

def summarize(events,include_text=False):
    stamps={}
    error_code=None
    intent_error=False
    speech_engine=''
    unanswered=False
    heard='';reply=''
    for event in events[:200]:
        try:stamps[event['type']]=datetime.fromisoformat(event['timestamp'])
        except (KeyError,ValueError,TypeError):continue
        data=event.get('data') or {}
        if not isinstance(data,dict):continue
        if event.get('type')=='stt-start':speech_engine=str(data.get('engine',''))
        if event.get('type')=='stt-end':
            output=data.get('stt_output')
            text=output.get('text') if isinstance(output,dict) else None
            if isinstance(text,str):heard=text[:500]
        if event.get('type')=='error':
            code=data.get('code')
            error_code=code if isinstance(code,str) and code in ERRORS else 'unclassified'
        if event.get('type')=='intent-end':
            output=data.get('intent_output') or {}
            response=output.get('response') if isinstance(output,dict) else None
            intent_error=isinstance(response,dict) and response.get('response_type')=='error'
            block=response.get('speech') if isinstance(response,dict) else None
            plain=block.get('plain') if isinstance(block,dict) else None
            speech=plain.get('speech','') if isinstance(plain,dict) else ''
            if isinstance(speech,str):
                reply=speech[:1500]
                normalized=speech.strip().replace('’',"'").lower()
                unanswered=normalized in {"sorry, i can't find the information you're looking for.","sorry, i can't find the information you are looking for."} or normalized.startswith("i can't find the right device to check that.")
    def elapsed(start,end):
        try:return round(max(0,(stamps[end]-stamps[start]).total_seconds()),3)
        except (KeyError,TypeError):return None
    failed=error_code is not None or intent_error or unanswered
    details=ERRORS.get(error_code, ('Question handling' if intent_error else 'Pipeline', 'The assistant returned an error.' if intent_error else 'HA reported a pipeline error.', 'Check this run under HA Voice assistants → Debug and the matching HA Core logs. A command may already have run; check its state before retrying.')) if failed else None
    if unanswered and error_code is None:
        details=('Question handling','Speech was recognized, but Pixora could not find an answer.','Recognition and speech playback can complete even when the question was not answered. Inspect the recognized words under HA Voice assistants → Debug, then check request wording, device names, device type and Assist exposure. This does not indicate a microphone or Groq connection failure.')
    if failed and details[0]=='Speech recognition' and 'groq' in speech_engine.lower():
        details=('Speech recognition','Groq speech recognition did not return usable text.','Check Pixora Voice → Speech recognition → Test connection, then HA Core logs at this time for the specific HTTP status: 401/403 key or permissions, 429 free-plan/rate limit, or connection/timeout. Clear audio can also return no text. No recognized text reached Pixora; this is not a Speech-to-Phrase vocabulary error.')
    elif failed and details[0]=='Speech recognition' and 'whisper' in speech_engine.lower():
        details=('Speech recognition','Whisper did not return usable text.','Check the selected Whisper service logs, audio and connection at this time. Unlike Speech-to-Phrase, Whisper does not require a known trained phrase. No recognized text reached Pixora.')
    stages=[]
    for prefix,label in [('wake-word','Wake word'),('stt','Speech recognition'),('intent','Question handling'),('tts','Speech generation')]:
        stages.append({'name':label,'status':'failed' if failed and details[0]==label else 'completed' if prefix+'-end' in stamps else 'started; completion not recorded' if prefix+'-start' in stamps else 'not recorded'})
    result={'recognition_seconds':elapsed('stt-vad-end','stt-end'),
            'lookup_seconds':elapsed('intent-start','intent-end'),
            'speech_preparation_seconds':elapsed('tts-start','tts-end'),
            'complete':'run-end' in stamps,'error':failed,
            'status':'unanswered' if unanswered and error_code is None else 'failed' if failed else 'completed' if 'run-end' in stamps else 'incomplete',
            'stages':stages,'failure_stage':details[0] if details else None,
            'reason':details[1] if details else None,'next_check':details[2] if details else None,
            'error_code':error_code or ('answer-not-found' if unanswered else 'assistant-response-error' if intent_error else None)}
    if include_text:result.update(heard=heard,reply=reply)
    return result


async def recent_runs(session,token,agents,limit=5,include_text=False):
    # Close immediately after a user-requested read. Never return audio URLs,
    # tokens or other assistants' traces to the ingress browser. The admin
    # Voice log may display bounded heard/reply text on demand for each request.
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
        limit=max(1,min(20,int(limit)))
        candidates=[]
        for pipeline in [p for p in pipelines if p.get('conversation_engine') in agents][:4]:
            runs=(await call('assist_pipeline/pipeline_debug/list',pipeline_id=pipeline['id'])).get('pipeline_runs',[])
            candidates.extend((r,pipeline) for r in runs[-limit:])
        candidates.sort(key=lambda pair:pair[0].get('timestamp',''),reverse=True)
        output=[]
        for run,pipeline in candidates[:limit]:
            data=await call('assist_pipeline/pipeline_debug/get',pipeline_id=pipeline['id'],pipeline_run_id=run['pipeline_run_id'])
            output.append({'timestamp':run.get('timestamp'),'pipeline':pipeline.get('name','Pixora Voice'),**summarize(data.get('events',[]),include_text=include_text)})
        return output
