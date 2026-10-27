"""Small, allowlisted projections of HA events. Never store raw event payloads."""
import json
import math
import re
from datetime import datetime, timezone

ENTITY = re.compile(r"[a-z_]+\.[a-z0-9_]+$")
EVENTS = ("state_changed", "call_service", "automation_triggered", "script_started", "pixora_insight")
ATTRIBUTES = {"brightness", "color_temp_kelvin", "rgb_color", "percentage", "preset_mode", "current_position", "position", "temperature", "current_temperature", "target_temp_low", "target_temp_high", "hvac_action", "hvac_mode", "fan_mode", "swing_mode", "humidity", "current_humidity", "volume_level", "is_volume_muted", "source", "speed", "effect", "option"}
PRIVATE_DOMAINS = {"conversation", "notify", "persistent_notification", "tts", "stt", "camera", "image"}
STATES = {"on", "off", "open", "closed", "opening", "closing", "locked", "unlocked", "locking", "unlocking", "jammed", "home", "not_home", "unknown", "unavailable", "idle", "playing", "paused", "buffering", "streaming", "recording", "standby", "heat", "cool", "heat_cool", "auto", "dry", "fan_only", "armed_home", "armed_away", "armed_night", "disarmed", "triggered", "pending", "arming", "docked", "cleaning", "returning", "error", "ok", "detected", "clear"}


def text(value, length=160):
    return value[:length] if isinstance(value, str) else ""


def ids(value, entities=False):
    values = value if isinstance(value, list) else [value]
    return list(dict.fromkeys(v[:160] for v in values[:256] if isinstance(v, str) and (ENTITY.fullmatch(v) if entities else len(v) <= 160)))


def scalar(value):
    if value is None or type(value) is bool:
        return value
    if type(value) in {int, float}:
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return value[:120]
    if isinstance(value, (list, tuple)):
        return [scalar(v) for v in value[:8] if not isinstance(v, (dict, list, tuple))]
    return None


def projection(state):
    if not isinstance(state, dict):
        return None
    attrs = state.get("attributes") or {}
    if not isinstance(attrs, dict):
        attrs = {}
    value = state.get("state")
    safe = value if isinstance(value, str) and value in STATES else None
    if safe is None:
        try:
            number = float(value)
            safe = value[:48] if isinstance(value, str) and math.isfinite(number) and len(value) <= 48 else scalar(value) if type(value) in {int, float} else "Value changed (contents omitted)"
        except (ValueError, TypeError, OverflowError):
            safe = "Value changed (contents omitted)"
    # Free-text state and location values are intentionally excluded. A change
    # still records below even when both redacted projections look identical.
    return {"state": safe, "attributes": {k: scalar(attrs[k]) for k in sorted(ATTRIBUTES & attrs.keys())}}


def timestamp(raw):
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo:
            return dt.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError, AttributeError, OverflowError):
        pass
    return datetime.now(timezone.utc).isoformat()


class Catalog:
    def __init__(self):
        self.entities, self.registry, self.devices, self.areas = {}, {}, {}, {}

    def name(self, ident):
        return self.entities.get(ident, {}).get("name") or ident

    def state(self, state):
        if not isinstance(state, dict):
            return
        ident = state.get("entity_id")
        if not isinstance(ident, str) or not ENTITY.fullmatch(ident):
            return
        if len(self.entities) >= 20000 and ident not in self.entities:
            return
        attrs = state.get("attributes") or {}
        if not isinstance(attrs, dict):
            attrs = {}
        self.entities[ident] = {"id": ident, "name": text(attrs.get("friendly_name")) or ident}

    def targets(self, data):
        supplied = data.get("target") if isinstance(data.get("target"), dict) else {}
        supplied = {**data, **supplied}
        result = {k: ids(supplied.get(k), k == "entity_id") for k in ("entity_id", "device_id", "area_id", "floor_id", "label_id") if supplied.get(k) is not None}
        resolved = set(result.get("entity_id", []))
        if supplied.get("entity_id") == "all":
            result["entity_id"] = ["all"]
            # A domain-wide request is recorded, but no guessed affected devices.
        device_ids, area_ids = set(result.get("device_id", [])), set(result.get("area_id", []))
        for ident, row in self.registry.items():
            device = self.devices.get(row.get("device_id"), {})
            if row.get("device_id") in device_ids or (row.get("area_id") or device.get("area_id")) in area_ids:
                resolved.add(ident)
        return result, sorted(resolved)[:256]


def normalize(event, catalog):
    if not isinstance(event, dict) or event.get("event_type") not in EVENTS:
        return None
    kind = event["event_type"]
    data = event.get("data")
    if not isinstance(data, dict):
        return None
    context = event.get("context") or {}
    details, entities, title, name = {}, [], "", ""
    if kind == "state_changed":
        ident = data.get("entity_id")
        if not isinstance(ident, str) or not ENTITY.fullmatch(ident) or ident.split(".")[0] in PRIVATE_DOMAINS - {"camera", "image"}:
            return None
        old, new = data.get("old_state"), data.get("new_state")
        before, after = projection(old), projection(new)
        hidden_change = isinstance(old, dict) and isinstance(new, dict) and old.get("state") != new.get("state")
        if before == after and not hidden_change:
            return None
        catalog.state(new or old)
        name = catalog.name(ident)
        entities = [ident]
        # Entity values can contain free text or URLs; store only device state
        # and allowlisted controls. Sensitive text/location attributes never enter DB.
        if re.search(r"(?:^|[._\s])(?:latitude|longitude|gps|password|secret|token|api_key|pin|address)(?:$|[._\s])", ident + " " + name.lower()):
            before = {"state": "Contents omitted", "attributes": {}} if before else None
            after = {"state": "Contents omitted", "attributes": {}} if after else None
            hidden_change = True
        details = {"before": before, "after": after}
        if isinstance(new, dict) and isinstance(new.get("context"), dict):
            context = new["context"]
        a, b = before.get("state") if before else "not present", after.get("state") if after else "removed"
        title = f"{name}: {a} → {b}" if a != b else name + (": value changed (contents omitted)" if hidden_change else ": attributes changed")
        if new is None:
            catalog.entities.pop(ident, None)
    elif kind == "call_service":
        domain, service = text(data.get("domain"), 48), text(data.get("service"), 64)
        if not re.fullmatch(r"[a-z_]+", domain) or not re.fullmatch(r"[a-z0-9_]+", service):
            return None
        fields = data.get("service_data") or {}
        if not isinstance(fields, dict):
            fields = {}
        targets, entities = catalog.targets({**fields, "target": data.get("target", {})})
        if domain in PRIVATE_DOMAINS:
            details = {"service": domain + "." + service, "content": "Private payload omitted"}
        else:
            details = {"service": domain + "." + service, "targets": targets,
                       "settings": {k: scalar(fields[k]) for k in sorted(ATTRIBUTES & fields.keys())}}
        title = "Requested " + domain + "." + service
    elif kind in {"automation_triggered", "script_started"}:
        entities = ids(data.get("entity_id"), True)
        name = text(data.get("name")) or (catalog.name(entities[0]) if entities else kind.replace("_", " "))
        title = ("Automation triggered: " if kind == "automation_triggered" else "Script started: ") + name
        # Trigger descriptions can include templates or private contents. Do not copy.
    else:
        # Opt-in contract for apps to report decisions. No raw metadata accepted.
        entities = ids(data.get("entity_id"), True)
        source = text(data.get("source"), 80)
        reason = text(data.get("reason"), 600)
        outcome = data.get("outcome")
        if not source or not reason or not isinstance(outcome, str) or outcome not in {"requested", "confirmed", "blocked", "waiting", "cancelled"}:
            return None
        operation = text(data.get("operation"), 100)
        if not entities and not re.fullmatch(r"[a-z_]+\.[a-z0-9_]+", operation):
            return None
        details = {"source": source, "reason": reason, "outcome": outcome}
        if operation:details["operation"] = operation
        if isinstance(data.get("target_name"), str):details["targetName"] = text(data["target_name"], 120)
        action_context = data.get("action_context")
        if isinstance(action_context, str) and re.fullmatch(r"[A-Za-z0-9_-]{16,80}", action_context):
            # The sender explicitly reports the context returned by HA for its
            # device action. Keep it labelled as source-reported provenance.
            context = {"id": action_context}
            details["actionContext"] = action_context
        title = source + ": " + (operation.replace('_',' ') + " " if operation else "") + outcome
        if details.get("targetName"):title += " · " + details["targetName"]
    devices = {catalog.registry.get(entity, {}).get("device_id") for entity in entities}
    devices.update(details.get("targets", {}).get("device_id", []))
    devices = sorted(d for d in devices if isinstance(d, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,160}", d))
    if devices: details["deviceIds"] = devices[:256]
    context = context if isinstance(context, dict) else {}
    return {"at": timestamp(event.get("time_fired")), "kind": kind, "title": title[:350], "name": name,
            "entities": entities, "context": text(context.get("id"), 80), "parent": text(context.get("parent_id"), 80),
            "user": bool(context.get("user_id")), "details": details}


def valid_exclusion(value):
    return isinstance(value, str) and bool(ENTITY.fullmatch(value) or re.fullmatch(r"device:[A-Za-z0-9_-]{1,160}", value) or re.fullmatch(r"app-target:[^\x00-\x1f]{1,203}", value))


def target_exclusion(row):
    details = row.get("details", {})
    if row.get("kind") == "pixora_insight" and details.get("source") and details.get("targetName"):
        return "app-target:" + details["source"] + " / " + details["targetName"]
    return ""


def validate_settings(value):
    if not isinstance(value, dict) or set(value) != {"days", "limit", "excluded"}:
        raise ValueError("Choose retention days, event limit and excluded entities.")
    if type(value["days"]) is not int or not 1 <= value["days"] <= 14:
        raise ValueError("Keep between 1 and 14 days.")
    if type(value["limit"]) is not int or not 1000 <= value["limit"] <= 50000:
        raise ValueError("Keep between 1,000 and 50,000 events.")
    if not isinstance(value["excluded"], list) or len(value["excluded"]) > 500 or any(not valid_exclusion(v) for v in value["excluded"]):
        raise ValueError("Choose up to 500 valid entity IDs or app display exclusions.")
    return {**value, "excluded": sorted(set(value["excluded"]))}
