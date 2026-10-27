"""One local WebSocket, filtered subscriptions and a bounded disk-writer queue."""
import asyncio
import json
import sqlite3
import time
from datetime import datetime, timezone
from aiohttp import WSMsgType
from model import Catalog, EVENTS, normalize


def system_event(message):
    return {"at": datetime.now(timezone.utc).isoformat(), "kind": "coverage", "title": message, "name": "",
            "entities": [], "context": "", "parent": "", "user": False, "details": {}}


class Collector:
    def __init__(self, session, token, store):
        self.session, self.token, self.store = session, token, store
        self.catalog = Catalog()
        self.queue = asyncio.Queue(maxsize=2048)
        self.connected = False
        self.notice = "Connecting to Home Assistant."
        self.timezone = "UTC"
        self.dropped, self.recorded, self.pending_loss = 0, 0, 0
        self.last_received = None
        self.storage_error = ""
        self.registry_ready = False
        self.stopping = False
        self.monotonic = time.monotonic

    def enqueue(self, row):
        if not row:
            return
        if self.queue.full():
            self.dropped += 1
            self.pending_loss += 1
        else:
            self.queue.put_nowait(row)

    async def writer(self):
        while not self.stopping or not self.queue.empty():
            try:
                first = await asyncio.wait_for(self.queue.get(), timeout=60)
            except asyncio.TimeoutError:
                # Retention expires even if the house is quiet.
                try:
                    await asyncio.to_thread(self.store.prune)
                    self.storage_error = ""
                except (sqlite3.Error, OSError):
                    self.storage_error = "Local history storage is unavailable. New recording may have gaps."
                continue
            batch = [first]
            # At most one second of events per transaction, without polling HA.
            await asyncio.sleep(0.5)
            while not self.queue.empty() and len(batch) < 100:
                batch.append(self.queue.get_nowait())
            loss = self.pending_loss
            if loss:
                batch.insert(0, system_event(f"Recording gap: {loss} events could not be recorded. Explanations for this interval may be incomplete."))
            try:
                await asyncio.to_thread(self.store.append, batch)
                self.recorded += len(batch)
                self.pending_loss = max(0, self.pending_loss-loss)
                self.storage_error = ""
            except (sqlite3.Error, OSError):
                self.dropped += len(batch)
                self.pending_loss += len(batch)
                self.storage_error = "Local history storage is unavailable or full. This batch was not retried; recording may have gaps."
                # Pruning may free capacity after a full-disk/full-budget failure.
                try:
                    await asyncio.to_thread(self.store.make_room)
                except (sqlite3.Error, OSError):
                    pass

    def receive_event(self, event):
        self.last_received = datetime.now(timezone.utc).isoformat()
        row = normalize(event, self.catalog)
        if row and not set(row["entities"]) & set(self.store.settings["excluded"]):
            self.enqueue(row)

    async def listen(self):
        delay = 2
        while True:
            self.connected = False
            self.registry_ready = False
            try:
                if not self.token:
                    raise ValueError("HA API token unavailable")
                async with self.session.ws_connect("http://supervisor/core/websocket", heartbeat=25, receive_timeout=75, max_msg_size=16*1024*1024) as ws:
                    if (await ws.receive_json()).get("type") != "auth_required":
                        raise ValueError("Unexpected handshake")
                    await ws.send_json({"type": "auth", "access_token": self.token})
                    if (await ws.receive_json()).get("type") != "auth_ok":
                        raise ValueError("Not authorized")
                    self.catalog = Catalog()
                    for ident, kind in enumerate(EVENTS, 1):
                        await ws.send_json({"id": ident, "type": "subscribe_events", "event_type": kind})
                    requests = {20: "get_states", 21: "config/entity_registry/list", 22: "config/device_registry/list", 23: "config/area_registry/list", 24: "get_config"}
                    for ident, kind in requests.items():
                        await ws.send_json({"id": ident, "type": kind})
                    for ident, kind in enumerate(("entity_registry_updated", "device_registry_updated", "area_registry_updated"), 30):
                        await ws.send_json({"id": ident, "type": "subscribe_events", "event_type": kind})
                    subscriptions, ready, registry, refresh_due = set(), False, set(), False
                    reply_map, next_id = {}, 100
                    refreshed = self.monotonic()
                    async for message in ws:
                        if message.type != WSMsgType.TEXT:
                            if message.type in {WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR}:
                                break
                            continue
                        packet = json.loads(message.data)
                        ident = packet.get("id")
                        if packet.get("type") == "result":
                            ident = reply_map.pop(ident, ident)
                        if packet.get("type") == "result":
                            success, result = packet.get("success"), packet.get("result")
                            if ident in range(1, len(EVENTS)+1):
                                if not success:
                                    raise ValueError("Required event subscription unavailable")
                                subscriptions.add(ident)
                            elif ident == 20:
                                if not success or not isinstance(result, list):
                                    raise ValueError("Entity catalog unavailable")
                                for state in result[:20000]:
                                    self.catalog.state(state)
                                ready = True
                            elif ident in {21, 22, 23}:
                                if success and isinstance(result, list):
                                    if ident == 21:
                                        self.catalog.registry = {r["entity_id"]: {k: r.get(k) for k in ("device_id", "area_id")} for r in result[:20000] if isinstance(r, dict) and isinstance(r.get("entity_id"), str)}
                                    elif ident == 22:
                                        self.catalog.devices = {r["id"]: {"area_id": r.get("area_id"), "name": str(r.get("name_by_user") or r.get("name") or r["id"])[:160]} for r in result[:20000] if isinstance(r, dict) and isinstance(r.get("id"), str)}
                                    else:
                                        self.catalog.areas = {r["area_id"]: r.get("name", "")[:120] for r in result[:2000] if isinstance(r, dict) and isinstance(r.get("area_id"), str)}
                                    registry.add(ident)
                                self.registry_ready = len(registry) == 3
                            elif ident == 24 and success and isinstance(result, dict):
                                self.timezone = result.get("time_zone", "UTC")
                            if ready and len(subscriptions) == len(EVENTS) and not self.connected:
                                self.connected, self.notice, delay = True, "Recording available HA events.", 2
                                self.enqueue(system_event("Connected. Recording begins here; events before this connection or during gaps are not backfilled."))
                        elif packet.get("type") == "event":
                            event = packet.get("event", {})
                            if event.get("event_type") in EVENTS:
                                self.receive_event(event)
                            elif event.get("event_type") in {"entity_registry_updated", "device_registry_updated", "area_registry_updated"}:
                                refresh_due = True
                            if refresh_due and self.monotonic()-refreshed >= 30:
                                self.registry_ready = False
                                registry.clear()
                                for request_id in (21, 22, 23):
                                    reply_map[next_id] = request_id
                                    await ws.send_json({"id": next_id, "type": requests[request_id]})
                                    next_id += 1
                                refresh_due, refreshed = False, self.monotonic()
                    raise ValueError("Connection closed")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Do not print packets, credentials or provider error bodies.
                self.connected = False
                reasons = {"HA API token unavailable": "Home Assistant API access is unavailable.", "Not authorized": "Home Assistant did not authorize Insight.",
                           "Required event subscription unavailable": "A required HA event subscription was rejected.", "Entity catalog unavailable": "The HA entity catalog is unavailable."}
                reason = reasons.get(str(exc), "The local Home Assistant event connection was interrupted.")
                self.notice = reason + " Retrying automatically; events during this gap cannot be recorded."
                self.enqueue(system_event(reason + " Event coverage has a gap until reconnect."))
                await asyncio.sleep(delay)
                delay = min(delay*2, 60)
