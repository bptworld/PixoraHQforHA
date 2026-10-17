"""Failed actions retain their actual cause and identify only failed displays."""
import asyncio
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
from aiohttp.test_utils import TestClient, TestServer
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pixora_led_displays'))
from app import make_app

async def check():
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder)
        app=make_app(root,root/'ha',ingress_peer='127.0.0.1')
        async with TestClient(TestServer(app)) as client:
            studio=app['studio']
            studio.displays=lambda:[{'id':'center','name':'Center-128'},{'id':'left','name':'Left-64'}]
            studio.data['devices']={'center':{'playing':True},'left':{'playing':True}}
            async def play(ident):
                if ident=='center':raise ValueError('No playable cards remain.')
            with patch.object(studio,'selected'),patch.object(studio,'play',side_effect=play):
                response=await client.post('/api/studio/action',json={'id':'center','action':'play'})
                error=(await response.json())['error']
                assert response.status==400 and error=='Center-128: No playable cards remain.'
                assert 'group' not in error
                assert studio.runtime['center']['error']=='No playable cards remain.'
                assert not studio.data['devices']['center']['playing']
                studio.data['groups']['both']={'members':['center','left']}
                response=await client.post('/api/studio/action',json={'id':'both','action':'play'})
                assert (await response.json())['error']==error
                assert studio.data['devices']['left']['playing']
                assert (await client.post('/api/studio/action',json={'id':'left','action':'play'})).status==200

asyncio.run(check())
print('Action errors passed: single-display cause, partial group failure and retained device status.')
