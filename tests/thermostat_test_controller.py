"""Local controller regressions. No live thermostat or notification actions."""
import asyncio
import copy
import json
import sys
import tempfile
import unittest
import time
from unittest.mock import AsyncMock
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pixora_thermostat_controller"))
from policy import validate, schedule_at, next_period, service_for, temperature, same
from engine import Store, Engine


def zone():
    return {"id": "living", "name": "Living room", "entity": "climate.living", "unit": "F", "enabled": True,
            "openMinutes": 3, "closeMinutes": 1, "setback": 60, "manualMinutes": 120, "openings": ["binary_sensor.window"],
            "outdoor": {"enabled": False, "entity": "sensor.outdoor", "limit": 50, "margin": 2, "mode": "auto"},
            "notify": {"person": "Bryan", "service": "notify.mobile_app_bryan"},
            "schedule": [{"id": "day", "time": "06:00", "days": list(range(7)), "mode": "heat", "heat": 70},
                         {"id": "night", "time": "22:00", "days": list(range(7)), "mode": "heat", "heat": 64}]}


class FakeHA:
    def __init__(self):
        self.connected, self.timezone, self.unit, self.notice = True, "America/New_York", "F", ""
        self.actions = asyncio.Queue()
        self.services = {"climate.set_temperature", "climate.set_hvac_mode", "notify.mobile_app_bryan"}
        self.states = {
            "climate.living": {"entity_id": "climate.living", "state": "heat", "attributes": {"temperature": 70, "current_temperature": 68, "temperature_unit": "\u00b0F", "min_temp": 45, "max_temp": 90, "hvac_modes": ["heat", "cool", "heat_cool", "off"], "supported_features": 387}},
            "binary_sensor.window": {"entity_id": "binary_sensor.window", "state": "off", "attributes": {"friendly_name": "Living room window", "device_class": "window"}},
            "sensor.outdoor": {"entity_id": "sensor.outdoor", "state": "40", "attributes": {"unit_of_measurement": "\u00b0F", "device_class": "temperature"}}}
        self.calls, self.fail = [], False

    async def call(self, service, fields):
        self.calls.append((service, copy.deepcopy(fields)))
        if self.fail:
            raise ValueError("Uncertain result")
        if service.startswith("climate."):
            s = self.states[fields["entity_id"]]
            s["state"] = fields["hvac_mode"]
            s["attributes"].update({k: v for k, v in fields.items() if k not in {"entity_id", "hvac_mode"}})

    def device_calls(self):
        return [c for c in self.calls if c[0].startswith("climate.")]

    def notifications(self):
        return [c for c in self.calls if c[0].startswith("notify.")]


class PolicyTests(unittest.TestCase):
    def test_validation_defaults_and_duplicate_ownership(self):
        z = zone()
        validate({"zones": [z]})
        other = {**copy.deepcopy(z), "id": "other"}
        with self.assertRaises(ValueError):
            validate({"zones": [z, other]})

    def test_invalid_values_and_notification_binding(self):
        for patch in ({"openMinutes": True}, {"setback": float("nan")}, {"enabled": "yes"}, {"unit": "K"}, {"schedule": []}):
            z = zone(); z.update(patch)
            with self.assertRaises(ValueError): validate({"zones": [z]})
        z = zone(); z["outdoor"].update(enabled=True, mode="ask"); z["notify"]["service"] = "notify.broadcast"
        with self.assertRaises(ValueError): validate({"zones": [z]})

    def test_weekly_schedule_overnight_and_next_period(self):
        z = zone(); now = datetime(2026, 10, 26, 8, tzinfo=timezone.utc)  # Monday 4am.
        self.assertEqual(schedule_at(z["schedule"], now, "America/New_York")["id"], "night")
        self.assertEqual(next_period(z["schedule"], now, "America/New_York").hour, 10)
        self.assertEqual(schedule_at(z["schedule"], now.replace(hour=16), "America/New_York")["id"], "day")

    def test_dst_skips_nonexistent_period(self):
        rows = [{"id": "spring", "time": "02:30", "days": [6], "mode": "off"}]
        now = datetime(2026, 3, 8, 6, tzinfo=timezone.utc)
        self.assertEqual(next_period(rows, now, "America/New_York").day, 15)

    def test_units_capabilities_and_bounds(self):
        ha = FakeHA(); s = ha.states["climate.living"]
        service, data = service_for({"mode": "heat", "heat": 70}, s, "F", "F", ha.services)
        self.assertEqual(service, "climate.set_temperature"); self.assertEqual(data["entity_id"], "climate.living")
        for wanted, unit in (({"mode": "heat", "heat": 100}, "F"), ({"mode": "heat", "heat": 70}, "C")):
            with self.assertRaises(ValueError): service_for(wanted, s, unit, "F", ha.services)
        source = copy.deepcopy(ha.states["sensor.outdoor"]); source.update(state="10"); source["attributes"]["unit_of_measurement"] = "\u00b0C"
        self.assertEqual(temperature(source, "F"), 50)
        source["state"] = "unavailable"
        with self.assertRaises(ValueError): temperature(source, "F")

    def test_fall_back_does_not_rewind_or_repeat_period(self):
        rows = [{"id": "early", "time": "00:00", "days": [6], "mode": "off"},
                {"id": "later", "time": "01:30", "days": [6], "mode": "off"}]
        now = datetime(2026, 11, 1, 6, 10, tzinfo=timezone.utc)
        self.assertEqual(schedule_at(rows, now, "America/New_York")["id"], "later")
        self.assertEqual(next_period(rows, now, "America/New_York").day, 8)

    def test_native_setpoint_increment_rejected_before_send(self):
        ha = FakeHA(); state = ha.states["climate.living"]
        state["attributes"]["target_temp_step"] = 1
        with self.assertRaisesRegex(ValueError, "increments"):
            service_for({"mode": "heat", "heat": 70.5}, state, "F", "F", ha.services)
        service_for({"mode": "heat", "heat": 70}, state, "F", "F", ha.services)

    def test_period_names_validate_and_survive_copy(self):
        z = zone(); z["schedule"][0]["name"] = "Wake up"
        self.assertEqual(validate({"zones": [z]})["zones"][0]["schedule"][0]["name"], "Wake up")
        z["schedule"][0]["name"] = " "
        with self.assertRaises(ValueError): validate({"zones": [z]})

    def test_store_corruption_is_not_reset(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "controller.json"; p.write_text("bad")
            with self.assertRaises(ValueError): Store(d)
            self.assertEqual(p.read_text(), "bad")


class EngineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name); self.z = zone(); data = copy.deepcopy(self.store.data); data["zones"] = [self.z]; self.store.write(data)
        self.ha = FakeHA(); self.now = datetime(2026, 10, 24, 16, tzinfo=timezone.utc)
        self.engine = Engine(self.store, self.ha, now=lambda: self.now)

    async def tick(self, seconds=0):
        self.now += timedelta(seconds=seconds); await self.engine.tick()

    def runtime(self): return self.store.data["runtime"].get("living", {})

    def outdoor(self, mode="auto"):
        self.z["outdoor"].update(enabled=True, mode=mode)
        data = copy.deepcopy(self.store.data); data["zones"] = [self.z]; self.store.write(data)

    async def test_contact_alert_names_bad_readings_and_open_contacts(self):
        self.store.data["zones"][0]["openings"] += ["binary_sensor.front_door", "binary_sensor.missing"]
        self.ha.states["binary_sensor.window"]["state"] = "unknown"
        self.ha.states["binary_sensor.front_door"] = {"state": "on", "attributes": {"friendly_name": "Front door"}}
        await self.tick()
        message = self.ha.notifications()[-1][1]["message"]
        for text in ("Living room window (unknown)", "binary_sensor.missing (missing from Home Assistant)", "Also open: Front door"):
            self.assertIn(text, message)
            self.assertIn(text, self.engine.status["living"]["detail"])
        self.assertFalse(self.ha.device_calls())
        await self.tick()
        self.assertEqual(len(self.ha.notifications()), 1)

    async def test_open_protection_notification_names_window(self):
        self.ha.states["binary_sensor.window"]["state"] = "on"
        await self.tick()
        await self.tick(180)
        await self.tick()
        self.assertIn("Open: Living room window.", self.ha.notifications()[-1][1]["message"])
        self.assertEqual(self.ha.states["climate.living"]["attributes"]["temperature"], 60)

    async def test_new_opening_updates_active_protection_alert_without_repeat(self):
        self.store.data["zones"][0]["openings"].append("binary_sensor.door")
        self.ha.states["binary_sensor.door"] = {"state": "off", "attributes": {"friendly_name": "Kitchen door"}}
        self.ha.states["binary_sensor.window"]["state"] = "on"
        await self.tick(); await self.tick(180); await self.tick()
        count = len(self.ha.notifications())
        self.ha.states["binary_sensor.door"]["state"] = "on"
        await self.tick()
        self.assertEqual(len(self.ha.notifications()), count + 1)
        self.assertIn("Kitchen door", self.ha.notifications()[-1][1]["message"])
        self.assertIn("Living room window", self.ha.notifications()[-1][1]["message"])
        await self.tick()
        self.assertEqual(len(self.ha.notifications()), count + 1)

    async def test_approval_storage_failure_does_not_kill_loop(self):
        self.outdoor("ask"); self.ha.states["sensor.outdoor"]["state"] = "55"
        await self.tick()
        token = self.runtime()["approval"]["token"]
        self.ha.actions.put_nowait("pixora_thermostat:" + token + ":yes")
        original = self.store.write
        def failed(value):
            raise OSError("Disk unavailable")
        self.store.write = failed
        await self.tick()
        self.assertFalse(self.ha.device_calls())
        self.store.write = original
        await self.tick()
        self.assertEqual(self.runtime()["approval"]["decision"], "pending")
        self.assertFalse(self.ha.device_calls())

    async def test_voice_override_is_timed_and_window_guard_wins(self):
        self.ha.voice = asyncio.Queue(); self.ha.request = AsyncMock()
        self.ha.states["binary_sensor.window"]["state"] = "on"
        await self.tick(); await self.tick(180); await self.tick()
        req = {"request_id": "a" * 32, "expires_at": time.time() + 10, "entity_id": "climate.living", "service": "set_temperature", "temperature": 74}
        self.ha.voice.put_nowait(req); await self.tick()
        hold = self.runtime()["override"]
        self.assertEqual(hold["target"]["heat"], 74)
        self.assertEqual(datetime.fromisoformat(hold["until"]), self.now + timedelta(minutes=120))
        self.assertEqual(self.ha.states["climate.living"]["attributes"]["temperature"], 60)
        count = len(self.ha.device_calls())
        self.ha.voice.put_nowait(req); await self.tick()
        self.assertEqual(len(self.ha.device_calls()), count)
        self.ha.states["binary_sensor.window"]["state"] = "off"
        await self.tick(); await self.tick(60)
        self.assertEqual(self.ha.device_calls()[-1][1]["temperature"], 74)

    async def test_voice_outdoor_guard_and_disabled_expired_requests(self):
        self.ha.voice = asyncio.Queue(); self.ha.request = AsyncMock()
        self.outdoor(); self.ha.states["sensor.outdoor"]["state"] = "55"
        await self.tick(); await self.tick()
        req = {"request_id": "b" * 32, "expires_at": time.time() + 10, "entity_id": "climate.living", "service": "set_temperature", "temperature": 74}
        self.ha.voice.put_nowait(req); await self.tick()
        self.assertEqual(self.runtime()["override"]["target"]["heat"], 74)
        self.assertEqual(self.ha.states["climate.living"]["state"], "off")
        self.ha.voice.put_nowait({**req, "request_id": "c" * 32, "expires_at": time.time() - 1, "temperature": 76})
        await self.tick(); self.assertEqual(self.runtime()["override"]["target"]["heat"], 74)
        data = copy.deepcopy(self.store.data); data["zones"][0]["enabled"] = False; self.store.write(data)
        self.ha.voice.put_nowait({**req, "request_id": "d" * 32, "temperature": 76})
        await self.tick(); self.assertEqual(self.runtime()["override"]["target"]["heat"], 74)

    async def test_preview_has_no_real_writes_or_service_calls(self):
        await self.tick()
        self.ha.states["binary_sensor.window"]["state"] = "on"
        await self.tick(); self.now += timedelta(minutes=4)
        before = copy.deepcopy(self.store.data)
        calls = len(self.ha.calls)
        preview = await self.engine.preview(self.z)
        self.assertTrue(preview["readOnly"])
        self.assertEqual(preview["status"]["target"]["heat"], 60)
        self.assertEqual(self.store.data, before)
        self.assertEqual(len(self.ha.calls), calls)

    async def test_return_home_hold_waits_for_away_then_known_home(self):
        await self.tick()
        runtime = copy.deepcopy(self.runtime())
        runtime["override"] = {"target": {"mode": "heat", "heat": 65}, "until": datetime.max.replace(tzinfo=timezone.utc).isoformat(), "returnPerson": "person.bryan", "seenAway": False}
        self.store.patch_runtime("living", runtime)
        self.ha.states["person.bryan"] = {"state": "home"}
        await self.tick(); await self.tick()
        self.assertIsNotNone(self.runtime()["override"])
        self.ha.states["person.bryan"]["state"] = "not_home"
        await self.tick()
        self.ha.states["person.bryan"]["state"] = "unavailable"
        await self.tick(); self.assertIsNotNone(self.runtime()["override"])
        self.ha.states["person.bryan"]["state"] = "home"
        await self.tick(); self.assertIsNone(self.runtime()["override"])
        self.assertEqual(self.ha.device_calls()[-1][1]["temperature"], 70)

    async def test_sensor_alert_deduplicates_and_respects_choice(self):
        self.ha.states["binary_sensor.window"]["state"] = "unavailable"
        await self.tick(); await self.tick()
        self.assertEqual(len(self.ha.notifications()), 1)
        self.assertFalse(self.ha.device_calls())
        self.ha.states["binary_sensor.window"]["state"] = "off"
        await self.tick()
        data = copy.deepcopy(self.store.data)
        data["zones"][0]["alerts"] = {"sensor": False, "failure": True, "restore": True, "setback": True}
        self.store.write(data)
        self.ha.states["binary_sensor.window"]["state"] = "unavailable"
        await self.tick(); self.assertEqual(len(self.ha.notifications()), 1)

    async def test_voice_status_and_resume_do_not_clear_protection(self):
        self.ha.voice = asyncio.Queue(); self.ha.request = AsyncMock()
        self.outdoor(); self.ha.states["sensor.outdoor"]["state"] = "55"
        await self.tick(); await self.tick()
        runtime = copy.deepcopy(self.runtime())
        runtime["override"] = {"target": {"mode": "heat", "heat": 74}, "until": (self.now + timedelta(hours=1)).isoformat()}
        self.store.patch_runtime("living", runtime)
        base = {"expires_at": time.time() + 10, "entity_id": "climate.living"}
        self.ha.voice.put_nowait({**base, "request_id": "e" * 32, "service": "controller_status"})
        await self.tick()
        self.assertIn("Outdoor heat lockout", self.ha.request.call_args.args[1]["speech"])
        self.ha.voice.put_nowait({**base, "request_id": "f" * 32, "service": "controller_resume"})
        await self.tick()
        self.assertIsNone(self.runtime()["override"])
        self.assertTrue(self.runtime()["outdoor"])
        self.assertEqual(self.ha.states["climate.living"]["state"], "off")

    async def test_disabled_voice_status_is_read_only(self):
        self.ha.voice = asyncio.Queue(); self.ha.request = AsyncMock()
        data = copy.deepcopy(self.store.data); data["zones"][0]["enabled"] = False; self.store.write(data)
        self.ha.voice.put_nowait({"request_id": "9" * 32, "expires_at": time.time() + 10, "entity_id": "climate.living", "service": "controller_status"})
        await self.tick()
        self.assertIn("Disabled", self.ha.request.call_args.args[1]["speech"])
        self.assertFalse(self.ha.calls)
        self.assertFalse(self.store.data["zones"][0]["enabled"])

    async def test_idle_schedule_sends_no_commands(self):
        await self.tick(); await self.tick(5)
        self.assertFalse(self.ha.calls)

    async def test_open_delay_setback_notification_and_restore(self):
        await self.tick(); self.ha.states["binary_sensor.window"]["state"] = "on"
        await self.tick(); await self.tick(179); self.assertFalse(self.ha.calls)
        await self.tick(1); self.assertEqual(self.ha.device_calls()[-1][1]["temperature"], 60)
        await self.tick(); self.assertEqual(len(self.ha.notifications()), 1)
        await self.tick(30); self.assertEqual(len(self.ha.notifications()), 1)
        self.ha.states["binary_sensor.window"]["state"] = "off"
        await self.tick(); await self.tick(59); self.assertEqual(len(self.ha.device_calls()), 1)
        await self.tick(1); self.assertEqual(self.ha.device_calls()[-1][1]["temperature"], 70)
        await self.tick(); self.assertEqual(len(self.ha.notifications()), 2)

    async def test_any_contact_keeps_protection_and_unknown_never_restores(self):
        self.ha.states["binary_sensor.window"]["state"] = "on"
        await self.tick(); await self.tick(180); await self.tick()
        self.ha.states["binary_sensor.window"]["state"] = "unavailable"
        await self.tick(200)
        self.assertEqual(len(self.ha.device_calls()), 1); self.assertTrue(self.runtime()["window"])

    async def test_restart_observes_full_open_delay(self):
        self.ha.states["binary_sensor.window"]["state"] = "on"
        await self.tick(); await self.tick(100)
        self.engine = Engine(Store(self.temp.name), self.ha, now=lambda: self.now)
        await self.tick(); await self.tick(100); self.assertFalse(self.ha.device_calls())
        await self.tick(80); self.assertEqual(len(self.ha.device_calls()), 1)

    async def test_different_contacts_do_not_add_their_open_durations(self):
        self.store.data["zones"][0]["openings"].append("binary_sensor.door")
        self.ha.states["binary_sensor.door"] = {"entity_id": "binary_sensor.door", "state": "off", "attributes": {"device_class": "door"}}
        self.ha.states["binary_sensor.window"]["state"] = "on"
        await self.tick(); await self.tick(120)
        self.ha.states["binary_sensor.window"]["state"] = "off"
        self.ha.states["binary_sensor.door"]["state"] = "on"
        await self.tick(); await self.tick(60); self.assertFalse(self.ha.device_calls())
        await self.tick(120); self.assertEqual(len(self.ha.device_calls()), 1)

    async def test_reopened_contact_resets_its_own_timer(self):
        c = self.ha.states["binary_sensor.window"]
        c.update(state="on", last_changed=self.now.isoformat())
        await self.tick(); await self.tick(170)
        # A close/open between timer ticks is still visible via HA last_changed.
        c["last_changed"] = self.now.isoformat()
        await self.tick(20); self.assertFalse(self.ha.device_calls())
        await self.tick(180); self.assertEqual(len(self.ha.device_calls()), 1)

    async def test_latched_protection_survives_restart(self):
        self.ha.states["binary_sensor.window"]["state"] = "on"
        await self.tick(); await self.tick(180); await self.tick()
        self.engine = Engine(Store(self.temp.name), self.ha, now=lambda: self.now)
        await self.tick(); self.assertEqual(len(self.ha.device_calls()), 1)
        self.assertEqual(self.ha.states["climate.living"]["attributes"]["temperature"], 60)

    async def test_manual_hold_respected_and_window_guard_wins(self):
        await self.tick(); self.ha.states["climate.living"]["attributes"]["temperature"] = 72
        await self.tick(); self.assertEqual(self.runtime()["override"]["target"]["heat"], 72); self.assertFalse(self.ha.device_calls())
        self.ha.states["binary_sensor.window"]["state"] = "on"
        await self.tick(); await self.tick(180); self.assertEqual(self.ha.device_calls()[-1][1]["temperature"], 60)

    async def test_outdoor_auto_and_hysteresis(self):
        self.outdoor(); self.ha.states["sensor.outdoor"]["state"] = "51"
        await self.tick(); self.assertEqual(self.ha.device_calls()[-1][1]["hvac_mode"], "off")
        await self.tick(); self.assertEqual(len(self.ha.notifications()), 1)
        self.ha.states["sensor.outdoor"]["state"] = "49"; await self.tick(60); self.assertEqual(len(self.ha.device_calls()), 1)
        self.ha.states["sensor.outdoor"]["state"] = "48"; await self.tick(); self.assertEqual(self.ha.device_calls()[-1][1]["temperature"], 70)

    async def test_outdoor_ask_no_and_silence_never_turn_heat_off(self):
        self.outdoor("ask"); self.ha.states["sensor.outdoor"]["state"] = "60"
        await self.tick(); self.assertFalse(self.ha.device_calls()); self.assertEqual(len(self.ha.notifications()), 1)
        await self.tick(601); self.assertFalse(self.ha.device_calls()); self.assertEqual(len(self.ha.notifications()), 1)
        self.assertEqual(self.runtime()["approval"]["decision"], "expired")

    async def test_outdoor_yes_rechecks_current_reading_and_is_one_time(self):
        self.outdoor("ask"); self.ha.states["sensor.outdoor"]["state"] = "60"
        await self.tick(); action = self.ha.notifications()[0][1]["data"]["actions"][0]["action"]
        self.ha.actions.put_nowait(action); await self.tick()
        self.assertEqual(self.ha.device_calls()[-1][1]["hvac_mode"], "off")
        self.ha.actions.put_nowait(action); await self.tick(); self.assertEqual(len(self.ha.device_calls()), 1)

    async def test_no_declines_without_reprompt_and_stale_yes_is_ignored(self):
        self.outdoor("ask"); self.ha.states["sensor.outdoor"]["state"] = "60"
        await self.tick(); actions = self.ha.notifications()[0][1]["data"]["actions"]
        self.ha.actions.put_nowait(actions[1]["action"]); await self.tick()
        self.ha.actions.put_nowait(actions[0]["action"]); await self.tick(200)
        self.assertFalse(self.ha.device_calls()); self.assertEqual(len(self.ha.notifications()), 1)

    async def test_yes_cannot_use_old_warm_reading(self):
        self.outdoor("ask"); self.ha.states["sensor.outdoor"]["state"] = "60"
        await self.tick(); action = self.ha.notifications()[0][1]["data"]["actions"][0]["action"]
        self.ha.states["sensor.outdoor"]["state"] = "45"; self.ha.actions.put_nowait(action)
        await self.tick(); self.assertFalse(self.ha.device_calls())

    async def test_command_uncertainty_survives_restart_without_retry(self):
        self.ha.states["climate.living"]["attributes"]["temperature"] = 65
        self.ha.fail = True; await self.tick(); self.assertTrue(self.runtime()["blocked"])
        self.ha.fail = False; self.engine = Engine(Store(self.temp.name), self.ha, now=lambda: self.now)
        await self.tick(60); self.assertEqual(len(self.ha.device_calls()), 1)

    async def test_late_acknowledgement_resolves_uncertainty_without_resending(self):
        self.ha.states["climate.living"]["attributes"]["temperature"] = 65
        self.ha.fail = True; await self.tick()
        self.ha.fail = False; self.ha.states["climate.living"]["attributes"]["temperature"] = 70
        await self.tick(40)
        self.assertFalse(self.runtime().get("blocked")); self.assertEqual(len(self.ha.device_calls()), 1)

    async def test_disconnect_never_sends_commands(self):
        self.ha.connected = False; self.ha.states["climate.living"]["attributes"]["temperature"] = 65
        await self.tick(); self.assertFalse(self.ha.calls)

    async def test_disabled_controller_leaves_thermostat_alone(self):
        self.store.data["zones"][0]["enabled"] = False
        self.ha.states["climate.living"]["attributes"]["temperature"] = 65
        await self.tick(); self.assertFalse(self.ha.calls)


if __name__ == "__main__": unittest.main()
