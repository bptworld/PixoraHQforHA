import importlib.util
import json
import os
import tempfile
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "pixora_locator" / "app.py"
CONFIG = SOURCE.with_name("config.yaml")
DOCKERFILE = SOURCE.with_name("Dockerfile")
ROOT_README = SOURCE.parents[1] / "README.md"
HUBITAT_IMPORTER = SOURCE.parents[1] / "hubitat" / "PixoraLocatorOwnTracksImporter.groovy"
HUBITAT_README = SOURCE.parents[1] / "hubitat" / "README.md"
spec = importlib.util.spec_from_file_location("pixora_locator_ha_app", SOURCE)
assert spec and spec.loader
locator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(locator)


def run() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        locator.OPTIONS_PATH = root / "options.json"
        locator.REGISTRATIONS_PATH = root / "registrations.json"
        locator.MIGRATION_SOURCE_PATH = root / "migration-source-id"
        locator.OPTIONS_PATH.write_text(json.dumps({"pairing_token": "pha1.test", "poll_seconds": 30}), encoding="utf-8")
        locator.REGISTRATIONS_PATH.write_text(json.dumps({"broken": "not-a-registration"}), encoding="utf-8")
        os.environ["SUPERVISOR_TOKEN"] = "supervisor-test-token"
        calls = []
        snapshot = {
            "devices": [{
                "deviceId": "phone-1",
                "name": "Bryan's phone",
                "sharing": "precise",
                "available": True,
                "battery": 55,
                "charging": False,
                "batteryUnrestricted": True,
                "locationHealth": "current",
                "motion": "stationary",
                "stationarySince": "2026-09-19T12:00:00+00:00",
                "currentPlace": {"name": "Home", "since": "2026-09-19T11:30:00+00:00"},
                "location": {"latitude": 42.36, "longitude": -71.06, "accuracy": 9.4, "speed": 10, "capturedAt": "2026-09-19T12:05:00+00:00", "receivedAt": "2026-09-19T12:05:02+00:00"},
            }]
        }

        def fake_request(url, *, token="", method="GET", payload=None, timeout=20, max_bytes=1_000_000):
            calls.append((url, token, method, payload))
            if url == locator.PIXORA_URL:
                return snapshot
            if url.endswith("/states/zone.home"):
                return {"attributes": {"latitude": 42.36, "longitude": -71.06}}
            if url.endswith("/states"):
                return [
                    {"entity_id": "zone.home", "state": "1", "attributes": {"friendly_name": "Home", "latitude": 42.36, "longitude": -71.06, "radius": 100, "icon": "mdi:home"}},
                    {"entity_id": "zone.x", "state": "0", "attributes": {"friendly_name": "X", "latitude": 42.35, "longitude": -71.05, "radius": 75}},
                    {"entity_id": "zone.invalid", "state": "0", "attributes": {"friendly_name": "Invalid", "latitude": "nan", "longitude": -71.06, "radius": 100}},
                    {"entity_id": "zone.boolean", "state": "0", "attributes": {"friendly_name": "Boolean", "latitude": True, "longitude": -71.06, "radius": 100}},
                    {"entity_id": "zone.Bad", "state": "0", "attributes": {"friendly_name": "Bad identity", "latitude": 42.35, "longitude": -71.05, "radius": 75}},
                    {"entity_id": "zone." + "x" * 196, "state": "0", "attributes": {"friendly_name": "Too long", "latitude": 42.35, "longitude": -71.05, "radius": 75}},
                ]
            if url.endswith("/mobile_app/registrations"):
                return {"webhook_id": "managed-webhook-1"}
            if "/webhook/" in url:
                return {}
            raise AssertionError(url)

        original_request = locator.request_json
        locator.request_json = fake_request
        try:
            bridge = locator.LocatorBridge()
            assert bridge.registrations == {}
            bridge.validate()
            bridge.poll()
            registration = next(call for call in calls if call[0].endswith("/mobile_app/registrations"))
            assert registration[3]["device_name"] == "Bryan's phone"
            assert registration[3]["device_id"] == "pixora_locator_phone-1"
            location = next(call for call in calls if call[3] and call[3].get("type") == "update_location")
            assert location[3]["data"] == {"gps": [42.36, -71.06], "gps_accuracy": 9}
            sensor_calls = [call for call in calls if call[3] and call[3].get("type") == "register_sensor"]
            assert len(sensor_calls) == 14
            sensors = {call[3]["data"]["name"]: call[3]["data"] for call in sensor_calls}
            assert set(sensors) == {"Place", "Latitude", "Longitude", "GPS Accuracy", "Since", "Movement", "Sharing Mode", "Last Report", "Battery", "Charging", "Speed", "Distance from Home", "Location Health", "Battery Unrestricted"}
            assert sensors["Battery"]["state"] == 55
            assert sensors["Charging"]["state"] == "Not charging"
            assert sensors["Speed"]["state"] == 22.4
            assert sensors["Distance from Home"]["state"] == 0
            assert sensors["Battery Unrestricted"]["state"] == "Yes"
            assert sensors["Location Health"]["state"] == "Current"
            updates = [call[3]["data"] for call in calls if call[3] and call[3].get("type") == "update_sensor_states"]
            assert len(updates[-1]) == 14
            assert sensors["Place"]["unique_id"] == "pixora_location" and sensors["Place"]["state"] == "Home"
            assert sensors["Latitude"]["state"] == 42.36 and sensors["Latitude"]["unit_of_measurement"] == "°"
            assert sensors["Longitude"]["state"] == -71.06 and sensors["Longitude"]["unit_of_measurement"] == "°"
            assert sensors["GPS Accuracy"]["state"] == 9 and sensors["GPS Accuracy"]["unit_of_measurement"] == "m"
            assert sensors["Since"]["state"] == "2026-09-19T11:30:00+00:00" and sensors["Since"]["device_class"] == "timestamp"
            assert sensors["Movement"]["state"] == "Stationary"
            assert sensors["Sharing Mode"]["state"] == "Precise"
            assert sensors["Last Report"]["state"] == "2026-09-19T12:05:02+00:00" and sensors["Last Report"]["device_class"] == "timestamp"
            assert all(sensor["attributes"] == {} for sensor in sensors.values())
            calls.clear()
            bridge.distance_units = "km"
            bridge.update_location_sensors(bridge.registrations["phone-1"], snapshot["devices"][0], snapshot["devices"][0]["location"])
            metric_sensors = {call[3]["data"]["name"]: call[3]["data"] for call in calls if call[3] and call[3].get("type") == "register_sensor"}
            assert metric_sensors["Speed"]["state"] == 36.0 and metric_sensors["Speed"]["unit_of_measurement"] == "km/h"
            assert metric_sensors["Distance from Home"]["unit_of_measurement"] == "km"
            assert 111 < bridge.distance_from_home({"latitude": 43.36, "longitude": -71.06}) < 112
            calls.clear()
            older_device = {**snapshot["devices"][0], "charging": None, "batteryUnrestricted": None}
            bridge.update_location_sensors(bridge.registrations["phone-1"], older_device, {**older_device["location"], "speed": -1})
            unknown_sensors = {call[3]["data"]["name"]: call[3]["data"] for call in calls if call[3] and call[3].get("type") == "register_sensor"}
            assert all(unknown_sensors[name]["state"] == "unavailable" for name in ("Charging", "Battery Unrestricted", "Speed"))
            bridge.distance_units = "mi"
            bridge.home_checked_at = 0
            locator.request_json = lambda *args, **kwargs: {"attributes": None}
            assert bridge.distance_from_home(snapshot["devices"][0]["location"]) is None
            locator.request_json = fake_request
            bridge.home_checked_at = 0
            saved_registration = json.loads(locator.REGISTRATIONS_PATH.read_text())["phone-1"]
            assert saved_registration["webhook_id"] == "managed-webhook-1" and saved_registration["app_version"] == "1.5.0"
            page = locator.status_page(bridge).decode()
            assert "Bryan&#x27;s phone" in page and "Connected" in page and "Last successful sync" in page
            assert "42.36" not in page and "-71.06" not in page and "pha1.test" not in page
            assert "Migrate Home Assistant zones" in page and "Places only" in page
            assert "Location history" not in page
            assert "Invalid" not in page and "Boolean" not in page and "Bad identity" not in page and "Too long" not in page and "migration.js" in page and "X Place" in page
            assert "selection-count" in page
            catalog = bridge.migration_catalog()
            assert next(item for item in catalog["zones"] if item["entityId"] == "zone.x")["name"] == "X Place"

            calls.clear()
            document = json.loads(bridge.create_migration(["zone.home"]))
            assert document["format"] == "pixora-locator-home-assistant-migration-envelope" and document["version"] == 3
            assert document["sha256"] == locator.hashlib.sha256(document["payload"].encode()).hexdigest()
            migration = json.loads(document["payload"])
            assert migration["format"] == "pixora-locator-home-assistant-migration" and migration["version"] == 3
            assert migration["zones"][0]["name"] == "Home" and migration["zones"][0]["radiusMeters"] == 100
            assert migration["sourceInstanceId"] == locator.MIGRATION_SOURCE_PATH.read_text().strip()
            assert not {"trackers", "historyDays", "locations", "activities"}.intersection(migration)
            assert not any("/history/period/" in call[0] or call[0].endswith("/template") for call in calls)
            original_states = bridge.home_assistant_states
            bridge.home_assistant_states = lambda: [
                {"entity_id": f"zone.place_{index}", "attributes": {"friendly_name": f"Place {index}", "latitude": 42.0 + index / 1000, "longitude": -71.0, "radius": 100}}
                for index in range(locator.MAX_MIGRATION_ZONES + 1)
            ]
            try:
                crowded_page = locator.status_page(bridge).decode()
                assert crowded_page.count('name="zone"') == locator.MAX_MIGRATION_ZONES + 1
                assert crowded_page.count(" checked") == locator.MAX_MIGRATION_ZONES
                bridge.create_migration([f"zone.place_{index}" for index in range(locator.MAX_MIGRATION_ZONES + 1)])
                raise AssertionError("Oversized migration selection was accepted")
            except RuntimeError as exc:
                assert "no more than 50 zones" in str(exc)
            finally:
                bridge.home_assistant_states = original_states
            original_port = locator.INGRESS_PORT
            locator.INGRESS_PORT = 0
            server = locator.start_status_server(bridge)
            try:
                base_url = f"http://127.0.0.1:{server.server_address[1]}"
                with locator.urllib.request.urlopen(f"{base_url}/", timeout=5) as response:
                    live_page = response.read()
                    assert response.headers["Cache-Control"] == "no-store"
                    assert b"Migrate Home Assistant zones" in live_page
                with locator.urllib.request.urlopen(f"{base_url}/migration.js", timeout=5) as response:
                    migration_script = response.read()
                    assert b"maximum=50" in migration_script and response.headers["X-Content-Type-Options"] == "nosniff"
                export_form = locator.urllib.parse.urlencode({"csrf": bridge.migration_csrf, "zone": "zone.home"}).encode()
                export_request = locator.urllib.request.Request(f"{base_url}/migration/export", data=export_form, method="POST")
                with locator.urllib.request.urlopen(export_request, timeout=5) as response:
                    exported_document = json.loads(response.read())
                    assert response.headers["Cache-Control"] == "no-store"
                    assert response.headers["Content-Disposition"].endswith('.pixora"')
                    assert exported_document["format"] == "pixora-locator-home-assistant-migration-envelope"
                expired_form = locator.urllib.parse.urlencode({"csrf": "expired", "zone": "zone.home"}).encode()
                expired_request = locator.urllib.request.Request(f"{base_url}/migration/export", data=expired_form, method="POST")
                try:
                    locator.urllib.request.urlopen(expired_request, timeout=5)
                    raise AssertionError("Expired migration CSRF was accepted")
                except locator.urllib.error.HTTPError as exc:
                    assert exc.code == 403
            finally:
                server.shutdown()
                server.server_close()
                locator.INGRESS_PORT = original_port
            calls.clear()
            snapshot["devices"][0] = {"deviceId": "phone-1", "name": "Bryan's phone", "available": False}
            bridge.poll()
            assert not any(call[0].endswith("/mobile_app/registrations") for call in calls)
            unavailable = next(call for call in calls if call[3] and call[3].get("type") == "update_location")
            assert unavailable[3]["data"] == {"location_name": "not_home"}
            unavailable_sensors = [call[3]["data"] for call in calls if call[3] and call[3].get("type") == "register_sensor"]
            assert len(unavailable_sensors) == 14
            assert next(sensor for sensor in unavailable_sensors if sensor["name"] == "Sharing Mode")["state"] == "Off"
            assert all(sensor["state"] == "unavailable" for sensor in unavailable_sensors if sensor["name"] not in {"Sharing Mode", "Location Health"})
            assert next(sensor for sensor in unavailable_sensors if sensor["name"] == "Location Health")["state"] == "Off"

            calls.clear()
            snapshot["devices"] = []
            bridge.poll()
            assert next(call for call in calls if call[3] and call[3].get("type") == "update_location")[3]["data"] == {"location_name": "not_home"}
            missing_sensors = [call[3]["data"] for call in calls if call[3] and call[3].get("type") == "register_sensor"]
            assert len(missing_sensors) == 14
            assert all(sensor["state"] == "unavailable" for sensor in missing_sensors if sensor["name"] not in {"Sharing Mode", "Location Health"})
        finally:
            locator.request_json = original_request



if __name__ == "__main__":
    run()
    print("Pixora Locator Home Assistant App checks passed.")
