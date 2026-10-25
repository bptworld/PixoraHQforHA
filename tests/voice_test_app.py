"""Ingress access and one-shot app-to-HA calls; no real HA endpoint."""
import os,sys,tempfile,unittest,json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,patch
from aiohttp import web
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'pixora_voice'))
from app import make_app


class Response:
    def __init__(self,status,data):self.status=status;self.data=data
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass
    async def json(self):return self.data


class AppTests(unittest.IsolatedAsyncioTestCase):
    async def test_speech_settings_never_return_saved_key(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);app=make_app(root,root)
            routes={(r.method,r.resource.canonical):r.handler for r in app.router.routes()}
            key='gsk_'+'fake_for_test_'*3
            post=NS(method='POST',headers={'X-Pixora-Request':'1'},json=AsyncMock(return_value={'enabled':True,'key':key}))
            reply=await routes['POST','/api/speech'](post)
            self.assertEqual(reply.status,200);self.assertNotIn(key,reply.text)
            reply=await routes['GET','/api/speech'](NS(method='GET'))
            self.assertTrue(json.loads(reply.text)['key_saved']);self.assertNotIn(key,reply.text)
            post.headers={}
            self.assertEqual((await routes['POST','/api/speech'](post)).status,400)

    async def test_connection_test_sends_key_only_to_groq_without_audio(self):
        from speech_settings import save_settings
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);app=make_app(root,root);calls=[]
            save_settings(root,{'enabled':True,'key':'gsk_'+'fake_for_test_'*3})
            def get(url,**kwargs):calls.append((url,kwargs));return Response(200,{})
            app['session']=NS(get=get)
            handler=next(r.handler for r in app.router.routes() if r.method=='POST' and r.resource.canonical=='/api/speech/test')
            result=await handler(NS(headers={'X-Pixora-Request':'1'}))
            self.assertEqual(result.status,200);self.assertEqual(len(calls),1)
            self.assertEqual(calls[0][0],'https://api.groq.com/openai/v1/models')
            self.assertFalse(calls[0][1]['allow_redirects']);self.assertNotIn('data',calls[0][1])

    async def test_restart_requires_explicit_confirmation_and_cannot_be_queued_twice(self):
        import asyncio
        from app import VERSION
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);app=make_app(root,root)
            app['maintenance']={'pending':False,'restartRequired':True}
            journal=root/'integration-update.json'
            journal.write_text(json.dumps({'version':VERSION,'phase':'awaiting-restart','needRestart':True}))
            handler=next(r.handler for r in app.router.routes() if r.method=='POST' and r.resource.canonical=='/api/restart')
            bad=NS(headers={},json=AsyncMock(return_value={'confirm':True}))
            self.assertEqual((await handler(bad)).status,400)
            self.assertEqual(json.loads(journal.read_text())['phase'],'awaiting-restart')
            allowed=NS(headers={'X-Pixora-Request':'1'},json=AsyncMock(return_value={'confirm':True}))
            with patch('app.finish_integration_update',AsyncMock()) as finish:
                self.assertEqual((await handler(allowed)).status,200)
                await app['update_task']
                self.assertEqual(json.loads(journal.read_text())['phase'],'restart-approved')
                self.assertEqual((await handler(allowed)).status,409)
                finish.assert_awaited_once()

    async def test_voice_log_only_reads_traces_on_request(self):
        app=make_app();calls=[]
        def request(method,url,**kwargs):
            calls.append((method,url))
            return Response(200,[{'entity_id':'conversation.local','attributes':{'friendly_name':'Pixora Voice'}}])
        app['session']=NS(request=request)
        handler=next(r.handler for r in app.router.routes() if r.method=='GET' and r.resource.canonical=='/api/voice-log')
        with patch.dict(os.environ,{'SUPERVISOR_TOKEN':'fixture-token'}), patch('diagnostics.recent_runs',AsyncMock(return_value=[])) as read:
            self.assertFalse(calls)
            response=await handler(NS())
            self.assertEqual(json.loads(response.text),{'runs':[]})
            self.assertEqual(read.await_args.kwargs,{'limit':20})
            self.assertTrue(all(method=='GET' for method,url in calls))
    async def test_direct_access_and_cross_origin_installs_denied(self):
        app=make_app();handler=AsyncMock(return_value=web.json_response({'ok':True}));gate=app.middlewares[0]
        with self.assertRaises(web.HTTPForbidden):await gate(NS(remote='127.0.0.1',method='POST'),handler)
        request=NS(remote='172.30.32.2',method='POST',headers={'Origin':'https://elsewhere.invalid'},host='homeassistant.local')
        with self.assertRaises(web.HTTPForbidden):await gate(request,handler)
        handler.assert_not_awaited()

    async def test_ingress_allows_authenticated_same_origin(self):
        app=make_app();handler=AsyncMock(return_value=web.json_response({'ok':True}))
        request=NS(remote='172.30.32.2',method='POST',headers={'Origin':'http://homeassistant.local:8123','X-Forwarded-Host':'homeassistant.local:8123'},host='internal')
        response=await app.middlewares[0](request,handler)
        self.assertEqual(response.status,200);self.assertEqual(response.headers['Cache-Control'],'no-store')

    async def test_planner_corrupt_settings_and_invalid_input(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'.storage').mkdir();(root/'.storage/pixora_voice_planner.json').write_text('[]')
            app=make_app(root,root)
            get=next(r.handler for r in app.router.routes() if r.method=='GET' and r.resource.canonical=='/api/planner')
            post=next(r.handler for r in app.router.routes() if r.method=='POST' and r.resource.canonical=='/api/planner')
            self.assertFalse(json.loads((await get(NS(method='GET'))).text)['enabled'])
            result=await post(NS(method='POST',json=AsyncMock(return_value={'enabled':'yes'})))
            self.assertEqual(result.status,400)
            result=await post(NS(method='POST',json=AsyncMock(return_value={'enabled':False})))
            self.assertEqual(result.status,200);self.assertFalse(json.loads((root/'.storage/pixora_voice_planner.json').read_text())['enabled'])

    async def test_uncertain_post_is_not_retried(self):
        app=make_app();calls=[]
        def request(method,url,**kwargs):
            calls.append((method,url))
            if method=='GET':return Response(200,[{'entity_id':'conversation.local','attributes':{'friendly_name':'Pixora Voice'}}])
            return Response(503,{})
        app['session']=NS(request=request)
        handler=next(route.handler for route in app.router.routes() if route.method=='POST' and route.resource.canonical=='/api/ask')
        with patch.dict(os.environ,{'SUPERVISOR_TOKEN':'local-fixture-only'}):
            response=await handler(NS(json=AsyncMock(return_value={'text':'Turn on the ceiling light'})))
        self.assertEqual(response.status,503);self.assertEqual(len([c for c in calls if c[0]=='POST']),1)

if __name__=='__main__':unittest.main()
