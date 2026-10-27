"""Small, deterministic thermostat policies. No network or device writes."""
import math
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ENTITY = re.compile(r"[a-z_]+\.[a-z0-9_]+$")
MODES = {"heat", "cool", "heat_cool", "off"}


def number(value, low, high, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{label} must be between {low} and {high}.")
    return value


def entity(value, domains, label, optional=False):
    if optional and value == "":
        return value
    if not isinstance(value, str) or not ENTITY.fullmatch(value) or value.split(".")[0] not in domains:
        raise ValueError("Choose a valid " + label + ".")
    return value


def validate(value):
    if not isinstance(value, dict) or set(value) != {"zones"} or not isinstance(value["zones"], list) or len(value["zones"]) > 12:
        raise ValueError("Use up to 12 thermostat controllers.")
    ids, thermostats = set(), set()
    for z in value["zones"]:
        if not isinstance(z, dict) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", str(z.get("id", ""))) or z["id"] in ids:
            raise ValueError("Use unique controller identities.")
        ids.add(z["id"])
        if not isinstance(z.get("name"), str) or not 1 <= len(z["name"].strip()) <= 80:
            raise ValueError("Enter a controller name.")
        entity(z.get("entity"), {"climate"}, "thermostat")
        if z["entity"] in thermostats:
            raise ValueError("A thermostat can belong to only one controller.")
        thermostats.add(z["entity"])
        if type(z.get("enabled")) is not bool or z.get("unit") not in {"F", "C"}:
            raise ValueError("Choose enabled state and temperature unit.")
        for k, low, high in (("openMinutes", 0, 120), ("closeMinutes", 0, 30), ("manualMinutes", 5, 1440), ("setback", -40, 120)):
            number(z.get(k), low, high, k)
        openings = z.get("openings")
        if not isinstance(openings, list) or len(openings) > 64 or len(set(openings)) != len(openings):
            raise ValueError("Choose up to 64 unique doors/windows.")
        for ident in openings:
            entity(ident, {"binary_sensor"}, "door/window contact")
        outside = z.get("outdoor")
        if not isinstance(outside, dict) or type(outside.get("enabled")) is not bool:
            raise ValueError("Choose outdoor protection settings.")
        if outside.get("mode") not in {"auto", "ask"}:
            raise ValueError("Choose automatic outdoor protection or ask first.")
        entity(outside.get("entity"), {"sensor", "weather"}, "outdoor temperature", optional=not outside["enabled"])
        number(outside.get("limit"), -40, 120, "Outdoor limit")
        number(outside.get("margin"), .5, 10, "Outdoor return margin")
        notice = z.get("notify")
        if isinstance(notice, dict) and "recipients" in notice:
            recipients = notice["recipients"]
            if not isinstance(recipients, list) or len(recipients) > 32:
                raise ValueError("Add up to 32 notification recipients.")
            destinations = set()
            for recipient in recipients:
                if not isinstance(recipient, dict) or not isinstance(recipient.get("person"), str) or not recipient["person"].strip() or len(recipient["person"]) > 80:
                    raise ValueError("Give each notification recipient a name.")
                recipient["person"] = recipient["person"].strip()
                entity(recipient.get("service"), {"notify"}, "notification destination")
                if recipient["service"] == "notify.send_message":
                    raise ValueError("Choose a named notification destination, not notify.send_message.")
                if recipient["service"] in destinations:
                    raise ValueError("Choose a different notification destination for each recipient.")
                destinations.add(recipient["service"])
            notice.update({key: recipients[0][key] if recipients else "" for key in ("person", "service")})
        if not isinstance(notice, dict) or not isinstance(notice.get("person"), str) or len(notice["person"]) > 80:
            raise ValueError("Choose who receives notifications.")
        entity(notice.get("service"), {"notify"}, "notification destination", optional=True)
        if notice["service"] == "notify.send_message":
            raise ValueError("Choose a named notification destination, not notify.send_message.")
        if bool(notice["person"].strip()) != bool(notice["service"]):
            raise ValueError("Choose both a person and their notification destination.")
        if z["enabled"] and (openings or outside["enabled"]) and not notice["service"]:
            raise ValueError("Choose a notification recipient for protection alerts.")
        if outside["enabled"] and outside["mode"] == "ask" and not notice["service"].startswith("notify.mobile_app_"):
            raise ValueError("Ask first needs a Home Assistant Companion mobile-app notification destination.")
        if outside["enabled"] and outside["mode"] == "ask" and any(not r["service"].startswith("notify.mobile_app_") for r in notice.get("recipients", [])):
            raise ValueError("Ask first needs Companion mobile-app destinations for all recipients.")
        alerts = z.setdefault("alerts", {"setback": True, "restore": True, "sensor": True, "failure": True})
        if not isinstance(alerts, dict) or set(alerts) != {"setback", "restore", "sensor", "failure"} or any(type(v) is not bool for v in alerts.values()):
            raise ValueError("Choose valid notification options.")
        fresh = z.setdefault("freshness", {"enabled": False, "minutes": 60})
        if not isinstance(fresh, dict) or type(fresh.get("enabled")) is not bool:
            raise ValueError("Choose sensor freshness settings.")
        number(fresh.get("minutes"), 5, 1440, "Sensor report age")
        notices = z.setdefault("notificationPolicy", {"cooldownMinutes": 5})
        if not isinstance(notices, dict):
            raise ValueError("Choose notification grouping settings.")
        number(notices.get("cooldownMinutes"), 0, 120, "Notification cooldown")
        quiet = z.setdefault("quietHours", {"enabled": False, "start": "22:00", "end": "07:00", "allowUrgent": True})
        if not isinstance(quiet, dict) or type(quiet.get("enabled")) is not bool or type(quiet.get("allowUrgent")) is not bool:
            raise ValueError("Choose valid notification quiet hours.")
        for key in ("start", "end"):
            if not isinstance(quiet.get(key), str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", quiet[key]):
                raise ValueError("Choose valid quiet-hour start and end times.")
        if quiet["start"] == quiet["end"]:
            raise ValueError("Quiet-hour start and end must be different.")
        home = z.setdefault("household", {"enabled": False, "people": [], "awayMinutes": 5, "homeMinutes": 1, "away": {"mode": "heat", "heat": 60 if z["unit"] == "F" else 16}})
        if isinstance(home, dict) and "members" in home:
            members = home["members"]
            if not isinstance(members, list) or len(members) > 32:
                raise ValueError("Add up to 32 household members.")
            for member in members:
                if not isinstance(member, dict) or not isinstance(member.get("name"), str) or not member["name"].strip() or len(member["name"]) > 80:
                    raise ValueError("Give each household member a name.")
                member["name"] = member["name"].strip()
                entity(member.get("entity"), {"person", "device_tracker", "binary_sensor"}, "household presence source")
            home["people"] = [member["entity"] for member in members]
        if not isinstance(home, dict) or type(home.get("enabled")) is not bool or not isinstance(home.get("people"), list) or len(home["people"]) > 32 or any(not isinstance(person, str) for person in home["people"]) or len(set(home["people"])) != len(home["people"]):
            raise ValueError("Choose up to 32 unique household people.")
        for person in home["people"]:
            entity(person, {"person", "device_tracker", "binary_sensor"}, "household presence source")
        if home["enabled"] and not home["people"]:
            raise ValueError("Choose household people before enabling Home/Away.")
        number(home.get("awayMinutes"), 0, 120, "Household away delay")
        number(home.get("homeMinutes"), 0, 120, "Household home delay")
        if not isinstance(home.get("away"), dict):
            raise ValueError("Choose a household Away target.")
        target(home["away"])
        indoor = z.setdefault("indoorAlerts", {"enabled": False, "entity": "", "low": 45 if z["unit"] == "F" else 7, "high": 90 if z["unit"] == "F" else 32, "minutes": 10, "margin": 2})
        if not isinstance(indoor, dict) or type(indoor.get("enabled")) is not bool:
            raise ValueError("Choose indoor temperature alert settings.")
        entity(indoor.get("entity"), {"sensor"}, "indoor temperature sensor", optional=True)
        number(indoor.get("low"), -40, 140, "Indoor low warning")
        number(indoor.get("high"), -40, 140, "Indoor high warning")
        number(indoor.get("minutes"), 0, 120, "Indoor warning delay")
        number(indoor.get("margin"), .5, 10, "Indoor warning return margin")
        if indoor["low"] + indoor["margin"] >= indoor["high"] - indoor["margin"]:
            raise ValueError("Separate indoor warning thresholds and return margins.")
        if z["enabled"] and indoor["enabled"] and not notice["service"]:
            raise ValueError("Choose a recipient for indoor temperature warnings.")
        schedules = z.get("schedule")
        if not isinstance(schedules, list) or len(schedules) > 64:
            raise ValueError("Use up to 64 weekly schedule periods.")
        occupied, periods = set(), set()
        for row in schedules:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", row["id"]) or row["id"] in periods:
                raise ValueError("Use unique schedule period identities.")
            periods.add(row["id"])
            if "name" in row and (not isinstance(row["name"], str) or not 1 <= len(row["name"].strip()) <= 80):
                raise ValueError("Period names must contain 1 to 80 characters.")
            days = row.get("days")
            if not isinstance(days, list) or not days or any(type(d) is not int or not 0 <= d <= 6 for d in days) or len(set(days)) != len(days):
                raise ValueError("Choose the days for each period.")
            if not isinstance(row.get("time"), str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", row["time"]):
                raise ValueError("Use a valid schedule time.")
            target(row)
            for day in days:
                key = (day, row["time"])
                if key in occupied:
                    raise ValueError("Two periods cannot start at the same time on the same day.")
                occupied.add(key)
        if z["enabled"] and not schedules:
            raise ValueError("Add a schedule before enabling a controller.")
    return value


def target(row):
    mode = row.get("mode")
    if mode not in MODES:
        raise ValueError("Choose heat, cool, heat/cool, or off.")
    result = {"mode": mode}
    if mode in {"heat", "heat_cool"}:
        result["heat"] = number(row.get("heat"), -40, 120, "Heat setpoint")
    if mode in {"cool", "heat_cool"}:
        result["cool"] = number(row.get("cool"), -40, 120, "Cool setpoint")
    if mode == "heat_cool" and result["cool"] - result["heat"] < 1:
        raise ValueError("Cooling must be at least one degree above heating.")
    return result


def schedule_at(rows, now, zone):
    tz = ZoneInfo(zone)
    local = now.astimezone(tz)
    candidates = []
    # A repeated fall-back hour must not rewind the active period. Each
    # scheduled local time occurs once, at its first valid occurrence.
    for offset in range(9):
        day = local.date() - timedelta(days=offset)
        for row in rows:
            if day.weekday() not in row["days"]:
                continue
            hour, minute = map(int, row["time"].split(":"))
            at = datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz).astimezone(timezone.utc)
            back = at.astimezone(tz)
            if back.date() == day and back.hour == hour and back.minute == minute and at <= now:
                candidates.append((at, row))
    return max(candidates, key=lambda p: p[0])[1] if candidates else None


def next_period(rows, now, zone):
    tz = ZoneInfo(zone)
    local = now.astimezone(tz)
    candidates = []
    for offset in range(9):
        day = local.date() + timedelta(days=offset)
        for row in rows:
            if day.weekday() not in row["days"]:
                continue
            hour, minute = map(int, row["time"].split(":"))
            for fold in (0,):
                at = datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz, fold=fold).astimezone(timezone.utc)
                back = at.astimezone(tz)
                if back.date() == day and back.hour == hour and back.minute == minute and at > now:
                    candidates.append(at)
    return min(candidates) if candidates else None


def temperature(state, unit):
    if not state or state.get("state") in {"unknown", "unavailable"}:
        raise ValueError("Outdoor temperature is unavailable.")
    attrs = state.get("attributes", {})
    raw = attrs.get("temperature") if state["entity_id"].startswith("weather.") else state.get("state")
    try:
        value = float(raw)
    except (ValueError, TypeError):
        raise ValueError("Outdoor temperature is unavailable.")
    if not math.isfinite(value):
        raise ValueError("Outdoor temperature is unavailable.")
    source = str(attrs.get("temperature_unit") or attrs.get("unit_of_measurement") or "").replace("\u00b0", "").upper()
    if source not in {"F", "C"}:
        raise ValueError("Outdoor temperature needs a Fahrenheit or Celsius unit.")
    return value if source == unit else (value - 32) * 5 / 9 if unit == "C" else value * 9 / 5 + 32


def observed(state):
    a = state.get("attributes", {})
    mode = state.get("state")
    result = {"mode": mode}
    if mode in {"heat", "cool"}:
        result[mode] = a.get("temperature")
    elif mode == "heat_cool":
        result.update(heat=a.get("target_temp_low"), cool=a.get("target_temp_high"))
    return target(result)


def same(actual, wanted):
    return actual.get("mode") == wanted.get("mode") and all(k == "mode" or isinstance(actual.get(k), (int, float)) and abs(actual[k] - v) < .1 for k, v in wanted.items())


def service_for(wanted, state, unit, ha_unit, services):
    a = state.get("attributes", {})
    actual_unit = str(a.get("temperature_unit") or ha_unit).replace("\u00b0", "").upper()
    if actual_unit != unit:
        raise ValueError("Controller units must match the thermostat's Home Assistant unit.")
    if state.get("state") in {"unknown", "unavailable"}:
        raise ValueError("Thermostat is unavailable; no command sent.")
    mode = wanted["mode"]
    if mode not in a.get("hvac_modes", []):
        raise ValueError("The thermostat does not support " + mode + " mode.")
    fields = {"entity_id": state["entity_id"]}
    name = "set_hvac_mode" if mode == "off" else "set_temperature"
    if "climate." + name not in services:
        raise ValueError("The thermostat action is unavailable.")
    fields["hvac_mode"] = mode
    if mode != "off":
        if not int(a.get("supported_features") or 0) & (2 if mode == "heat_cool" else 1):
            raise ValueError("The thermostat does not support this target-temperature control.")
        for key in ("heat", "cool"):
            if key not in wanted:
                continue
            low, high = a.get("min_temp"), a.get("max_temp")
            if not isinstance(low, (int, float)) or not isinstance(high, (int, float)) or not low <= wanted[key] <= high:
                raise ValueError("A requested setpoint is outside the thermostat's reported range.")
            step = a.get("target_temp_step")
            if isinstance(step, (int, float)) and not isinstance(step, bool) and math.isfinite(step) and step > 0:
                quotient = (wanted[key] - low) / step
                if not math.isclose(quotient, round(quotient), abs_tol=1e-7):
                    raise ValueError("Choose a setpoint in the thermostat's supported increments of " + str(step) + " degrees.")
            fields[("target_temp_low" if key == "heat" else "target_temp_high") if mode == "heat_cool" else "temperature"] = wanted[key]
    return "climate." + name, fields
