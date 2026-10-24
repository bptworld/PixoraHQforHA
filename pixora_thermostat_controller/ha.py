"""One local HA WebSocket, one cached catalog; commands are never retried."""
import asyncio
import json
from zoneinfo import ZoneInfo
from aiohttp import ClientError, ClientTimeout, WSMsgType


class HomeAssistant:
    def __init__(self, session, token):
        self.session, self.token = session, token
        self.states, self.services = {}, set()
        self.connected = False
        self.timezone, self.unit = "UTC", "C"
        self.notice = "Connecting to Home Assistant."
        self.actions = asyncio.Queue(maxsize=32)

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
        domain, name = service.split(".", 1)
        result = await self.request("services/" + domain + "/" + name, fields)
        if isinstance(result, list):
            for state in result:
                self.update(state)

    def update(self, state):
        if not isinstance(state, dict):
            return
        ident = str(state.get("entity_id", ""))
        if ident.split(".")[0] not in {"climate", "sensor", "binary_sensor", "weather", "person"}:
            return
        attrs = state.get("attributes", {})
        if ident.startswith("sensor.") and attrs.get("device_class") != "temperature" or ident.startswith("binary_sensor.") and attrs.get("device_class") not in {"door", "window", "opening", "garage_door"}:
            self.states.pop(ident, None)
            return
        old = self.states.get(ident, {})
        if str(state.get("last_updated", "")) >= str(old.get("last_updated", "")):
            keep = {"friendly_name", "device_class", "unit_of_measurement", "temperature_unit", "temperature", "current_temperature", "target_temp_low", "target_temp_high", "supported_features", "hvac_modes", "min_temp", "max_temp", "target_temp_step"}
            self.states[ident] = {**{k: state[k] for k in ("entity_id", "state", "last_changed", "last_updated") if k in state}, "attributes": {k: v for k, v in attrs.items() if k in keep}}

    async def listen(self):
        delay = 2
        while True:
            try:
                config = await self.request("config")
                ZoneInfo(config["time_zone"])
                self.timezone = config["time_zone"]
                self.unit = str(config["unit_system"]["temperature"]).replace("\u00b0", "").upper()
                services = await self.request("services")
                self.services = {row["domain"] + "." + name for row in services for name in row.get("services", {})}
                async with self.session.ws_connect("http://supervisor/core/websocket", heartbeat=25, receive_timeout=75,
                        max_msg_size=16 * 1024 * 1024) as ws:
                    hello = await ws.receive_json()
                    if hello.get("type") != "auth_required":
                        raise ValueError("Unexpected Home Assistant handshake.")
                    await ws.send_json({"type": "auth", "access_token": self.token})
                    if (await ws.receive_json()).get("type") != "auth_ok":
                        raise ValueError("Home Assistant did not authorize the app.")
                    await ws.send_json({"id": 1, "type": "subscribe_events", "event_type": "state_changed"})
                    await ws.send_json({"id": 2, "type": "get_states"})
                    await ws.send_json({"id": 3, "type": "subscribe_events", "event_type": "mobile_app_notification_action"})
                    initial = False
                    async for message in ws:
                        if message.type != WSMsgType.TEXT:
                            if message.type in {WSMsgType.CLOSED, WSMsgType.ERROR, WSMsgType.CLOSE}:
                                break
                            continue
                        packet = json.loads(message.data)
                        if packet.get("type") == "result" and packet.get("success") is False:
                            raise ValueError("Home Assistant subscription could not be established.")
                        if packet.get("id") == 2 and packet.get("type") == "result":
                            buffered = self.states
                            self.states = {}
                            for state in packet["result"]:
                                self.update(state)
                            for state in buffered.values():
                                self.update(state)
                            initial = self.connected = True
                            self.notice, delay = "", 2
                        elif packet.get("type") == "event":
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
                # Never treat a snapshot from an earlier connection as fresh.
                self.states = {}
            await asyncio.sleep(delay)
            delay = min(60, delay * 2)
