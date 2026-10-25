"""Local Voice/controller protocol tests with no HA device writes."""
import asyncio
import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
spec = importlib.util.spec_from_file_location("voice_thermostat_bridge", Path(__file__).resolve().parents[1] / "pixora_voice/custom_components/pixora_voice/thermostat.py")
bridge = importlib.util.module_from_spec(spec); spec.loader.exec_module(bridge)

class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_correlated_reply_and_listener_cleanup(self):
        handlers = {}; removed = []
        def listen(event, callback):
            handlers[event] = callback
            return lambda: removed.append(event)
        def fire(event, data):
            callback = handlers["pixora_thermostat_voice_reply"]
            callback(NS(data={"request_id": "wrong", "unmanaged": True}))
            callback(NS(data={"request_id": data["request_id"], "speech": "Override saved."}))
        hass = NS(bus=NS(async_listen=listen, async_fire=fire))
        command = {"service": "set_temperature", "data": {"entity_id": "climate.living", "temperature": 72}}
        self.assertEqual(await bridge.route(hass, command), "Override saved.")
        self.assertEqual(len(removed), 1)

    async def test_only_explicit_unmanaged_allows_native_fallback(self):
        handlers = {}
        def listen(event, callback):
            handlers[event] = callback
            return lambda: None
        def fire(event, data):
            handlers["pixora_thermostat_voice_reply"](NS(data={"request_id": data["request_id"], "unmanaged": True}))
        hass = NS(bus=NS(async_listen=listen, async_fire=fire))
        command = {"service": "set_temperature", "data": {"entity_id": "climate.living", "temperature": 72}}
        self.assertIsNone(await bridge.route(hass, command))
        async def timeout(future, seconds):
            future.cancel(); raise asyncio.TimeoutError()
        hass.bus.async_fire = lambda *args: None
        with patch.object(bridge.asyncio, "wait_for", timeout):
            self.assertIn("haven't sent a direct", await bridge.route(hass, command))

class SpeechReadinessTests(unittest.IsolatedAsyncioTestCase):
 async def test_startup_ready_is_not_finished_training(self):
  import importlib.util
  spec=importlib.util.spec_from_file_location('speech_readiness',Path(__file__).resolve().parents[1]/'pixora_voice/custom_components/pixora_voice/speech_training.py')
  module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  self.assertFalse(module.logs_ready('old Finished training: en\nINFO:root: Ready\nStarted training: en'))
  self.assertTrue(module.logs_ready('INFO:root: Ready\nStarted training: en\nFinished training: en'))
  values=iter([{'ready':True,'generation':'old'},{'ready':False,'generation':'old'},{'ready':True,'generation':'new'}])
  async def read(hass):return next(values)
  from unittest.mock import AsyncMock
  self.assertTrue(await module.wait_ready(None,read=read,sleep=AsyncMock(),previous='old'))
