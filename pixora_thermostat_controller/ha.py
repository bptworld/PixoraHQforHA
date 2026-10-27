"""One local HA WebSocket, one cached catalog; commands are never retried."""
import asyncio
import json
from zoneinfo import ZoneInfo
from urllib.parse import quote
from datetime import datetime, timezone
from aiohttp import ClientError, ClientTimeout, WSMsgType
from insight_origin import ha_reporter


class HomeAssistant:
    def __init__(self, session, token):
        self.session, self.token = session, token
        self.states, self.services = {}, set()
        self.connected = False
        self.timezone, self.unit = "UTC", "C"
        self.notice = "Connecting to Home Assistant."
        self.actions = asyncio.Queue(maxsize=32)
        self.voice = asyncio.Queue(maxsize=16)
        self.wake = asyncio.Event()
        self.freshness_checks = {}
        self.last_freshness_check = None
        self.socket, self.pending, self.counter = None, {}, 100
        self.origin = ha_reporter(session, "Pixora Thermostat Controller")

    async def request(self, path, data=None):
        if not self.token:
            raise ValueError("Home Assistant API access is unavailable.")
        try:
            async with self.session.request("GET" if data is None else "POST", "http://supervisor/core/api/" + path,
                    json=data, headers={"Authorization": "Bearer " + self.token}, timeout=ClientTimeout(total=12), allow_redirects=False) as response:
                if response.status >= 300:
                    raise ValueError("Home Assistant could not confirm the request. Check the device before retrying.")
                return await response.json()
        except (ClientError, asyncio.TimeoutError) as exc:
            raise ValueError("Home Assistant request could not be confirmed. No automatic retry.") from exc

    async def call(self, service, fields):
        return await self.call_with_origin(service, fields, "Thermostat Controller requested this service action.")

    async def call_with_origin(self, service, fields, reason):
        domain, name = service.split(".", 1)
        if not self.connected or self.socket is None or len(self.pending) >= 32:
            raise ValueError("Home Assistant command connection is unavailable. No command sent.")
        self.counter += 1
        ident = self.counter
        future = asyncio.get_running_loop().create_future()
        self.pending[ident] = future
        try:
            await self.socket.send_json({"id": ident, "type": "call_service", "domain": domain, "service": name, "service_data": fields})
            result = await asyncio.wait_for(future, 12)
        except (ClientError, RuntimeError) as exc:
            raise ValueError("Home Assistant command result could not be confirmed. No automatic retry.") from exc
        finally:
            self.pending.pop(ident, None)
            if not future.done():future.cancel()
        context = result.get("context", {}).get("id") if isinstance(result, dict) and isinstance(result.get("context"), dict) else None
        targets = fields.get("entity_id", [])
        targets = [targets] if isinstance(targets, str) else targets
        try:self.origin.emit(targets, reason, context=context, operation=service)
        except Exception:pass # Optional provenance never changes the service result.

    def update(self, state):
        if not isinstance(state, dict):
            return
        ident = str(state.get("entity_id", ""))
        if ident.split(".")[0] not in {"climate", "sensor", "binary_sensor", "weather", "person", "device_tracker"}:
            return
        attrs = state.get("attributes", {})
        if ident.startswith("sensor.") and attrs.get("device_class") != "temperature" or ident.startswith("binary_sensor.") and attrs.get("device_class") not in {"door", "window", "opening", "garage_door", "presence", "occupancy"}:
            self.states.pop(ident, None)
            return
        old = self.states.get(ident, {})
        if (str(state.get("last_updated", "")), str(state.get("last_reported", ""))) >= (str(old.get("last_updated", "")), str(old.get("last_reported", ""))):
            keep = {"friendly_name", "device_class", "unit_of_measurement", "temperature_unit", "temperature", "current_temperature", "target_temp_low", "target_temp_high", "supported_features", "hvac_modes", "min_temp", "max_temp", "target_temp_step", "hvac_action"}
            self.states[ident] = {**{k: state[k] for k in ("entity_id", "state", "last_changed", "last_updated", "last_reported") if k in state}, "attributes": {k: v for k, v in attrs.items() if k in keep}}

    async def verify_report(self, ident, minutes, now):
        from enhancements import freshness
        if freshness(self.states.get(ident), now, minutes)["state"] == "current":
            return
        # Only opted-in, selected temperature entities are checked, and only
        # after their report timestamp is old or missing. No global polling.
        last = self.freshness_checks.get(ident)
        if last and 0 <= (now-last).total_seconds() < 300:
            return
        if self.last_freshness_check and 0 <= (now-self.last_freshness_check).total_seconds() < 5:
            return
        self.last_freshness_check = now
        self.freshness_checks[ident] = now
        # Selected entities only; prune bindings removed by later settings.
        self.freshness_checks = {key: at for key, at in self.freshness_checks.items() if (now-at).total_seconds() < 86400}
        try:
            state = await asyncio.wait_for(self.request("states/" + quote(ident, safe="")), timeout=3)
            self.update(state)
        except (ValueError, asyncio.TimeoutError):
            pass  # Caller retains unknown/stale status and blocks new commands.

    async def listen(self):
        delay = 2
        while True:
            try:
                config = await self.request("config")
                ZoneInfo(config["time_zone"])
                self.timezone = config["time_zone"]
                self.unit = str(config["unit_system"]["temperature"]).replace("\u00b0", "").upper()
                async with self.session.ws_connect("http://supervisor/core/websocket", heartbeat=25, receive_timeout=75,
                        max_msg_size=16 * 1024 * 1024) as ws:
                    hello = await ws.receive_json()
                    if hello.get("type") != "auth_required":
                        raise ValueError("Unexpected Home Assistant handshake.")
                    await ws.send_json({"type": "auth", "access_token": self.token})
                    if (await ws.receive_json()).get("type") != "auth_ok":
                        raise ValueError("Home Assistant did not authorize the app.")
                    self.socket = ws
                    await ws.send_json({"id": 1, "type": "subscribe_events", "event_type": "state_changed"})
                    await ws.send_json({"id": 2, "type": "get_states"})
                    await ws.send_json({"id": 3, "type": "subscribe_events", "event_type": "mobile_app_notification_action"})
                    await ws.send_json({"id": 4, "type": "subscribe_events", "event_type": "pixora_thermostat_voice_request"})
                    await ws.send_json({"id": 5, "type": "subscribe_events", "event_type": "service_registered"})
                    await ws.send_json({"id": 6, "type": "subscribe_events", "event_type": "service_removed"})
                    await ws.send_json({"id": 7, "type": "get_services"})
                    initial = False
                    services_ready = False
                    async for message in ws:
                        if message.type != WSMsgType.TEXT:
                            if message.type in {WSMsgType.CLOSED, WSMsgType.ERROR, WSMsgType.CLOSE}:
                                break
                            continue
                        packet = json.loads(message.data)
                        if packet.get("type") == "result" and packet.get("id") in self.pending:
                            future = self.pending[packet["id"]]
                            if not future.done():
                                if packet.get("success"):future.set_result(packet.get("result"))
                                else:future.set_exception(ValueError("Home Assistant rejected the command. It was not retried."))
                            continue
                        if packet.get("type") == "result" and packet.get("success") is False:
                            raise ValueError("Home Assistant subscription could not be established.")
                        if packet.get("id") == 2 and packet.get("type") == "result":
                            buffered = self.states
                            self.states = {}
                            for state in packet["result"]:
                                self.update(state)
                            for state in buffered.values():
                                self.update(state)
                            initial = True
                            self.connected = services_ready
                            self.notice, delay = "", 2
                        elif packet.get("id") == 7 and packet.get("type") == "result":
                            self.services = {domain + "." + name for domain, rows in packet["result"].items() for name in rows}
                            services_ready = True
                            self.connected = initial
                        elif packet.get("type") == "event":
                            kind = packet.get("event", {}).get("event_type")
                            if kind in {"service_registered", "service_removed"}:
                                data = packet["event"].get("data", {})
                                domain, name = data.get("domain"), data.get("service")
                                if isinstance(domain, str) and isinstance(name, str):
                                    service = domain + "." + name
                                    if kind == "service_registered":
                                        self.services.add(service)
                                    else:
                                        self.services.discard(service)
                                    self.wake.set()
                                continue
                            if packet.get("event", {}).get("event_type") == "pixora_thermostat_voice_request":
                                if not self.voice.full():
                                    self.voice.put_nowait(packet["event"].get("data", {}))
                                    self.wake.set()
                                continue
                            if packet.get("event", {}).get("event_type") == "mobile_app_notification_action":
                                action = packet["event"].get("data", {}).get("action", "")
                                if isinstance(action, str) and action.startswith("pixora_thermostat:") and not self.actions.full():
                                    self.actions.put_nowait(action)
                                continue
                            event = packet.get("event", {}).get("data", {})
                            if event.get("new_state") is None:
                                self.states.pop(event.get("entity_id"), None)
                            else:
                                self.update(event["new_state"])
                    if not initial:
                        raise ValueError("Home Assistant did not provide its state catalog.")
            except asyncio.CancelledError:
                raise
            except (ValueError, KeyError, TypeError, ClientError, asyncio.TimeoutError):
                self.notice = "Reconnecting to Home Assistant. Automatic changes are paused."
            finally:
                self.connected = False
                self.socket = None
                for future in self.pending.values():
                    if not future.done():future.set_exception(ValueError("Home Assistant disconnected. Command result is uncertain; no retry."))
                # Never treat a snapshot from an earlier connection as fresh.
                self.states = {}
            await asyncio.sleep(delay)
            delay = min(60, delay * 2)
