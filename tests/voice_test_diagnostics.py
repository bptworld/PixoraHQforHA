"""Trace timing semantics, bounded reads, and no transcript/token leakage."""
import sys,unittest,json
from pathlib import Path
from types import SimpleNamespace as NS
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'pixora_voice'))
from diagnostics import summarize,recent_runs

class TimingTests(unittest.IsolatedAsyncioTestCase):
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

if __name__=='__main__':unittest.main()
