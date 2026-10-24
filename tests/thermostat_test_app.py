"""Ingress access, API revision validation, and real HA event transport shape."""
import asyncio
import copy
import json
import sys
import tempfile
import unittest
import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from aiohttp import web, WSMsgType
from aiohttp.test_utils import make_mocked_request
from thermostat_test_controller import FakeHA, zone
_spec = importlib.util.spec_from_file_location("thermostat_controller_app", Path(__file__).resolve().parents[1] / "pixora_thermostat_controller" / "app.py")
_app = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_app)
make_app = _app.make_app
from engine import Engine
from ha import HomeAssistant


def route(app, method, path):
    return next(r.handler for r in app.router.routes() if r.method == method and r.resource.canonical == path)


def request(body):
    return NS(json=AsyncMock(return_value=body))


class AppTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.ha = FakeHA(); self.app = make_app(Path(self.temp.name), self.ha)
        self.app["ha"] = self.ha; self.app["engine"] = Engine(self.app["store"], self.ha)

    async def save(self, z=None, revision=0):
        return await route(self.app, "POST", "/api/settings")(request({"revision": revision, "zones": [z or zone()]}))

    async def test_ingress_and_csrf_guards(self):
        gate = self.app.middlewares[0]; handler = AsyncMock(return_value=web.json_response({"ok": True}))
        with self.assertRaises(web.HTTPForbidden):
            await gate(NS(remote="127.0.0.1", method="GET"), handler)
        for headers in ({}, {"X-Pixora-Request": "1", "Origin": "https://evil.invalid"}):
            with self.assertRaises(web.HTTPForbidden):
                await gate(NS(remote="172.30.32.2", method="POST", headers=headers, host="homeassistant.local"), handler)
        handler.assert_not_awaited()
        response = await gate(NS(remote="172.30.32.2", method="POST", headers={"X-Pixora-Request": "1", "Origin": "http://homeassistant.local"}, host="homeassistant.local"), handler)
        self.assertEqual(response.status, 200); self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])

    async def test_save_revision_and_reload(self):
        response = await self.save(); self.assertEqual(response.status, 200)
        response = await self.save(); self.assertEqual(response.status, 409)
        reloaded = make_app(Path(self.temp.name), self.ha)
        self.assertEqual(reloaded["store"].data["zones"][0]["entity"], "climate.living")

    async def test_invalid_live_ranges_never_save_or_send(self):
        z = zone(); z["schedule"][0]["heat"] = 100
        with self.assertRaises(ValueError): await self.save(z)
        self.assertEqual(self.app["store"].data["revision"], 0); self.assertFalse(self.ha.calls)
        z = zone(); z["openings"] = ["binary_sensor.motion"]
        with self.assertRaises(ValueError): await self.save(z)
        self.assertFalse(self.ha.calls)

    async def test_save_preserves_unmodified_contact_observation(self):
        z = zone(); await self.save(z)
        engine = self.app["engine"]
        self.ha.states["binary_sensor.window"]["state"] = "on"
        await engine.tick()
        started = engine.timers[z["id"]]["contacts"]["binary_sensor.window"]["at"]
        z["name"] = "Renamed room"
        await self.save(z, revision=1)
        self.assertEqual(engine.timers[z["id"]]["contacts"]["binary_sensor.window"]["at"], started)
        z["openMinutes"] = 5
        await self.save(z, revision=2)
        self.assertGreaterEqual(engine.timers[z["id"]]["contacts"]["binary_sensor.window"]["at"], started)

    async def test_restore_disables_and_clears_runtime(self):
        await self.save()
        store = self.app["store"]
        store.patch_runtime("living", {"override": {"target": {"mode": "heat", "heat": 72}, "until": "2027-01-01T00:00:00+00:00"}})
        count = len(self.ha.calls)
        result = await route(self.app, "POST", "/api/settings")(request({"revision": 1, "zones": [zone()], "restore": True}))
        self.assertEqual(result.status, 200)
        self.assertFalse(store.data["zones"][0]["enabled"])
        self.assertEqual(store.data["runtime"], {})
        self.assertEqual(len(self.ha.calls), count)

    async def test_vacation_date_validation_and_expiry(self):
        from datetime import timedelta
        await self.save()
        now = self.app["engine"].now()
        data = {"id": "living", "action": "override", "target": {"mode": "heat", "heat": 65}, "minutes": 120, "until": (now + timedelta(days=3)).isoformat()}
        action = route(self.app, "POST", "/api/action")
        await action(request(data))
        self.assertEqual(self.app["store"].data["runtime"]["living"]["override"]["until"], data["until"])
        with self.assertRaises(ValueError): await action(request({**data, "until": (now - timedelta(days=1)).isoformat()}))

    async def test_disabled_setup_never_sends_commands(self):
        z = zone(); z["enabled"] = False
        self.ha.states["climate.living"]["attributes"]["temperature"] = 65
        await self.save(z); self.assertFalse(self.ha.calls)

    async def test_override_capability_validation_and_expiry(self):
        z = zone(); z["schedule"] = [{**z["schedule"][0], "days": list(range(7)), "time": "00:00"}]
        await self.save(z)
        action = route(self.app, "POST", "/api/action")
        with self.assertRaises(ValueError):
            await action(request({"id": "living", "action": "override", "target": {"mode": "heat", "heat": 100}, "minutes": 60}))
        await action(request({"id": "living", "action": "override", "target": {"mode": "heat", "heat": 72}, "minutes": 60}))
        self.assertEqual(self.app["store"].data["runtime"]["living"]["override"]["target"]["heat"], 72)
        self.assertEqual(self.ha.device_calls()[-1][1]["temperature"], 72)

    async def test_action_tokens_stay_out_of_ui(self):
        data = copy.deepcopy(self.app["store"].data)
        data["runtime"]["living"] = {"approval": {"token": "secret-action-token", "decision": "pending", "until": "2026-10-24T20:00:00+00:00"}}
        self.app["store"].write(data)
        response = await route(self.app, "GET", "/api/status")(request(None))
        self.assertNotIn("secret-action-token", response.text)

    async def test_settings_invalidate_old_yes_after_disable(self):
        z = zone(); z["outdoor"].update(enabled=True, mode="ask")
        self.ha.states["sensor.outdoor"]["state"] = "60"
        await self.save(z)
        token = self.app["store"].data["runtime"]["living"]["approval"]["token"]
        z["enabled"] = False; await self.save(z, revision=1)
        self.assertNotIn("approval", self.app["store"].data["runtime"]["living"])
        self.ha.actions.put_nowait("pixora_thermostat:" + token + ":yes")
        await self.app["engine"].tick(); self.assertFalse(self.ha.device_calls())


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_action_event_reaches_bounded_queue(self):
        closed = asyncio.Event()
        class Socket:
            def __init__(self): self.sent = []; self.auth = 0
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def receive_json(self):
                self.auth += 1; return {"type": "auth_required" if self.auth == 1 else "auth_ok"}
            async def send_json(self, value): self.sent.append(value)
            def __aiter__(self): return self.packets()
            async def packets(self):
                for packet in [{"id": 1, "type": "result", "success": True}, {"id": 2, "type": "result", "success": True, "result": []}, {"type": "event", "event": {"event_type": "mobile_app_notification_action", "data": {"action": "pixora_thermostat:example:yes"}}}]:
                    yield NS(type=WSMsgType.TEXT, data=json.dumps(packet))
                closed.set(); await asyncio.Event().wait()
        socket = Socket(); session = NS(ws_connect=lambda *a, **k: socket)
        ha = HomeAssistant(session, "not-a-real-token")
        ha.request = AsyncMock(side_effect=[{"time_zone": "America/New_York", "unit_system": {"temperature": "\u00b0F"}}, []])
        task = asyncio.create_task(ha.listen())
        try:
            await asyncio.wait_for(closed.wait(), 2)
            self.assertEqual(ha.actions.get_nowait(), "pixora_thermostat:example:yes")
            self.assertTrue(ha.connected)
            self.assertIn({"id": 3, "type": "subscribe_events", "event_type": "mobile_app_notification_action"}, socket.sent)
        finally:
            task.cancel(); await asyncio.gather(task, return_exceptions=True)

    async def test_cached_catalog_discards_unrelated_sensors_and_attributes(self):
        ha = HomeAssistant(None, "")
        ha.update({"entity_id": "sensor.power", "state": "30", "attributes": {"device_class": "power", "huge": "x" * 1000}})
        self.assertFalse(ha.states)
        ha.update({"entity_id": "sensor.outdoor", "state": "30", "attributes": {"device_class": "temperature", "unit_of_measurement": "\u00b0F", "huge": "x" * 1000}})
        self.assertNotIn("huge", ha.states["sensor.outdoor"]["attributes"])


if __name__ == "__main__": unittest.main()
