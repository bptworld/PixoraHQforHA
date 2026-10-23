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
