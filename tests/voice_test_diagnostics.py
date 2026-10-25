"""Trace timing semantics, bounded reads, and no transcript/token leakage."""
import sys,unittest,json
from pathlib import Path
from types import SimpleNamespace as NS
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'pixora_voice'))
from diagnostics import summarize,recent_runs

class TimingTests(unittest.IsolatedAsyncioTestCase):
    def test_not_found_reply_is_unanswered_even_when_pipeline_completed(self):
        events=[{'type':'stt-end','timestamp':'2026-10-25T15:26:40+00:00','data':{'stt_output':{'text':'private question'}}},
          {'type':'intent-end','timestamp':'2026-10-25T15:26:41+00:00','data':{'intent_output':{'response':{'response_type':'action_done','speech':{'plain':{'speech':"Sorry, I can't find the information you're looking for."}}}}}},
          {'type':'run-end','timestamp':'2026-10-25T15:26:42+00:00'}]
        result=summarize(events)
        self.assertTrue(result['complete']);self.assertTrue(result['error']);self.assertEqual(result['status'],'unanswered')
        self.assertEqual(result['failure_stage'],'Question handling');self.assertEqual(result['error_code'],'answer-not-found')
        self.assertIn('Speech was recognized',result['reason']);self.assertNotIn('private question',json.dumps(result))
        detailed=summarize(events,include_text=True)
        self.assertEqual(detailed['heard'],'private question');self.assertIn("can't find",detailed['reply'])
        successful=summarize([{'type':'stt-end','timestamp':'2026-10-25T15:26:40+00:00','data':{'stt_output':{'text':'private success'}}},{'type':'run-end','timestamp':'2026-10-25T15:26:41+00:00'}],include_text=True)
        self.assertEqual(successful['heard'],'private success')
        self.assertNotIn('heard',summarize(events))
    def test_app_outage_reply_is_a_handling_failure_even_if_pipeline_completed(self):
        events=[{'type':'intent-end','timestamp':'2026-10-25T12:00:01+00:00','data':{'intent_output':{'response':{'response_type':'action_done','speech':{'plain':{'speech':"I couldn't finish that request. Voice may be updating. Please check any device you asked to control before trying again."}}}}}}, {'type':'run-end','timestamp':'2026-10-25T12:00:02+00:00'}]
        result=summarize(events)
        self.assertEqual(result['status'],'failed');self.assertEqual(result['error_code'],'voice-app-unavailable')
        self.assertEqual(result['failure_stage'],'Question handling');self.assertIn('before repeating',result['next_check'])

    def test_groq_failure_does_not_blame_phrase_training(self):
        result=summarize([{'type':'stt-start','timestamp':'2026-10-25T12:00:00+00:00','data':{'engine':'stt.pixora_groq_whisper'}},
             {'type':'error','timestamp':'2026-10-25T12:00:01+00:00','data':{'code':'stt-stream-failed'}}])
        self.assertIn('Groq',result['reason']);self.assertIn('429',result['next_check'])
        self.assertNotIn('check phrase coverage',result['next_check'])
    def test_speech_failure_has_specific_reason_without_raw_payload(self):
        events=[{'type':'stt-start','timestamp':'2026-10-25T12:00:00+00:00'},
                {'type':'error','timestamp':'2026-10-25T12:00:03+00:00','data':{'code':'stt-no-text-recognized','message':'secret audio url private text'}},
                {'type':'run-end','timestamp':'2026-10-25T12:00:04+00:00'}]
        result=summarize(events)
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['failure_stage'],'Speech recognition')
        self.assertIn('trained vocabulary, even with clear audio',result['next_check']);self.assertIn('cannot tell us which words',result['next_check'])
        self.assertNotIn('secret',json.dumps(result))
        self.assertEqual(result['stages'][1]['status'],'failed')
        self.assertEqual(result['stages'][2]['status'],'not recorded')

    def test_unknown_error_does_not_expose_exception_or_guess_cause(self):
        result=summarize([{'type':'error','timestamp':'2026-10-25T12:00:00+00:00','data':{'code':'private-secret','message':'credentials'}}])
        self.assertEqual(result['error_code'],'unclassified')
        self.assertEqual(result['failure_stage'],'Pipeline')
        self.assertNotIn('private-secret',json.dumps(result))
        self.assertNotIn('credentials',json.dumps(result))

    def test_error_answer_is_not_reported_as_success(self):
        result=summarize([{'type':'intent-end','timestamp':'2026-10-25T12:00:01+00:00','data':{'intent_output':{'response':{'response_type':'error','speech':{'plain':{'speech':'private'}}}}}}, {'type':'run-end','timestamp':'2026-10-25T12:00:02+00:00'}])
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['failure_stage'],'Question handling')
        self.assertNotIn('private',json.dumps(result))

    def test_speech_generation_failure_warns_against_duplicate_commands(self):
        result=summarize([{'type':'error','timestamp':'2026-10-25T12:00:00+00:00','data':{'code':'tts-failed'}}])
        self.assertIn('already have happened',result['next_check'])
        self.assertEqual(result['failure_stage'],'Speech generation')

    def test_incomplete_run_is_not_a_success(self):
        self.assertEqual(summarize([])['status'],'incomplete')

    def test_recognition_excludes_speaking_and_missing_is_unknown(self):
        def event(kind,second):return {'type':kind,'timestamp':f'2026-10-23T18:00:{second:02d}+00:00','data':{'text':'private','url':'secret'}}
        result=summarize([event('stt-start',0),event('stt-vad-end',4),event('stt-end',6),event('intent-start',6),event('intent-end',7),event('run-end',8)])
        self.assertEqual(result['recognition_seconds'],2);self.assertEqual(result['lookup_seconds'],1)
        self.assertIsNone(result['speech_preparation_seconds']);self.assertTrue(result['complete'])
        self.assertNotIn('secret',json.dumps(result));self.assertNotIn('private',json.dumps(result))

    async def test_on_demand_read_only_bounded_and_filtered(self):
        class Socket:
            def __init__(self):self.sent=[];self.reply=None;self.auth=False
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
            async def send_json(self,message):
                self.sent.append(message)
                if message['type']=='auth':self.reply={'type':'auth_ok'};return
                kind=message['type']
                if kind.endswith('pipeline/list'):value={'pipelines':[{'id':'ours','conversation_engine':'conversation.pixora','name':'Pixora'},{'id':'other','conversation_engine':'other'}]}
                elif kind.endswith('/list'):value={'pipeline_runs':[{'pipeline_run_id':str(i),'timestamp':str(i).zfill(2)} for i in range(20)]}
                else:value={'events':[{'type':'stt-end','timestamp':'2026-10-23T18:00:06+00:00','data':{'text':'private','token':'secret'}}]}
                self.reply={'id':message['id'],'success':True,'result':value}
            async def receive_json(self,**kw):
                if self.reply is None:return {'type':'auth_required'}
                return self.reply
        socket=Socket();session=NS(ws_connect=lambda *args,**kw:socket)
        result=await recent_runs(session,'fixture-token',['conversation.pixora'])
        self.assertEqual(len(result),5)
        self.assertTrue(all(m.get('pipeline_id','ours')=='ours' for m in socket.sent))
        self.assertNotIn('private',json.dumps(result));self.assertNotIn('secret',json.dumps(result))
        self.assertTrue(all(m['type'] in {'auth','assist_pipeline/pipeline/list','assist_pipeline/pipeline_debug/list','assist_pipeline/pipeline_debug/get'} for m in socket.sent))
        expanded=await recent_runs(NS(ws_connect=lambda *args,**kw:Socket()),'fixture-token',['conversation.pixora'],limit=100)
        self.assertEqual(len(expanded),20)

if __name__=='__main__':unittest.main()
