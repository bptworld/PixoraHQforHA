"""Bounded local thermostat tools; no device writes or global polling."""
import copy
import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def stamp(raw):
    try:
        value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return value if value.tzinfo else None
    except (ValueError, TypeError):
        return None


def freshness(state, now, minutes):
    # last_updated means VALUE changed, not that the integration reported again.
    # Never call an unchanged temperature stale based on that timestamp.
    reported = stamp((state or {}).get("last_reported"))
    if not reported or reported > now + timedelta(seconds=60):
        return {"state": "unverified", "ageMinutes": None}
    age = max(0, (now - reported).total_seconds() / 60)
    return {"state": "stale" if age > minutes else "current", "ageMinutes": round(age, 1)}


def indoor_value(state, unit, fallback_unit):
    if not state or not isinstance(state.get("state"), str) or state.get("state") in {"unknown", "unavailable"}:
        raise ValueError("Indoor temperature is unavailable.")
    attrs = state.get("attributes", {})
    climate = str(state.get("entity_id", "")).startswith("climate.")
    raw = attrs.get("current_temperature") if climate else state.get("state")
    source = str(attrs.get("temperature_unit") or attrs.get("unit_of_measurement") or (fallback_unit if climate else "")).replace("°", "").upper()
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError("Indoor temperature is unavailable.")
    if source not in {"F", "C"} or not math.isfinite(value):
        raise ValueError("Indoor temperature is unavailable.")
    return value if source == unit else (value - 32) * 5 / 9 if unit == "C" else value * 9 / 5 + 32


def household(config, states, runtime, now):
    if not config.get("enabled"):
        runtime.pop("household", None)
        return False, "Household automation is off."
    previous = runtime.get("household", {})
    binding = [sorted(config["people"]), config["away"], config["awayMinutes"], config["homeMinutes"]]
    if previous.get("binding") != binding:
        previous = {"away": False, "binding": copy.deepcopy(binding)}
    values = []
    for person in config["people"]:
        state = states.get(person, {})
        value = state.get("state")
        if person.startswith("binary_sensor."):
            value = ({"on": "home", "off": "not_home"}.get(value)
                     if isinstance(value, str) and state.get("attributes", {}).get("device_class") in {"presence", "occupancy"} else None)
        values.append(value if isinstance(value, str) else None)
    unknown = any(v in {None, "", "unknown", "unavailable"} for v in values)
    wanted = False if "home" in values else None if unknown else True
    if wanted is None:
        previous.pop("candidate", None); previous.pop("since", None)
        detail = "Presence is unknown; keeping the last household mode."
    elif wanted == previous["away"]:
        previous.pop("candidate", None); previous.pop("since", None)
        detail = "Everyone is confirmed away." if wanted else "Someone is home."
    else:
        if previous.get("candidate") != wanted:
            previous.update(candidate=wanted, since=now.isoformat())
        delay = config["awayMinutes"] if wanted else config["homeMinutes"]
        if (now - stamp(previous["since"])).total_seconds() >= delay * 60:
            previous["away"] = wanted
            previous.pop("candidate", None); previous.pop("since", None)
            detail = "Everyone is confirmed away." if wanted else "Someone is home."
        else:
            detail = "Waiting for the household " + ("away" if wanted else "home") + " delay."
    runtime["household"] = previous
    return previous["away"], detail


class RuntimeHistory:
    """Observed activity only. Never fills restart, disconnect or long gaps."""
    def __init__(self, saved=None):
        self.data = copy.deepcopy(saved or {})
        if not isinstance(self.data, dict) or len(self.data) > 12:
            raise ValueError("Saved runtime history is invalid.")
        for record in self.data.values():
            if not isinstance(record, dict) or not isinstance(record.get("entity"), str) or not isinstance(record.get("days"), dict) or len(record["days"]) > 90:
                raise ValueError("Saved runtime history is invalid.")
            for day, row in record["days"].items():
                datetime.strptime(day, "%Y-%m-%d")
                if not isinstance(row, dict) or set(row) != {"heating", "cooling", "idle", "off", "unknown"} or any(type(v) not in {int, float} or not math.isfinite(v) or not 0 <= v <= 100000 for v in row.values()):
                    raise ValueError("Saved runtime history is invalid.")
        self.samples = {}
        self.persisted = None

    def sample(self, zone, state, connected, now, timezone_name):
        ident = zone["id"]
        record = self.data.get(ident)
        if not record or record.get("entity") != zone["entity"]:
            record = {"entity": zone["entity"], "days": {}}
            self.data[ident] = record
        raw = (state or {}).get("attributes", {}).get("hvac_action")
        action = raw if connected and zone["enabled"] and isinstance(raw, str) and raw in {"heating", "cooling", "idle", "off"} else "unknown"
        previous = self.samples.get(ident)
        dirty = False
        if previous and connected and previous["connected"] and previous["enabled"] and zone["enabled"]:
            elapsed = (now - previous["at"]).total_seconds()
            if 0 < elapsed <= 30:
                start = previous["at"]
                while start < now:
                    local = start.astimezone(ZoneInfo(timezone_name))
                    midnight = datetime.combine(local.date() + timedelta(days=1), datetime.min.time(), ZoneInfo(timezone_name)).astimezone(timezone.utc)
                    end = min(now, midnight)
                    row = record["days"].setdefault(local.date().isoformat(), {k: 0 for k in ("heating", "cooling", "idle", "off", "unknown")})
                    row[previous["action"]] += (end-start).total_seconds()
                    start = end
                dirty = True
        self.samples[ident] = {"at": now, "action": action, "connected": connected, "enabled": zone["enabled"]}
        days = sorted(record["days"])[-90:]
        record["days"] = {day: record["days"][day] for day in days}
        changed = previous and previous["action"] != action
        return dirty and (changed or self.persisted is None or (now-self.persisted).total_seconds() >= 300)
