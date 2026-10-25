"""App/HA boundary tests: local authentication, permissions, no replay and app-only updates."""
import asyncio,copy,json,sys,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,patch
from aiohttp import web
from aiohttp.test_utils import TestClient,TestServer
import voice_test_conversation as fixture
from app import make_app,configure_bridge
from runtime.server import Runtime
bridge=fixture.bridge

class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.ha=AsyncMock(return_value={'service_response':{'result':None}})
        self.runtime=Runtime(self.root,self.ha)
        self.payload={'request_id':'request-nonce','text':'Is the front door open?','catalog':[
            {'entity_id':'binary_sensor.front','name':'Front door','state':'off','attributes':{'device_class':'door'},'area':'Living Room','control':False},
            {'entity_id':'lock.front','name':'Front door lock','state':'unlocked','attributes':{},'area':'Living Room','control':False},
            {'entity_id':'light.ceiling','name':'Ceiling light','state':'off','attributes':{},'area':'Living Room','control':True}],
            'origin':'Living Room','user_id':None,'valid_user':True,'admin':True,'device_id':'speaker','satellite_id':'assist_satellite.living','conversation_id':'test','timezone':'America/New_York','services':['light.turn_on','light.turn_off']}
    async def test_malformed_optional_planner_settings_do_not_break_local_voice(self):
        storage=self.root/'.storage';storage.mkdir()
        for value in ('[]','null','42','"bad"','{broken'):
            (storage/'pixora_voice_planner.json').write_text(value)
            self.assertIn('closed',(await self.runtime.answer(self.payload))['speech'])
        self.ha.assert_not_awaited()

    async def test_contact_read_is_local_and_command_uses_ha_bridge_once(self):
        result=await self.runtime.answer(self.payload)
        self.assertIn('closed',result['speech']);self.ha.assert_not_awaited()
        self.payload['text']='Turn on the ceiling light'
        result=await self.runtime.answer(self.payload)
        self.assertIn('turning on',result['speech']);self.ha.assert_awaited_once()
        call=self.ha.await_args.args
        self.assertEqual(call[0],'services/pixora_voice/runtime_action?return_response')
        self.assertEqual(call[1]['data']['data']['entity_id'],'light.ceiling')
    async def test_explicit_room_and_permission_denial(self):
        self.payload['catalog'].append({'entity_id':'light.kitchen','name':'Kitchen lights','state':'on','attributes':{},'area':'Kitchen','control':False})
        self.payload.update(text='Turn off all kitchen lights',user_id='restricted',admin=False)
        result=await self.runtime.answer(self.payload)
        self.assertIn('permissions',result['speech']);self.ha.assert_not_awaited()
    async def test_uncertain_rpc_never_retries_and_uses_same_answer_path(self):
        self.payload['text']='Turn on the ceiling light';self.ha.side_effect=ValueError('uncertain')
        result=await self.runtime.answer(self.payload)
        self.assertIn('not sure',result['speech']);self.ha.assert_awaited_once()
    async def test_own_planner_opt_in_and_saved_flows_are_preserved(self):
        storage=self.root/'.storage';storage.mkdir()
        (storage/'pixora_voice_planner.json').write_text('{"enabled":true}')
        (storage/'pixora_voice_flows.json').write_text('["Good night"]')
        self.ha.return_value={'service_response':{'result':'Started Good Night.'}}
        self.payload['text']='Good night'
        self.assertEqual((await self.runtime.answer(self.payload))['speech'],'Started Good Night.')
        self.assertEqual(self.ha.await_args.args[1]['op'],'flow')
    async def test_internal_routes_require_secret_and_do_not_open_admin_ui(self):
        app=make_app(self.root,self.root);app.on_startup.clear();app.on_cleanup.clear()
        app['runtime']=self.runtime;app['bridge_token']='test-private-bridge-key'
        client=TestClient(TestServer(app));await client.start_server();self.addAsyncCleanup(client.close)
        self.assertEqual((await client.post('/bridge/request',json=self.payload)).status,403)
        response=await client.post('/bridge/request',json=self.payload,headers={'X-Pixora-Bridge':'test-private-bridge-key'})
        self.assertEqual(response.status,200);self.assertIn('closed',(await response.json())['speech'])
        self.assertEqual((await client.get('/api/status',headers={'X-Pixora-Bridge':'test-private-bridge-key'})).status,403)
        self.assertEqual((await client.post('/bridge/request',json={'text':'x'},headers={'X-Pixora-Bridge':'test-private-bridge-key'})).status,400)

class LeaseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        fixture.AdapterTests.setUp(self)
        self.hass.data={};self.hass.states.get=lambda eid:next((s for s in self.states if s.entity_id==eid),None)
        self.lease={'id':'nonce','request':self.request,'until':time.monotonic()+30,'ids':{'light.living','light.kitchen'},'mutation':False,'operations':set()}
        self.hass.data['pixora_voice']={'bridge_requests':{'nonce':self.lease}}
    async def test_fresh_permissions_and_exposure_checked_before_command(self):
        data={'domain':'light','service':'turn_on','data':{'entity_id':'light.living'}}
        self.hass.hidden.add('light.living')
        with self.assertRaises(fixture.HAError):await bridge.execute(self.hass,self.lease,'service',data)
        self.hass.hidden.clear();self.control_denied.add('light.living')
        with self.assertRaises(fixture.HAError):await bridge.execute(self.hass,self.lease,'service',data)
        self.hass.services.async_call.assert_not_awaited()
    async def test_ha_context_preserved_and_mutation_never_repeated(self):
        data={'domain':'light','service':'turn_on','data':{'entity_id':'light.living'}}
        self.hass.services.async_call.side_effect=asyncio.TimeoutError
        with self.assertRaises(asyncio.TimeoutError):await bridge.execute(self.hass,self.lease,'service',data)
        with self.assertRaises(fixture.HAError):await bridge.execute(self.hass,self.lease,'service',data)
        self.hass.services.async_call.assert_awaited_once()
        self.assertIs(self.hass.services.async_call.await_args.kwargs['context'],self.context)
    async def test_expired_or_closed_request_cannot_act(self):
        data={'domain':'light','service':'turn_on','data':{'entity_id':'light.living'}}
        self.lease['until']=time.monotonic()-1
        with self.assertRaises(fixture.HAError):await bridge.execute(self.hass,self.lease,'service',data)
        self.lease['until']=time.monotonic()+30;self.hass.data['pixora_voice']['bridge_requests'].clear()
        with self.assertRaises(fixture.HAError):await bridge.execute(self.hass,self.lease,'service',data)
        self.hass.services.async_call.assert_not_awaited()
    async def test_arbitrary_service_and_thermostat_bypass_are_rejected(self):
        for domain,service,eid in [('homeassistant','restart','light.living'),('lock','unlock','light.living'),('climate','set_temperature','climate.hall')]:
            with self.assertRaises(fixture.HAError):await bridge.execute(self.hass,self.lease,'service',{'domain':domain,'service':service,'data':{'entity_id':eid}})
        self.hass.services.async_call.assert_not_awaited()
    async def test_bridge_outage_spoken_failure_does_not_restart_or_retry(self):
        with patch.object(bridge,'transport',AsyncMock(side_effect=OSError('app stopped'))) as send:
            response=await bridge.converse(self.hass,self.request,'test')
            self.assertIn('updating',response);send.assert_awaited_once()
            self.assertEqual(list(self.hass.data['pixora_voice']['bridge_requests']),['nonce'])
            self.hass.services.async_call.assert_not_awaited()

class ConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_connection_survives_app_restart_without_supervisor_or_rotation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            class Response:
                status=200
                async def __aenter__(self):return self
                async def __aexit__(self,*args):pass
                async def json(self):return {'data':{'hostname':'6264a0fa-pixora-voice'}}
            session=NS(get=lambda *args,**kwargs:Response())
            with patch.dict('os.environ',{'SUPERVISOR_TOKEN':'fixture'}):await configure_bridge(session,root)
            path=root/'.storage/pixora_voice_bridge.json';before=path.read_bytes()
            value=json.loads(before)
            self.assertEqual(value['url'],'http://6264a0fa-pixora-voice:4190');self.assertEqual(len(value['token']),64)
            with patch.dict('os.environ',{},clear=True):await configure_bridge(NS(get=lambda *a,**k:self.fail('No Supervisor call needed')),root)
            self.assertEqual(path.read_bytes(),before)
    async def test_interrupted_bridge_response_is_bounded_and_complete(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'.storage').mkdir()
            (root/'.storage/pixora_voice_bridge.json').write_text(json.dumps({'url':'http://6264a0fa-pixora-voice:4190','token':'fixture'}))
            class Response:
                status=200
                @property
                def content(self):return self
                async def __aenter__(self):return self
                async def __aexit__(self,*args):pass
                async def iter_chunked(self,n):
                    yield b'{"spe';yield b'ech":"Hello."}'
            session=NS(post=lambda *a,**k:Response())
            hass=NS(config=NS(path=lambda *parts:str(root.joinpath(*parts)),time_zone='UTC'))
            with patch.object(bridge,'async_get_clientsession',return_value=session):self.assertEqual(await bridge.transport(hass,'request',{}),{'speech':'Hello.'})
