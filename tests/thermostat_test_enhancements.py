"""New thermostat tools: deterministic tests, no live HA or equipment."""
import copy
import ast
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from thermostat_test_controller import FakeHA, zone
from engine import Store, Engine
from policy import validate
from enhancements import freshness, household, indoor_value, RuntimeHistory
from ha import HomeAssistant


class ToolPolicies(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 26, 16, tzinfo=timezone.utc)

    def test_old_value_but_recent_report_is_current(self):
        state = {"last_updated": "2020-01-01T00:00:00Z", "last_reported": self.now.isoformat()}
        self.assertEqual(freshness(state, self.now, 5)["state"], "current")
        state["last_reported"] = (self.now-timedelta(minutes=6)).isoformat()
        self.assertEqual(freshness(state, self.now, 5)["state"], "stale")
        self.assertEqual(freshness({"last_updated": self.now.isoformat()}, self.now, 5)["state"], "unverified")
        self.assertEqual(freshness({"last_reported": (self.now+timedelta(hours=1)).isoformat()}, self.now, 5)["state"], "unverified")

    def test_household_requires_everyone_known_away_and_delays_return(self):
        config = {"enabled": True, "people": ["person.a", "person.b"], "away": {"mode": "heat", "heat": 60}, "awayMinutes": 5, "homeMinutes": 1}
        states = {"person.a": {"state": "work"}, "person.b": {"state": "unknown"}}
        runtime = {}
        self.assertFalse(household(config, states, runtime, self.now)[0])
        states["person.b"]["state"] = "not_home"
        self.assertFalse(household(config, states, runtime, self.now)[0])
        self.assertTrue(household(config, states, runtime, self.now+timedelta(minutes=5))[0])
        states["person.a"]["state"] = "unavailable"
        self.assertTrue(household(config, states, runtime, self.now+timedelta(minutes=6))[0])
        states["person.b"]["state"] = "home"
        self.assertTrue(household(config, states, runtime, self.now+timedelta(minutes=7))[0])
        self.assertFalse(household(config, states, runtime, self.now+timedelta(minutes=8))[0])
        config["people"] = ["person.c"]
        self.assertFalse(household(config, {}, runtime, self.now)[0])

    def test_indoor_units_and_unknown(self):
        self.assertAlmostEqual(indoor_value({"entity_id": "climate.x", "state": "off", "attributes": {"current_temperature": 20}}, "F", "C"), 68)
        for raw in (None, "bad", float("nan")):
            with self.assertRaises(ValueError):
                indoor_value({"entity_id": "sensor.x", "state": raw, "attributes": {"unit_of_measurement": "F"}}, "F", "F")

    def test_history_does_not_infer_heating_from_heat_mode_or_fill_gaps(self):
        history = RuntimeHistory()
        z = zone(); state = {"state": "heat", "attributes": {}}
        history.sample(z, state, True, self.now, "America/New_York")
        history.sample(z, state, True, self.now+timedelta(seconds=5), "America/New_York")
        row = history.data["living"]["days"]["2026-10-26"]
        self.assertEqual(row["heating"], 0); self.assertEqual(row["unknown"], 5)
        state["attributes"]["hvac_action"] = "heating"
        history.sample(z, state, True, self.now+timedelta(seconds=10), "America/New_York")
        history.sample(z, state, True, self.now+timedelta(seconds=15), "America/New_York")
        self.assertEqual(row["heating"], 5)
        history.sample(z, state, False, self.now+timedelta(seconds=20), "America/New_York")
        history.sample(z, state, True, self.now+timedelta(hours=1), "America/New_York")
        self.assertEqual(row["heating"], 5)
        restarted = RuntimeHistory(history.data)
        restarted.sample(z, state, True, self.now+timedelta(hours=2), "America/New_York")
        self.assertEqual(restarted.data["living"]["days"]["2026-10-26"]["heating"], 5)
        z["entity"] = "climate.other"
        restarted.sample(z, state, True, self.now, "UTC")
        self.assertFalse(restarted.data["living"]["days"])

    def test_history_splits_midnight_and_is_bounded(self):
        history = RuntimeHistory(); z = zone(); state = {"attributes": {"hvac_action": "cooling"}}
        now = datetime(2026, 10, 27, 3, 59, 55, tzinfo=timezone.utc)
        history.sample(z, state, True, now, "America/New_York")
        history.sample(z, state, True, now+timedelta(seconds=10), "America/New_York")
        self.assertEqual(history.data["living"]["days"]["2026-10-26"]["cooling"], 5)
        self.assertEqual(history.data["living"]["days"]["2026-10-27"]["cooling"], 5)
        for day in range(100):
            at = now+timedelta(days=day)
            history.sample(z, state, True, at, "UTC")
            history.sample(z, state, True, at+timedelta(seconds=5), "UTC")
        self.assertLessEqual(len(history.data["living"]["days"]), 90)

    def test_container_packages_all_local_imports(self):
        root = Path(__file__).resolve().parents[1] / "pixora_thermostat_controller"
        copied = set(next(line for line in (root / "Dockerfile").read_text().splitlines() if line.startswith("COPY ")).split()[1:-1])
        for name in copied:
            if not name.endswith(".py"):
                continue
            for node in ast.walk(ast.parse((root/name).read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom) and node.module and (root/(node.module+".py")).exists():
                    self.assertIn(node.module+".py", copied)

    def test_new_options_validate_and_default_to_optional(self):
        z = validate({"zones": [zone()]})["zones"][0]
        self.assertFalse(z["freshness"]["enabled"]); self.assertFalse(z["household"]["enabled"]); self.assertFalse(z["indoorAlerts"]["enabled"])
        for key, value in (("freshness", {"enabled": True, "minutes": True}), ("household", {"enabled": True, "people": [{}]}), ("notificationPolicy", {"cooldownMinutes": -1})):
            bad = copy.deepcopy(z); bad[key] = value
            with self.assertRaises(ValueError): validate({"zones": [bad]})
        bad = copy.deepcopy(z); bad["indoorAlerts"].update(enabled=True, low=90, high=45)
        with self.assertRaises(ValueError): validate({"zones": [bad]})


class IntegrationTools(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name); self.z = validate({"zones": [zone()]})["zones"][0]
        data = copy.deepcopy(self.store.data); data["zones"] = [self.z]; self.store.write(data)
        self.ha = FakeHA(); self.now = datetime(2026, 10, 26, 16, tzinfo=timezone.utc)
        self.engine = Engine(self.store, self.ha, now=lambda: self.now)

    async def tick(self, seconds=0):
        self.now += timedelta(seconds=seconds)
        await self.engine.tick()

    def config(self): return self.store.data["zones"][0]

    async def test_freshness_blocks_stale_not_unchanged_readings(self):
        self.config()["freshness"].update(enabled=True, minutes=5)
        climate = self.ha.states["climate.living"]
        climate["attributes"]["temperature"] = 65
        climate["last_reported"] = (self.now-timedelta(minutes=6)).isoformat()
        await self.tick()
        self.assertFalse(self.ha.device_calls()); self.assertIn("last report", self.engine.status["living"]["detail"])
        climate["last_reported"] = self.now.isoformat(); climate["last_updated"] = "2020-01-01T00:00:00Z"
        await self.tick()
        self.assertEqual(self.ha.device_calls()[-1][1]["temperature"], 70)

    async def test_household_away_keeps_window_protection_and_manual_hold_priority(self):
        self.config()["household"].update(enabled=True, people=["person.a", "person.b"], awayMinutes=0, homeMinutes=0, away={"mode": "heat", "heat": 65})
        self.ha.states.update({"person.a": {"state": "work"}, "person.b": {"state": "not_home"}})
        await self.tick(); await self.tick()
        self.assertEqual(self.engine.status["living"]["reason"], "Household away")
        self.ha.states["climate.living"]["attributes"]["temperature"] = 72
        await self.tick(); self.assertEqual(self.engine.status["living"]["target"]["heat"], 72)
        self.ha.states["binary_sensor.window"]["state"] = "on"
        await self.tick(); await self.tick(180); await self.tick()
        self.assertEqual(self.engine.status["living"]["target"]["heat"], 60)
        rules = [r["rule"] for r in self.engine.status["living"]["explanations"]]
        for rule in ("Weekly schedule", "Household Home/Away", "Temporary override", "Door/window protection"): self.assertIn(rule, rules)

    async def test_grouping_sends_latest_list_once_and_survives_restart(self):
        self.config()["openings"].append("binary_sensor.door")
        self.ha.states["binary_sensor.door"] = {"state": "off", "attributes": {"friendly_name": "Door"}}
        self.ha.states["binary_sensor.window"]["state"] = "on"
        await self.tick(); await self.tick(180); await self.tick()
        self.assertEqual(len(self.ha.notifications()), 1)
        self.ha.states["binary_sensor.door"]["state"] = "on"; await self.tick()
        self.assertEqual(len(self.ha.notifications()), 1)
        self.assertIn("grouped", self.engine.status["living"]["notificationPending"])
        self.store = Store(self.temp.name); self.engine = Engine(self.store, self.ha, now=lambda: self.now)
        await self.tick(299); self.assertEqual(len(self.ha.notifications()), 1)
        await self.tick(1); self.assertEqual(len(self.ha.notifications()), 2)
        self.assertIn("Door", self.ha.notifications()[-1][1]["message"])
        await self.tick(); self.assertEqual(len(self.ha.notifications()), 2)

    async def test_indoor_warning_is_alert_only_and_latches_until_recovery(self):
        self.config()["schedule"] = [{"id": "off", "time": "00:00", "days": list(range(7)), "mode": "off"}]
        self.config()["indoorAlerts"].update(enabled=True, minutes=1)
        self.ha.states["climate.living"].update(state="off")
        self.ha.states["climate.living"]["attributes"]["current_temperature"] = 40
        await self.tick(); await self.tick(60)
        self.assertEqual(len(self.ha.notifications()), 1)
        self.assertIn("unusually cold", self.ha.notifications()[0][1]["message"])
        self.assertFalse(self.ha.device_calls())
        await self.tick(600); self.assertEqual(len(self.ha.notifications()), 1)
        self.ha.states["climate.living"]["attributes"]["current_temperature"] = 48; await self.tick()
        self.ha.states["climate.living"]["attributes"]["current_temperature"] = 40
        await self.tick(); await self.tick(60); self.assertEqual(len(self.ha.notifications()), 2)

    async def test_optional_warning_sensor_failure_does_not_stop_schedule(self):
        self.config()["indoorAlerts"].update(enabled=True, entity="sensor.indoor")
        self.ha.states["sensor.indoor"] = {"entity_id": "sensor.indoor", "state": "unavailable", "attributes": {"device_class": "temperature", "friendly_name": "Room reading", "unit_of_measurement": "F"}}
        self.ha.states["climate.living"]["attributes"]["temperature"] = 65
        await self.tick(); await self.tick()
        self.assertEqual(self.ha.device_calls()[-1][1]["temperature"], 70)
        self.assertEqual(len(self.ha.notifications()), 1)
        action = self.ha.notifications()[0][1]["data"]["actions"][1]["action"]
        self.ha.actions.put_nowait(action); await self.tick()
        self.assertIn("sensor.indoor", self.store.data["runtime"]["living"]["ignored"])
        await self.tick(600); self.assertEqual(len(self.ha.notifications()), 1)

    async def test_indoor_delay_does_not_count_missing_observations(self):
        self.config()["indoorAlerts"].update(enabled=True, entity="sensor.indoor", minutes=1)
        reading = {"entity_id": "sensor.indoor", "state": "40", "attributes": {"device_class": "temperature", "unit_of_measurement": "F"}}
        self.ha.states["sensor.indoor"] = reading
        await self.tick(); reading["state"] = "unavailable"; await self.tick(30)
        reading["state"] = "40"; await self.tick(600)
        self.assertFalse(any("unusually cold" in row[1]["message"] for row in self.ha.notifications()))
        await self.tick(60)
        self.assertTrue(any("unusually cold" in row[1]["message"] for row in self.ha.notifications()))

    async def test_history_storage_failure_does_not_crash_control(self):
        await self.tick()
        original = self.store.write
        def fail(value): raise OSError("test storage failure")
        self.store.write = fail
        await self.tick(5)
        self.store.write = original
        self.assertIn("could not be saved", self.engine.history_notice)
        self.assertEqual(self.engine.status["living"]["reason"], "Schedule")

    async def test_preview_never_verifies_live_sensor_or_changes_runtime(self):
        self.config()["freshness"].update(enabled=True, minutes=5)
        self.ha.verify_report = AsyncMock()
        before = copy.deepcopy(self.store.data)
        await self.engine.preview(self.config())
        self.ha.verify_report.assert_not_called()
        self.assertEqual(self.store.data, before)

    async def test_report_lookup_is_selected_bounded_and_keeps_last_reported(self):
        ha = HomeAssistant(None, "test")
        ha.request = AsyncMock(return_value={"entity_id": "sensor.outdoor", "state": "62", "last_updated": "2020-01-01T00:00:00Z", "last_reported": self.now.isoformat(), "attributes": {"device_class": "temperature", "unit_of_measurement": "F"}})
        await ha.verify_report("sensor.outdoor", 5, self.now)
        await ha.verify_report("sensor.outdoor", 5, self.now+timedelta(seconds=1))
        self.assertEqual(ha.request.await_count, 1)
        self.assertEqual(freshness(ha.states["sensor.outdoor"], self.now, 5)["state"], "current")
        old = copy.deepcopy(ha.states["sensor.outdoor"]); old["last_reported"] = "2020-01-01T00:00:00Z"
        ha.update(old)
        self.assertEqual(freshness(ha.states["sensor.outdoor"], self.now, 5)["state"], "current")


if __name__ == "__main__": unittest.main()
