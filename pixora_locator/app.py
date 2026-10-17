#!/usr/bin/env python3
"""Pixora Locator Home Assistant App.

Reads the household's current Pixora locations and publishes them through Home
Assistant's built-in Mobile App integration. Zone migration exports selected
zone definitions only and never reads recorder history.
"""

from __future__ import annotations

import json
import html
import hashlib
import logging
import math
import os
import re
import secrets
import signal
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

OPTIONS_PATH = Path("/data/options.json")
REGISTRATIONS_PATH = Path("/data/registrations.json")
MIGRATION_SOURCE_PATH = Path("/data/migration-source-id")
PIXORA_URL = "https://planner.pixorahq.com/api/locator/home-assistant/current"
HA_API = "http://supervisor/core/api"
APP_VERSION = "1.5.0"
INGRESS_PORT = 8099
MAX_MIGRATION_ZONES = 50
MAX_MIGRATION_FILE_BYTES = 512_000
LOGGER = logging.getLogger("pixora_locator")
RUNNING = True


def read_json(path: Path, fallback: Any) -> Any:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return fallback
    return value


def write_json(path: Path, value: Any) -> None:
    try:
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    except OSError as exc:
        raise RuntimeError(f"Pixora Locator could not safely save {path.name}.") from exc


def request_json(
    url: str,
    *,
    token: str = "",
    method: str = "GET",
    payload: Any = None,
    timeout: int = 20,
    max_bytes: int = 1_000_000,
) -> Any:
    headers = {"Accept": "application/json", "User-Agent": f"Pixora-Locator-HA/{APP_VERSION}"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if payload is not None:
        data = json.dumps(payload, separators=(",", ":")).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise RuntimeError("Home Assistant returned more data than can be safely processed at once.")
            return json.loads(body.decode()) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read(2000).decode(errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail or exc.reason}") from exc
    except (urllib.error.URLError, TimeoutError, ValueError, RecursionError) as exc:
        raise RuntimeError(str(exc)) from exc


def slug(value: str) -> str:
    clean = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return clean[:80] or "phone"


def clean_text(value: Any, maximum: int) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f]", " ", str(value or ""))).strip()[:maximum]


class LocatorBridge:
    def __init__(self) -> None:
        options = read_json(OPTIONS_PATH, {})
        self.pixora_token = str(options.get("pairing_token") or "").strip()
        try:
            poll_seconds = int(options.get("poll_seconds") or 30)
        except (TypeError, ValueError):
            poll_seconds = 30
        self.poll_seconds = max(15, min(300, poll_seconds))
        self.distance_units = "km" if options.get("distance_units") == "km" else "mi"
        self.home_coordinates: tuple[float, float] | None = None
        self.home_checked_at = 0.0
        self.supervisor_token = str(os.environ.get("SUPERVISOR_TOKEN") or "").strip()
        self.migration_csrf = secrets.token_urlsafe(24)
        self.migration_lock = threading.Lock()
        self.migration_export_lock = threading.Lock()
        saved = read_json(REGISTRATIONS_PATH, {})
        self.registrations: dict[str, dict[str, str]] = {
            str(device_id): {
                "webhook_id": clean_text(value.get("webhook_id"), 200),
                "name": clean_text(value.get("name"), 80),
                "app_version": clean_text(value.get("app_version"), 30),
            }
            for device_id, value in (saved.items() if isinstance(saved, dict) else [])
            if isinstance(value, dict) and clean_text(value.get("webhook_id"), 200)
        }
        self.status_lock = threading.Lock()
        self.status: dict[str, Any] = {
            "state": "starting",
            "message": "Waiting for the first PixoraHQ sync.",
            "lastSync": "",
            "deviceCount": 0,
            "devices": [],
        }

    def home_assistant_states(self) -> list[dict[str, Any]]:
        states = request_json(f"{HA_API}/states", token=self.supervisor_token, max_bytes=10_000_000)
        if not isinstance(states, list):
            raise RuntimeError("Home Assistant returned an invalid entity list.")
        return [item for item in states if isinstance(item, dict)]

    def migration_source_id(self) -> str:
        with self.migration_lock:
            try:
                existing = MIGRATION_SOURCE_PATH.read_text(encoding="utf-8").strip()
            except OSError:
                existing = ""
            if re.fullmatch(r"[a-f0-9]{32}", existing):
                return existing
            generated = uuid.uuid4().hex
            try:
                temporary = MIGRATION_SOURCE_PATH.with_suffix(".tmp")
                temporary.write_text(generated + "\n", encoding="utf-8")
                temporary.replace(MIGRATION_SOURCE_PATH)
            except OSError as exc:
                raise RuntimeError("The Home Assistant migration identity could not be saved safely.") from exc
            return generated

    def migration_catalog(self, states: list[dict[str, Any]] | None = None) -> dict[str, list[dict[str, str]]]:
        zones: list[dict[str, str]] = []
        for state in states if states is not None else self.home_assistant_states():
            entity_id = str(state.get("entity_id") or "")
            attributes = state.get("attributes") if isinstance(state.get("attributes"), dict) else {}
            if re.fullmatch(r"zone\.[a-z0-9_]{1,195}", entity_id):
                if any(isinstance(attributes.get(key), bool) for key in ("latitude", "longitude", "radius")):
                    continue
                try:
                    latitude = float(attributes["latitude"])
                    longitude = float(attributes["longitude"])
                    raw_radius = float(100 if attributes.get("radius") is None else attributes["radius"])
                except (KeyError, TypeError, ValueError):
                    continue
                if not math.isfinite(latitude) or not math.isfinite(longitude) or not math.isfinite(raw_radius) or not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
                    continue
                radius = max(50.0, min(5000.0, raw_radius))
                zone_name = clean_text(attributes.get("friendly_name") or entity_id, 80) or entity_id[:80]
                if len(zone_name) < 2:
                    zone_name = f"{zone_name or 'Home Assistant'} Place"[:80]
                zones.append({
                    "entityId": entity_id,
                    "name": zone_name,
                    "latitude": str(latitude),
                    "longitude": str(longitude),
                    "radius": str(radius),
                    "icon": clean_text(attributes.get("icon"), 120),
                })
        zones.sort(key=lambda item: (item["name"].casefold(), item["entityId"]))
        return {"zones": zones}

    def create_migration(self, zone_ids: list[str]) -> bytes:
        states = self.home_assistant_states()
        catalog = self.migration_catalog(states)
        zone_map = {item["entityId"]: item for item in catalog["zones"]}
        zone_ids = list(dict.fromkeys(zone_ids))
        if any(item not in zone_map for item in zone_ids):
            raise RuntimeError("Home Assistant entities changed while this page was open. Refresh and choose them again.")
        chosen_zones = [zone_map[item] for item in zone_ids]
        if not chosen_zones:
            raise RuntimeError("Choose at least one Home Assistant zone to import.")
        if len(chosen_zones) > MAX_MIGRATION_ZONES:
            raise RuntimeError(f"Choose no more than {MAX_MIGRATION_ZONES} zones for one Locator household.")
        exported_at = datetime.now(timezone.utc)
        def migration_zone(item: dict[str, str]) -> dict[str, Any]:
            zone: dict[str, Any] = {
                "entityId": item["entityId"],
                "name": item["name"],
                "latitude": float(item["latitude"]),
                "longitude": float(item["longitude"]),
                "radiusMeters": float(item["radius"]),
            }
            if item["icon"]:
                zone["icon"] = item["icon"]
            return zone
        zones = [migration_zone(item) for item in chosen_zones]
        payload: dict[str, Any] = {
            "format": "pixora-locator-home-assistant-migration",
            "version": 3,
            "createdAt": exported_at.isoformat(),
            "sourceInstanceId": self.migration_source_id(),
            "zones": zones,
        }
        payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        document = (json.dumps({
            "format": "pixora-locator-home-assistant-migration-envelope",
            "version": 3,
            "payload": payload_json,
            "sha256": hashlib.sha256(payload_json.encode("utf-8")).hexdigest(),
        }, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if len(document) > MAX_MIGRATION_FILE_BYTES:
            raise RuntimeError("The migration file is too large. Choose fewer zones.")
        return document

    def set_status(self, **updates: Any) -> None:
        with self.status_lock:
            self.status.update(updates)

    def status_snapshot(self) -> dict[str, Any]:
        with self.status_lock:
            return dict(self.status)

    def validate(self) -> None:
        if not self.pixora_token.startswith("pha1."):
            raise RuntimeError("Open Pixora Locator, create a Home Assistant pairing token, and paste it into this App's Configuration tab.")
        if not self.supervisor_token:
            raise RuntimeError("Home Assistant did not provide Supervisor API access.")

    def register(self, device: dict[str, Any]) -> dict[str, str]:
        device_id = str(device.get("deviceId") or "")
        name = str(device.get("name") or "Pixora Locator")[:80]
        existing = self.registrations.get(device_id)
        if existing and existing.get("webhook_id"):
            return existing
        response = request_json(
            f"{HA_API}/mobile_app/registrations",
            token=self.supervisor_token,
            method="POST",
            payload={
                "device_id": f"pixora_locator_{device_id}",
                "app_id": "com.pixorahq.locator.homeassistant",
                "app_name": "Pixora Locator",
                "app_version": APP_VERSION,
                "device_name": name,
                "manufacturer": "PixoraHQ",
                "model": "Pixora Locator",
                "os_name": "Pixora Locator Home Assistant App",
                "os_version": APP_VERSION,
                "supports_encryption": False,
                "app_data": {},
            },
        )
        webhook_id = str(response.get("webhook_id") or "")
        if not webhook_id:
            raise RuntimeError(f"Home Assistant did not return a webhook for {name}.")
        registration = {"webhook_id": webhook_id, "name": name, "app_version": APP_VERSION}
        self.registrations[device_id] = registration
        write_json(REGISTRATIONS_PATH, self.registrations)
        LOGGER.info("Registered managed Home Assistant tracker for %s", name)
        return registration

    def webhook(self, registration: dict[str, str], message_type: str, data: dict[str, Any] | list[dict[str, Any]]) -> None:
        request_json(
            f"{HA_API}/webhook/{registration['webhook_id']}",
            token=self.supervisor_token,
            method="POST",
            payload={"type": message_type, "data": data},
        )

    def update_registration_name(self, registration: dict[str, str], name: str) -> None:
        if registration.get("name") == name and registration.get("app_version") == APP_VERSION:
            return
        self.webhook(registration, "update_registration", {
            "app_version": APP_VERSION,
            "device_name": name,
            "manufacturer": "PixoraHQ",
            "model": "Pixora Locator",
            "os_version": APP_VERSION,
        })
        registration["name"] = name
        registration["app_version"] = APP_VERSION
        write_json(REGISTRATIONS_PATH, self.registrations)

    def distance_from_home(self, location: dict[str, Any]) -> float | None:
        # Read the local Home zone once per minute, shared by all household devices.
        if self.home_checked_at == 0 or time.monotonic() - self.home_checked_at >= 60:
            self.home_checked_at = time.monotonic()
            self.home_coordinates = None
            try:
                zone = request_json(f"{HA_API}/states/zone.home", token=self.supervisor_token)
                attributes = zone.get("attributes", {}) if isinstance(zone, dict) else {}
                attributes = attributes if isinstance(attributes, dict) else {}
                lat, lon = attributes.get("latitude"), attributes.get("longitude")
                if not isinstance(lat, bool) and not isinstance(lon, bool) and math.isfinite(float(lat)) and math.isfinite(float(lon)) and -90 <= float(lat) <= 90 and -180 <= float(lon) <= 180:
                    self.home_coordinates = (float(lat), float(lon))
            except (RuntimeError, TypeError, ValueError):
                pass  # Missing home configuration must never become a false zero distance.
        if self.home_coordinates is None:
            return None
        try:
            lat, lon = float(location["latitude"]), float(location["longitude"])
            if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
                return None
            home_lat, home_lon = self.home_coordinates
            delta_lat = math.radians(home_lat - lat)
            delta_lon = math.radians(home_lon - lon)
            a = math.sin(delta_lat / 2) ** 2 + math.cos(math.radians(lat)) * math.cos(math.radians(home_lat)) * math.sin(delta_lon / 2) ** 2
            a = min(1.0, max(0.0, a))
            kilometers = 6371.0088 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            return round(kilometers if self.distance_units == "km" else kilometers / 1.609344, 2)
        except (KeyError, TypeError, ValueError):
            return None

    def update_location_sensors(self, registration: dict[str, str], device: dict[str, Any], location: dict[str, Any] | None) -> None:
        current_place = device.get("currentPlace") if isinstance(device.get("currentPlace"), dict) else {}
        nearby = device.get("nearby") if isinstance(device.get("nearby"), dict) else {}
        motion = str(device.get("motion") or "unavailable")
        available = bool(device.get("available") and location)
        unavailable = "unavailable"
        place = str(
            current_place.get("name")
            or (nearby.get("label") if motion == "stationary" else "")
            or ("On the move" if available else unavailable)
        )[:255]
        since = str(current_place.get("since") or device.get("stationarySince") or "") if available else ""
        sharing = str(device.get("sharing") or "off")
        report_time = str(location.get("receivedAt") or location.get("capturedAt") or "") if location else ""
        battery = device.get("battery") if available else None
        battery = battery if isinstance(battery, (int, float)) and not isinstance(battery, bool) and math.isfinite(battery) and 0 <= battery <= 100 else None
        charging = device.get("charging") if available else None
        unrestricted = device.get("batteryUnrestricted") if available else None
        speed = location.get("speed") if available else None
        speed = round(speed * (3.6 if self.distance_units == "km" else 2.2369362921), 1) if isinstance(speed, (int, float)) and not isinstance(speed, bool) and math.isfinite(speed) and 0 <= speed <= 100 else None
        distance = self.distance_from_home(location) if available else None
        health = str(device.get("locationHealth") or ("off" if sharing == "off" else "unknown"))
        sensors: list[dict[str, Any]] = [
            {"unique_id": "pixora_location", "name": "Place", "state": place, "icon": "mdi:map-marker-account"},
            {"unique_id": "pixora_latitude", "name": "Latitude", "state": float(location["latitude"]) if location else unavailable, "icon": "mdi:latitude", "unit_of_measurement": "°"},
            {"unique_id": "pixora_longitude", "name": "Longitude", "state": float(location["longitude"]) if location else unavailable, "icon": "mdi:longitude", "unit_of_measurement": "°"},
            {"unique_id": "pixora_gps_accuracy", "name": "GPS Accuracy", "state": max(1, round(float(location.get("accuracy") or 1))) if location else unavailable, "icon": "mdi:crosshairs-gps", "unit_of_measurement": "m"},
            {"unique_id": "pixora_since", "name": "Since", "state": since or unavailable, "icon": "mdi:clock-start", "device_class": "timestamp"},
            {"unique_id": "pixora_movement", "name": "Movement", "state": motion.replace("_", " ").title() if available else unavailable, "icon": "mdi:run"},
            {"unique_id": "pixora_sharing_mode", "name": "Sharing Mode", "state": sharing.replace("_", " ").title() if sharing != "off" else "Off", "icon": "mdi:shield-account"},
            {"unique_id": "pixora_last_report", "name": "Last Report", "state": report_time or unavailable, "icon": "mdi:clock-check-outline", "device_class": "timestamp"},
            {"unique_id": "pixora_battery", "name": "Battery", "state": battery if battery is not None else unavailable, "icon": "mdi:battery", "device_class": "battery", "unit_of_measurement": "%"},
            {"unique_id": "pixora_charging", "name": "Charging", "state": ("Charging" if charging else "Not charging") if isinstance(charging, bool) else unavailable, "icon": "mdi:battery-charging"},
            {"unique_id": "pixora_speed", "name": "Speed", "state": speed if speed is not None else unavailable, "icon": "mdi:speedometer", "unit_of_measurement": "km/h" if self.distance_units == "km" else "mph"},
            {"unique_id": "pixora_distance_from_home", "name": "Distance from Home", "state": distance if distance is not None else unavailable, "icon": "mdi:map-marker-distance", "unit_of_measurement": self.distance_units},
            {"unique_id": "pixora_location_health", "name": "Location Health", "state": health.replace("-", " ").title(), "icon": "mdi:heart-pulse"},
            {"unique_id": "pixora_battery_unrestricted", "name": "Battery Unrestricted", "state": ("Yes" if unrestricted else "No") if isinstance(unrestricted, bool) else unavailable, "icon": "mdi:battery-lock-open"},
        ]
        for sensor in sensors:
            self.webhook(registration, "register_sensor", {"type": "sensor", "attributes": {}, **sensor})
        self.webhook(registration, "update_sensor_states", [{"type": "sensor", "unique_id": sensor["unique_id"], "state": sensor["state"], "attributes": {}} for sensor in sensors])

    def update(self, device: dict[str, Any]) -> None:
        device_id = str(device.get("deviceId") or "")
        for attempt in range(2):
            registration = self.register(device)
            name = str(device.get("name") or "Pixora Locator")[:80]
            try:
                self.update_registration_name(registration, name)
                location = device.get("location") if isinstance(device.get("location"), dict) else None
                if not device.get("available") or not location:
                    self.webhook(registration, "update_location", {"location_name": "not_home"})
                    self.update_location_sensors(registration, device, None)
                    return
                accuracy = max(1, round(float(location.get("accuracy") or 1)))
                self.webhook(registration, "update_location", {
                    "gps": [float(location["latitude"]), float(location["longitude"])],
                    "gps_accuracy": accuracy,
                })
                self.update_location_sensors(registration, device, location)
                return
            except RuntimeError as exc:
                if attempt or not ("HTTP 404" in str(exc) or "HTTP 410" in str(exc)):
                    raise
                LOGGER.warning("Home Assistant removed the tracker for %s; registering it again", name)
                self.registrations.pop(device_id, None)
                write_json(REGISTRATIONS_PATH, self.registrations)

    def poll(self) -> None:
        snapshot = request_json(PIXORA_URL, token=self.pixora_token)
        devices = snapshot.get("devices") if isinstance(snapshot, dict) else None
        if not isinstance(devices, list):
            raise RuntimeError("PixoraHQ returned an invalid current-location response.")
        seen = set()
        for device in devices:
            if not isinstance(device, dict) or not device.get("deviceId"):
                continue
            seen.add(str(device["deviceId"]))
            self.update(device)
        for device_id, registration in list(self.registrations.items()):
            if device_id not in seen:
                self.webhook(registration, "update_location", {"location_name": "not_home"})
                self.update_location_sensors(registration, {"available": False, "sharing": "off", "motion": "unavailable"}, None)
        now = time.strftime("%Y-%m-%d %H:%M:%S %Z")
        visible_devices = [
            {
                "name": str(device.get("name") or "Pixora Locator")[:80],
                "sharing": str(device.get("sharing") or "off"),
                "available": bool(device.get("available")),
            }
            for device in devices
            if isinstance(device, dict) and device.get("deviceId")
        ]
        self.set_status(
            state="connected",
            message="Current Pixora Locator positions are syncing to Home Assistant.",
            lastSync=now,
            deviceCount=len(visible_devices),
            devices=visible_devices,
        )
        LOGGER.info("Synced %d Pixora Locator device%s", len(seen), "" if len(seen) == 1 else "s")

    def run(self) -> None:
        delay = 1
        while RUNNING:
            try:
                self.validate()
                self.poll()
                delay = self.poll_seconds
            except RuntimeError as exc:
                LOGGER.error("Sync failed: %s", exc)
                self.set_status(state="error", message=str(exc))
                delay = min(max(delay * 2, 15), 300)
            except Exception:
                LOGGER.exception("Unexpected Pixora Locator sync failure")
                self.set_status(state="error", message="Pixora Locator hit an unexpected sync problem and will retry automatically.")
                delay = min(max(delay * 2, 15), 300)
            deadline = time.monotonic() + delay
            while RUNNING and time.monotonic() < deadline:
                time.sleep(min(1, max(0, deadline - time.monotonic())))


def status_page(bridge: LocatorBridge) -> bytes:
    status = bridge.status_snapshot()
    state = str(status.get("state") or "starting")
    badge = {"connected": "Connected", "error": "Needs attention"}.get(state, "Starting")
    rows = []
    for device in status.get("devices") or []:
        if not isinstance(device, dict):
            continue
        available = bool(device.get("available"))
        rows.append(
            '<div class="device"><div><strong>{}</strong><small>{}</small></div><span class="{}">{}</span></div>'.format(
                html.escape(str(device.get("name") or "Pixora Locator")),
                html.escape(str(device.get("sharing") or "off").replace("_", " ").title()),
                "online" if available else "offline",
                "Current" if available else "Not sharing",
            )
        )
    device_list = "".join(rows) or '<p class="empty">No Locator phones have been registered with this household yet.</p>'
    last_sync = html.escape(str(status.get("lastSync") or "Not synced yet"))
    message = html.escape(str(status.get("message") or ""))
    try:
        catalog = bridge.migration_catalog()
        zone_options = "".join(
            '<label class="pick"><input type="checkbox" name="zone" value="{}"{}><span><strong>{}</strong><small>{} m radius</small></span></label>'.format(
                html.escape(item["entityId"], quote=True),
                " checked" if index < MAX_MIGRATION_ZONES else "",
                html.escape(item["name"]), html.escape(str(round(float(item["radius"]))))
            )
            for index, item in enumerate(catalog["zones"])
        ) or '<p class="empty">No Home Assistant zones were found.</p>'
        missing = [] if catalog["zones"] else ["at least one Home Assistant zone"]
        migration_error = f'<p class="migration-error">Add {html.escape(" and ".join(missing))} before creating a migration file.</p>' if missing else ""
    except RuntimeError as exc:
        zone_options = ""
        migration_error = f'<p class="migration-error">{html.escape(str(exc))}</p>'
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pixora Locator</title>
<style>
:root{{color-scheme:light dark;--bg:#eef6ff;--card:#fff;--ink:#092d63;--muted:#647da2;--line:#c9dcf4;--blue:#3d63ff;--mint:#4ee0c2;--bad:#b33b32}}
@media(prefers-color-scheme:dark){{:root{{--bg:#061626;--card:#102842;--ink:#f4f8ff;--muted:#a9bdd9;--line:#315477;--blue:#86a0ff;--mint:#58dfc2;--bad:#ff9289}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,sans-serif}}
main{{max-width:860px;margin:auto;padding:28px 18px 48px}}header{{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:24px}}
h1{{margin:0;font-size:clamp(28px,5vw,44px)}}.brand{{color:var(--blue);font-size:13px;font-weight:900;letter-spacing:.2em}}
.badge{{border-radius:999px;background:color-mix(in srgb,var(--mint) 28%,transparent);padding:9px 14px;font-weight:800}}
.error .badge{{background:color-mix(in srgb,var(--bad) 18%,transparent);color:var(--bad)}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:22px;padding:22px;box-shadow:0 10px 30px #001b4514;margin:16px 0}}
h2{{margin:0 0 8px;font-size:22px}}p{{margin:6px 0;color:var(--muted)}}.message{{font-size:18px;color:var(--ink)}}
.device{{display:flex;justify-content:space-between;align-items:center;gap:16px;padding:14px 0;border-top:1px solid var(--line)}}
.device:first-of-type{{margin-top:10px}}.device small{{display:block;color:var(--muted)}}.device span{{font-weight:800;white-space:nowrap}}
.online{{color:#16866e}}.offline{{color:var(--muted)}}ol{{margin:12px 0 0;padding-left:24px}}code{{overflow-wrap:anywhere}}.empty{{padding:12px 0}}
.migration h3{{margin:18px 0 7px;font-size:15px}}.pick{{display:flex;align-items:flex-start;gap:10px;padding:10px 0;border-top:1px solid var(--line);cursor:pointer}}
.pick input{{width:20px;height:20px;margin-top:2px}}.pick span{{display:grid}}.pick small{{color:var(--muted)}}button{{font:inherit}}
.migration button{{width:100%;min-height:50px;margin-top:18px;border:0;border-radius:12px;background:var(--blue);color:#fff;font-weight:900;cursor:pointer}}
.migration .selection-count{{margin-top:12px;font-weight:800;color:var(--ink)}}.migration .warning{{margin-top:14px;font-size:13px}}.migration-error{{color:var(--bad);font-weight:800}}
</style></head><body><main class="{html.escape(state)}">
<header><div><div class="brand">PIXORA LOCATOR</div><h1>Home Assistant</h1></div><span class="badge">{html.escape(badge)}</span></header>
<section class="card"><h2>Connection status</h2><p class="message">{message}</p><p>Last successful sync: {last_sync}</p></section>
<section class="card"><h2>Household devices ({int(status.get('deviceCount') or 0)})</h2>{device_list}</section>
<section class="card migration"><h2>Migrate Home Assistant zones</h2><p>Create a one-time Locator file that turns your selected Home Assistant zones into new Locator Places.</p>{migration_error}
<form method="post" action="migration/export">
<input type="hidden" name="csrf" value="{html.escape(bridge.migration_csrf, quote=True)}">
<h3>Zones to make into Locator Places</h3>{zone_options}
<p class="selection-count" aria-live="polite"></p>
<button type="submit"{' disabled' if migration_error else ''}>Create Locator import file</button>
<p class="warning"><strong>Places only:</strong> No location, arrival, or departure history is read or included. New Places start fresh; an existing matching Place stays unchanged. Delete the file after importing it.</p></form></section>
<section class="card"><h2>Setup</h2><ol><li>Open Pixora Locator on your phone.</li><li>Open <strong>Settings → Home Assistant App</strong> and create a pairing token.</li><li>Open this Home Assistant App's <strong>Configuration</strong> tab and paste the token.</li><li>Click <strong>Save</strong>, then restart the Home Assistant App.</li></ol><p>Only current locations are synchronized. Pixora Locator does not send location history or friend battery information.</p></section>
<script src="migration.js" defer></script></main></body></html>"""
    return document.encode("utf-8")


def start_status_server(bridge: LocatorBridge) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if urllib.parse.urlparse(self.path).path.endswith("/migration.js"):
                script = f"""(()=>{{const form=document.querySelector('.migration form');if(!form)return;const boxes=[...form.querySelectorAll('input[name=zone]')],button=form.querySelector('button'),count=form.querySelector('.selection-count'),maximum={MAX_MIGRATION_ZONES};const update=()=>{{const selected=boxes.filter(box=>box.checked).length;count.textContent=`${{selected}} selected · maximum ${{maximum}}`;boxes.forEach(box=>{{box.disabled=!box.checked&&selected>=maximum;}});button.disabled=selected<1||selected>maximum;}};boxes.forEach(box=>box.addEventListener('change',update));form.addEventListener('submit',()=>{{button.disabled=true;button.textContent='Preparing secure import…';}});update();}})();""".encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/javascript; charset=utf-8")
                self.send_header("Content-Length", str(len(script)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                self.wfile.write(script)
                return
            body = status_page(bridge)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; script-src 'self'; form-action 'self'; frame-ancestors 'self'")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            if not urllib.parse.urlparse(self.path).path.endswith("/migration/export"):
                self.send_error(404)
                return
            try:
                content_length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                content_length = 0
            if content_length < 1 or content_length > 65_536:
                self.send_error(400, "Invalid migration request")
                return
            try:
                form = urllib.parse.parse_qs(
                    self.rfile.read(content_length).decode("utf-8"),
                    keep_blank_values=True,
                    max_num_fields=250,
                    strict_parsing=True,
                )
            except (UnicodeDecodeError, ValueError):
                self.send_error(400, "Invalid migration request")
                return
            if not secrets.compare_digest(str(form.get("csrf", [""])[0]), bridge.migration_csrf):
                self.send_error(403, "Migration request expired")
                return
            if not bridge.migration_export_lock.acquire(blocking=False):
                self.send_error(409, "Another migration export is already being prepared")
                return
            try:
                try:
                    body = bridge.create_migration([str(item) for item in form.get("zone", [])])
                except RuntimeError as exc:
                    self.send_error(400, str(exc))
                    return
            finally:
                bridge.migration_export_lock.release()
            filename = f"pixora-locator-home-assistant-{datetime.now(timezone.utc).date().isoformat()}.pixora"
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.pixora.locator-migration+json")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            LOGGER.debug("Home Assistant page: " + format, *args)

    server = ThreadingHTTPServer(("0.0.0.0", INGRESS_PORT), Handler)
    threading.Thread(target=server.serve_forever, name="pixora-locator-page", daemon=True).start()
    return server


def stop(_signum: int, _frame: Any) -> None:
    global RUNNING
    RUNNING = False


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    bridge = LocatorBridge()
    server = start_status_server(bridge)
    LOGGER.info("Pixora Locator Home Assistant page is ready on port %d", INGRESS_PORT)
    try:
        bridge.run()
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
