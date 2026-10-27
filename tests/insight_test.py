"""Local Insight regressions. No real HA, devices, credentials or cloud."""
import asyncio
import copy
import importlib.util
import json
import sqlite3
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pixora_insight"))
from model import Catalog, normalize, projection, validate_settings, EVENTS
from store import Store
from collector import Collector, system_event
spec = importlib.util.spec_from_file_location("insight_app", Path(__file__).resolve().parents[1]/"pixora_insight/app.py")
app_module = importlib.util.module_from_spec(spec); spec.loader.exec_module(app_module)
addon_spec = importlib.util.spec_from_file_location("insight_connector", Path(__file__).resolve().parents[1]/"pixora_home_control/app.py")
addon = importlib.util.module_from_spec(addon_spec); addon_spec.loader.exec_module(addon)
from aiohttp import web, WSMsgType


def event(kind="state_changed", context="device-context", parent="", **data):
    return {"event_type": kind, "time_fired": datetime.now(timezone.utc).isoformat(),
            "context": {"id": context, "parent_id": parent, "user_id": None}, "data": data}


def changed(ident="light.kitchen", before="off", after="on", **kwargs):
    old = {"entity_id": ident, "state": before, "attributes": {"friendly_name": "Kitchen light"}}
    new = {"entity_id": ident, "state": after, "attributes": {"friendly_name": "Kitchen light"}}
    return event(entity_id=ident, old_state=old, new_state=new, **kwargs)


def route(app, method, path):
    return next(r.handler for r in app.router.routes() if r.method == method and r.resource.canonical == path)


class Models(unittest.TestCase):
    def setUp(self): self.catalog = Catalog()

    def test_state_and_allowlisted_attribute_changes(self):
        raw = changed()
        row = normalize(raw, self.catalog)
        self.assertIn("off → on", row["title"])
        raw["data"]["new_state"]["state"] = "off"
        self.assertIsNone(normalize(raw, self.catalog))
        raw["data"]["new_state"]["attributes"]["brightness"] = 100
        self.assertEqual(normalize(raw, self.catalog)["details"]["after"]["attributes"]["brightness"], 100)

    def test_no_raw_payload_credentials_or_location_attributes(self):
        raw = changed()
        raw["data"]["new_state"]["attributes"].update(access_token="SECRET", latitude=42.1, longitude=-71.2, entity_picture="private.jpg", code="1234", message="PRIVATE")
        dumped = json.dumps(normalize(raw, self.catalog))
        for value in ("SECRET", "42.1", "71.2", "private.jpg", "1234", "PRIVATE"):
            self.assertNotIn(value, dumped)
        raw = event("call_service", domain="notify", service="phone", service_data={"message": "SECRET", "data": {"token": "SECRET"}})
        self.assertNotIn("SECRET", json.dumps(normalize(raw, self.catalog)))

    def test_free_text_state_is_omitted_but_change_is_recorded(self):
        row = normalize(changed("input_text.private", "before secret", "after secret"), self.catalog)
        self.assertNotIn("before secret", json.dumps(row))
        self.assertNotIn("after secret", json.dumps(row))
        self.assertIn("contents omitted", row["title"])

    def test_sensitive_named_numeric_entity_is_redacted(self):
        row = normalize(changed("sensor.latitude", "42.123456", "42.123457"), self.catalog)
        self.assertNotIn("42.123", json.dumps(row))

    def test_device_and_area_target_resolution(self):
        self.catalog.registry = {"light.kitchen": {"device_id": "device1", "area_id": None}, "light.bedroom": {"device_id": "device2", "area_id": "bedroom"}}
        self.catalog.devices = {"device1": {"area_id": "kitchen"}}
        raw = event("call_service", domain="light", service="turn_on", service_data={}, target={"area_id": "kitchen"})
        self.assertEqual(normalize(raw, self.catalog)["entities"], ["light.kitchen"])
        raw["data"]["target"] = {"device_id": "device2"}
        self.assertEqual(normalize(raw, self.catalog)["entities"], ["light.bedroom"])

    def test_domain_wide_target_not_guessed(self):
        row = normalize(event("call_service", domain="light", service="turn_off", service_data={"entity_id": "all"}), self.catalog)
        self.assertEqual(row["details"]["targets"]["entity_id"], ["all"])
        self.assertFalse(row["entities"])

    def test_custom_decision_contract_is_allowlisted(self):
        row = normalize(event("pixora_insight", entity_id="climate.hall", source="Thermostat", reason="Window open", outcome="blocked", password="SECRET"), self.catalog)
        self.assertEqual(row["details"]["outcome"], "blocked")
        self.assertNotIn("SECRET", json.dumps(row))
        self.assertIsNone(normalize(event("pixora_insight", reason="x"), self.catalog))

    def test_bad_shapes_and_irrelevant_events(self):
        for raw in (None, [], {}, event("unrelated"), {"event_type": "state_changed", "data": []}):
            self.assertIsNone(normalize(raw, self.catalog))
        self.catalog.state({"entity_id": "light.test", "attributes": []})
        self.assertIn("light.test", self.catalog.entities)

    def test_settings_limits_and_exclusions(self):
        good = {"days": 7, "limit": 20000, "excluded": ["sensor.noisy", "sensor.noisy"]}
        self.assertEqual(validate_settings(good)["excluded"], ["sensor.noisy"])
        for key, value in (("days", True), ("limit", 1000000), ("excluded", ["bad id"])):
            bad = {**good, key: value}
            with self.assertRaises(ValueError): validate_settings(bad)


class Journal(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name); self.addCleanup(self.store.close)
        self.catalog = Catalog()

    def put(self, raw): self.store.append([normalize(raw, self.catalog)])

    def test_context_chain_links_automation_command_and_sensor_trigger(self):
        self.put(changed("binary_sensor.motion", "off", "on", context="sensor"))
        self.put(event("automation_triggered", context="run", parent="sensor", entity_id="automation.kitchen", name="Kitchen motion"))
        self.put(event("call_service", context="run", parent="sensor", domain="light", service="turn_on", service_data={"entity_id": "light.kitchen"}))
        self.put(changed(context="run", parent="sensor"))
        result = self.store.explain(self.store.query()["events"][0]["id"])
        self.assertIn("Kitchen motion", result["answer"])
        self.assertIn("turn on", result["answer"])
        self.assertEqual({row["kind"] for row in result["evidence"]}, {"state_changed", "automation_triggered", "call_service"})

    def test_temporal_nearby_commands_do_not_establish_cause(self):
        self.put(event("call_service", context="other", domain="light", service="turn_on", service_data={"entity_id": "light.kitchen"}))
        self.put(changed())
        result = self.store.explain(2)
        self.assertIn("unknown", result["answer"])
        self.assertFalse(result["evidence"])

    def test_shared_context_different_target_is_not_cause(self):
        self.put(event("call_service", domain="light", service="turn_on", service_data={"entity_id": "light.bedroom"}))
        self.put(changed())
        self.assertIn("unknown", self.store.explain(2)["answer"])

    def test_request_alone_never_claims_success(self):
        self.put(event("call_service", domain="light", service="turn_on", service_data={"entity_id": "light.kitchen"}))
        self.assertIn("does not confirm", self.store.explain(1)["answer"])

    def test_retention_and_row_limits_cascade_targets(self):
        self.store.save_settings({"days": 1, "limit": 1000, "excluded": []})
        old = normalize(changed(), self.catalog); old["at"] = (datetime.now(timezone.utc)-timedelta(days=2)).isoformat()
        row = normalize(changed(), self.catalog)
        self.store.append([old]+[row]*1005)
        self.assertEqual(self.store.stats()["count"], 1000)
        with self.store.lock:
            self.assertEqual(self.store.db.execute("SELECT count(*) FROM targets").fetchone()[0], 1000)

    def test_exclusions_mixed_commands_and_literal_search(self):
        self.store.save_settings({"days": 7, "limit": 1000, "excluded": ["light.kitchen"]})
        self.put(changed())
        self.put(event("call_service", domain="light", service="turn_off", service_data={"entity_id": ["light.kitchen", "light.bedroom"]}))
        self.assertEqual(self.store.stats()["count"], 0)
        self.put(changed("light.bedroom"))
        self.assertEqual(len(self.store.query(entity="light.bedroom")["events"]), 1)
        self.assertFalse(self.store.query(search="%' OR 1=1 --")["events"])

    def test_single_exclusion_preserves_settings_history_and_is_idempotent(self):
        self.put(changed())
        self.store.save_settings({"days": 3, "limit": 1000, "excluded": ["sensor.other"]})
        self.store.exclude("light.kitchen")
        settings = self.store.exclude("light.kitchen")
        self.assertEqual(settings, {"days": 3, "limit": 1000, "excluded": ["light.kitchen", "sensor.other"]})
        self.put(changed())
        self.assertEqual(self.store.stats()["count"], 1)
        with self.assertRaises(ValueError): self.store.exclude("invalid")

    def test_app_display_exclusion_preserves_history_and_other_displays(self):
        def report(target, source="Pixora LED Studio"):
            return event("pixora_insight", source=source, reason="Card requested", outcome="requested", operation="pixora_led_studio.card", target_name=target)
        self.put(report("Center-128"))
        self.store.exclude("app-target:Pixora LED Studio / Center-128")
        self.put(report("Center-128"))
        self.put(report("Right"))
        self.put(report("Center-128", "Another app"))
        self.assertEqual(self.store.stats()["count"], 3)
        other = Store(self.temp.name)
        try:
            self.assertIn("app-target:Pixora LED Studio / Center-128", other.settings["excluded"])
            other.append([normalize(report("Center-128"), self.catalog)])
            self.assertEqual(other.stats()["count"], 3)
        finally: other.close()
        self.store.save_settings({**self.store.settings, "excluded": []})
        self.put(report("Center-128"))
        self.assertEqual(self.store.stats()["count"], 4)

    def test_device_exclusion_covers_entities_and_restore(self):
        self.catalog.registry = {"light.kitchen": {"device_id": "device-a"}, "sensor.power": {"device_id": "device-a"}}
        self.store.exclude("device:device-a")
        self.put(changed())
        self.put(changed("sensor.power"))
        self.put(changed("light.other"))
        self.assertEqual(self.store.stats()["count"], 1)
        self.catalog.registry["sensor.new"] = {"device_id": "device-a"}
        self.put(changed("sensor.new"))
        self.assertEqual(self.store.stats()["count"], 1)
        self.store.exclude("device:device-a", restore=True)
        self.put(changed("sensor.new"))
        self.assertEqual(self.store.stats()["count"], 2)
        self.store.exclude("sensor.new")
        self.store.exclude("sensor.new", restore=True)
        self.put(changed("sensor.new"))
        self.assertEqual(self.store.stats()["count"], 3)

    def test_housekeeping_hidden_but_recording_gaps_remain_visible(self):
        self.store.append([
            system_event("An entity, device or display was excluded from future recording. Earlier records expire normally."),
            system_event("An entity was excluded from future recording. Earlier records expire normally."),
            system_event("Recording restored for an exclusion."),
            system_event("Retention or exclusions changed. Exclusions affect future recording; retained earlier events expire normally."),
            system_event("Recording gap: connection interrupted."),
        ])
        for kind in ("", "coverage"):
            rows = self.store.query(kind=kind)["events"]
            self.assertEqual(len(rows), 1)
            self.assertIn("Recording gap", rows[0]["title"])
        self.assertEqual(self.store.stats()["count"], 5)

    def test_pagination_and_restart_persistence(self):
        self.store.append([normalize(changed(), self.catalog)]*55)
        first = self.store.query(); second = self.store.query(before=first["next"])
        self.assertEqual(len(first["events"]), 50)
        self.assertEqual(len(second["events"]), 5)
        other = Store(self.temp.name)
        try: self.assertEqual(other.stats()["count"], 55)
        finally: other.close()

    def test_full_budget_recovery_discards_oldest_not_retries(self):
        self.store.append([normalize(changed(), self.catalog)]*1010)
        self.store.make_room()
        self.assertEqual(self.store.stats()["count"], 10)

    def test_expired_event_ids_are_never_reused(self):
        self.put(changed())
        self.store.make_room()
        self.put(changed())
        self.assertIsNone(self.store.explain(1))
        self.assertEqual(self.store.query()["events"][0]["id"], 2)

    def test_late_explicit_flow_origin_explains_existing_device_change(self):
        context = "01EXACTFLOWCOMMANDCONTEXT01"
        self.put(changed(context=context))
        self.put(event("pixora_insight", context="different-event-context", entity_id="light.kitchen", source="Pixora Flow", outcome="requested", reason="Kitchen motion triggered Flow Kitchen Motion Lights, which requested this light action.", action_context=context))
        result = self.store.explain(1)
        self.assertIn("Kitchen motion triggered Flow Kitchen Motion Lights", result["answer"])
        self.assertEqual(result["evidence"][0]["kind"], "pixora_insight")

    def test_flow_origin_matches_an_explicit_parent_context(self):
        context = "01EXACTFLOWCOMMANDCONTEXT01"
        self.put(changed(context="integration-child", parent=context))
        self.put(event("pixora_insight", entity_id="light.kitchen", source="Pixora Flow", outcome="requested", reason="Kitchen Motion Lights requested this action.", action_context=context))
        self.assertIn("Kitchen Motion Lights", self.store.explain(1)["answer"])

    def test_flow_origin_for_another_entity_is_not_used(self):
        context = "01EXACTFLOWCOMMANDCONTEXT01"
        self.put(changed(context=context))
        self.put(event("pixora_insight", entity_id="light.bedroom", source="Pixora Flow", outcome="requested", reason="Other Flow", action_context=context))
        self.assertIn("unknown", self.store.explain(1)["answer"])

    def test_indirect_scene_origin_uses_exact_context_not_guessed_targets(self):
        context = "01EXACTSCENECOMMANDCONTEXT1"
        self.put(changed(context=context))
        self.put(event("pixora_insight", entity_id="scene.evening", source="Pixora Voice", outcome="requested", operation="scene.turn_on", reason="Voice requested the evening scene.", action_context=context))
        self.assertIn("Voice requested the evening scene", self.store.explain(1)["answer"])

    def test_operation_without_entity_records_direct_panel_source(self):
        self.put(event("pixora_insight", source="Pixora LED Studio", operation="pixora_led_studio.card", target_name="Kitchen panel", outcome="requested", reason="Deck card requested."))
        row = self.store.query()["events"][0]
        self.assertIn("Kitchen panel", row["title"])
        self.assertEqual(row["details"]["source"], "Pixora LED Studio")

    def test_later_command_and_ambiguous_requests_are_not_single_causes(self):
        state = normalize(changed(), self.catalog)
        self.store.append([state])
        later = normalize(event("call_service", domain="light", service="turn_on", service_data={"entity_id": "light.kitchen"}), self.catalog)
        later["at"] = (datetime.now(timezone.utc)+timedelta(seconds=10)).isoformat()
        self.store.append([later])
        self.assertIn("unknown", self.store.explain(1)["answer"])
        self.store.append([normalize(event("call_service", domain="light", service="turn_off", service_data={"entity_id": "light.kitchen"}), self.catalog)])
        last = normalize(changed(), self.catalog)
        last["at"] = (datetime.now(timezone.utc)+timedelta(seconds=20)).isoformat()
        self.store.append([last])
        self.assertIn("ambiguous", self.store.explain(4)["answer"])


class AsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_unexpected_reporting_error_does_not_end_connector_worker(self):
        connector = addon.Connector()
        local = NS(request=AsyncMock(side_effect=RuntimeError('session unavailable')))
        connector.insight.put_nowait((time.monotonic(), {'reason':'First'}))
        connector.insight.put_nowait((time.monotonic(), {'reason':'Second'}))
        task = asyncio.create_task(connector.send_insight(local))
        try:
            for _ in range(30):
                if local.request.await_count == 2:break
                await asyncio.sleep(.01)
            self.assertEqual(local.request.await_count,2)
            self.assertFalse(task.done())
        finally:
            task.cancel();await asyncio.gather(task,return_exceptions=True)
    async def test_connector_keeps_exact_command_context_and_deduplicates_action(self):
        connector = addon.Connector()
        origin = {"source": "Pixora Flow", "reason": "Kitchen motion triggered Flow Kitchen Motion Lights."}
        payload = {"entity_id": "light.kitchen"}
        local = NS(query=AsyncMock(return_value={"context": {"id": "01EXACTFLOWCOMMANDCONTEXT01"}}), request=AsyncMock())
        cloud = NS(send_json=AsyncMock())
        command = {"id": "a"*32, "path": "/api/services/light/turn_on", "method": "POST", "payload": payload, "expiresAt": time.time()+10, "insight": origin}
        await connector.execute(local, cloud, command)
        await connector.execute(local, cloud, command)
        local.query.assert_awaited_once_with('call_service', domain='light', service='turn_on', service_data=payload)
        local.request.assert_not_awaited()
        _, report = connector.insight.get_nowait()
        self.assertEqual(report["action_context"], "01EXACTFLOWCOMMANDCONTEXT01")
        self.assertEqual(payload, {"entity_id": "light.kitchen"})
        self.assertTrue(cloud.send_json.call_args.args[0]["ok"])

    async def test_origin_failure_does_not_fail_or_retry_device_action(self):
        connector = addon.Connector()
        connector.record_flow_origin = lambda *args: (_ for _ in ()).throw(RuntimeError("trace failed"))
        local = NS(query=AsyncMock(return_value={"context": {"id": "01EXACTFLOWCOMMANDCONTEXT01"}}))
        cloud = NS(send_json=AsyncMock())
        command = {"id": "b"*32, "path": "/api/services/light/turn_on", "method": "POST", "payload": {"entity_id": "light.kitchen"}, "expiresAt": time.time()+10, "insight": {"source": "Pixora Flow", "reason": "Motion"}}
        await connector.execute(local, cloud, command)
        self.assertTrue(cloud.send_json.call_args.args[0]["ok"])
        self.assertEqual(local.query.await_count, 1)

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name); self.addCleanup(self.store.close)
        self.collector = Collector(None, "", self.store)

    async def test_queue_overflow_is_bounded_and_visible(self):
        for _ in range(2050): self.collector.enqueue(system_event("Test"))
        self.assertEqual(self.collector.queue.qsize(), 2048)
        self.assertEqual(self.collector.pending_loss, 2)

    async def test_writer_persists_gap_without_raw_events(self):
        self.collector.pending_loss = 3
        self.collector.receive_event(changed())
        task = asyncio.create_task(self.collector.writer())
        try:
            for _ in range(30):
                if self.collector.recorded: break
                await asyncio.sleep(.05)
            self.assertEqual(self.store.stats()["count"], 2)
            self.assertIn("Recording gap", self.store.query()["events"][-1]["title"])
        finally:
            task.cancel(); await asyncio.gather(task, return_exceptions=True)

    async def test_storage_failure_is_visible_and_batch_not_retried(self):
        self.store.append = lambda rows: (_ for _ in ()).throw(sqlite3.OperationalError("full"))
        self.collector.enqueue(system_event("Test"))
        task = asyncio.create_task(self.collector.writer())
        try:
            for _ in range(30):
                if self.collector.storage_error: break
                await asyncio.sleep(.05)
            self.assertEqual(self.collector.dropped, 1)
            self.assertTrue(self.collector.queue.empty())
        finally:
            task.cancel(); await asyncio.gather(task, return_exceptions=True)

    async def test_ingress_and_csrf_reject_direct_access(self):
        app = app_module.make_app(Path(self.temp.name)/"api", self.collector)
        self.addCleanup(app["store"].close)
        guard = app.middlewares[0]; handler = AsyncMock(return_value=web.Response())
        with self.assertRaises(web.HTTPForbidden): await guard(NS(remote="127.0.0.1", method="GET"), handler)
        with self.assertRaises(web.HTTPForbidden):
            await guard(NS(remote="172.30.32.2", method="POST", headers={"X-Pixora-Request": "1", "Origin": "https://evil.test"}, host="ha.local"), handler)
        handler.assert_not_awaited()

    async def test_api_read_routes_and_no_command_endpoint(self):
        app = app_module.make_app(Path(self.temp.name)/"api", self.collector)
        self.addCleanup(app["store"].close)
        response = await route(app, "GET", "/api/status")(NS())
        data = json.loads(response.text)
        self.assertNotIn("token", data)
        response = await route(app, "GET", "/api/events")(NS(query={"search": "test"}))
        self.assertEqual(json.loads(response.text)["events"], [])
        posts = [r.resource.canonical for r in app.router.routes() if r.method == "POST"]
        self.assertEqual(posts, ["/api/settings", "/api/exclude"])

    async def test_exclude_endpoint_merges_only_one_entity(self):
        app = app_module.make_app(Path(self.temp.name)/"api", self.collector)
        self.addCleanup(app["store"].close)
        response = await route(app, "POST", "/api/exclude")(NS(json=AsyncMock(return_value={"entity": "sensor.distance"})))
        self.assertIn("sensor.distance", json.loads(response.text)["settings"]["excluded"])
        with self.assertRaises(ValueError):
            await route(app, "POST", "/api/exclude")(NS(json=AsyncMock(return_value={"entity": "sensor.other", "days": 1})))

    async def test_websocket_subscriptions_and_registry_refresh_use_unique_increasing_ids(self):
        sent, clock = [], [0]
        connected = asyncio.Event()
        class Socket:
            def __init__(self): self.auth = 0
            async def __aenter__(self): return self
            async def __aexit__(self, *args): return False
            async def receive_json(self):
                self.auth += 1
                return {"type": "auth_required" if self.auth == 1 else "auth_ok"}
            async def send_json(self, value): sent.append(value)
            def __aiter__(self): return self.messages()
            async def messages(self):
                for ident in range(1, len(EVENTS)+1):
                    yield NS(type=WSMsgType.TEXT, data=json.dumps({"type": "result", "id": ident, "success": True, "result": None}))
                yield NS(type=WSMsgType.TEXT, data=json.dumps({"type": "result", "id": 20, "success": True, "result": []}))
                for ident in (21, 22, 23):
                    yield NS(type=WSMsgType.TEXT, data=json.dumps({"type": "result", "id": ident, "success": True, "result": []}))
                clock[0] = 31
                yield NS(type=WSMsgType.TEXT, data=json.dumps({"type": "event", "event": {"event_type": "entity_registry_updated", "data": {}}}))
                for ident in (100, 101, 102):
                    yield NS(type=WSMsgType.TEXT, data=json.dumps({"type": "result", "id": ident, "success": True, "result": []}))
                connected.set()
                await asyncio.Event().wait()
        socket = Socket()
        self.collector.session = NS(ws_connect=lambda *args, **kwargs: socket)
        self.collector.token = "test-local-token"
        self.collector.monotonic = lambda: clock[0]
        task = asyncio.create_task(self.collector.listen())
        try:
            await asyncio.wait_for(connected.wait(), timeout=2)
            ids_sent = [r["id"] for r in sent if "id" in r]
            self.assertEqual(ids_sent, sorted(set(ids_sent)))
            self.assertTrue(self.collector.connected)
            self.assertTrue(self.collector.registry_ready)
            self.assertFalse(any(r.get("type") == "call_service" for r in sent))
        finally:
            task.cancel(); await asyncio.gather(task, return_exceptions=True)


if __name__ == "__main__": unittest.main()
