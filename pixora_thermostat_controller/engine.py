"""Local schedule/guard coordinator; the thermostat still regulates its equipment."""
import asyncio
import copy
import json
import os
import tempfile
import secrets
import time
import math
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from policy import schedule_at, next_period, target, temperature, observed, same, service_for


def clock_time(value):
    hour, minute = map(int, value.split(":"))
    return f"{hour % 12 or 12}:{minute:02d} {'AM' if hour < 12 else 'PM'}"


def hold_detail(hold, zone):
    if hold.get("returnPerson"):
        return "Until the selected person returns home"
    end = datetime.fromisoformat(hold["until"]).astimezone(ZoneInfo(zone))
    return f"Until {end.strftime('%b')} {end.day}, {end.year} at {clock_time(end.strftime('%H:%M'))}"


def target_text(wanted, unit):
    if wanted["mode"] == "off":
        return "Off"
    return " / ".join(key.capitalize() + f" {wanted[key]:g}°{unit}" for key in ("heat", "cool") if key in wanted)


def utcnow():
    return datetime.now(timezone.utc)


class Store:
    def __init__(self, root):
        self.path = Path(root) / "controller.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = {"revision": 0, "zones": [], "runtime": {}, "events": []}
        if self.path.exists():
            # Corrupt data must never become a new empty configuration.
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(self.data, dict) or not all(k in self.data for k in ("revision", "zones", "runtime", "events")) or type(self.data["revision"]) is not int or not isinstance(self.data["runtime"], dict) or not isinstance(self.data["events"], list):
                raise ValueError("Saved thermostat data is unreadable. Restore an app backup.")
            for runtime in self.data["runtime"].values():
                if not isinstance(runtime, dict):
                    raise ValueError("Saved thermostat runtime is unreadable. Restore an app backup.")
                for key, when in (("pending", "at"), ("override", "until"), ("approval", "until")):
                    item = runtime.get(key)
                    if item:
                        if not isinstance(item, dict) or not isinstance(item.get(when), str) or datetime.fromisoformat(item[when]).tzinfo is None:
                            raise ValueError("Saved thermostat runtime is unreadable. Restore an app backup.")

    def write(self, value):
        content = json.dumps(value, ensure_ascii=True, allow_nan=False)
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as f:
                tmp = Path(f.name)
                os.chmod(tmp, 0o600)
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            tmp.replace(self.path)
            self.data = copy.deepcopy(value)
        finally:
            if tmp:
                tmp.unlink(missing_ok=True)

    def patch_runtime(self, ident, runtime, message=None, kind="info"):
        value = copy.deepcopy(self.data)
        value["runtime"][ident] = runtime
        if message:
            value["events"].append({"at": utcnow().isoformat(), "zone": ident, "message": message, "kind": kind})
            value["events"] = value["events"][-200:]
        self.write(value)


class Engine:
    def __init__(self, store, ha, now=utcnow):
        self.store, self.ha, self.now = store, ha, now
        self.lock = asyncio.Lock()
        self.timers = {}
        self.status = {}
        self.voice_seen = deque(maxlen=64)
        self.contact_notice_since = {}

    async def send_notice(self, z, fields):
        service = z["notify"]["service"]
        recipient = z["notify"]["person"]
        message = fields["message"]
        try:
            if service not in self.ha.services:
                raise ValueError("Notification destination unavailable.")
            await self.ha.call(service, fields)
        except (ValueError, OSError, asyncio.TimeoutError):
            self.store.patch_runtime(z["id"], self.store.data["runtime"].get(z["id"], {}),
                f"Notification to {recipient} ({service}) could not be confirmed; it was not retried. Message: {message}", "warning")
            raise
        self.store.patch_runtime(z["id"], self.store.data["runtime"].get(z["id"], {}),
            f"Notification sent to {recipient} ({service}): {message}")

    async def tick(self):
        async with self.lock:
            active = {z["id"] for z in self.store.data["zones"]}
            self.contact_notice_since = {k: v for k, v in self.contact_notice_since.items() if k in active}
            voice = getattr(self.ha, "voice", None)
            while voice is not None and not voice.empty():
                request = voice.get_nowait()
                await self.handle_voice(request)
            while not self.ha.actions.empty():
                action = self.ha.actions.get_nowait()
                try:
                    self.handle_approval(action)
                except (ValueError, OSError, TypeError, KeyError):
                    # Fail closed for this tick; retain a live loop for recovery.
                    for zone in self.store.data["zones"]:
                        self.status[zone["id"]] = {"reason": "Needs attention", "detail": "Notification response could not be saved. No approval assumed; automatic changes paused for this check."}
                    return
            for zone in copy.deepcopy(self.store.data["zones"]):
                try:
                    await self.evaluate(zone)
                    issue = self.status.get(zone["id"], {})
                    await self.issue_notice(zone, issue.get("detail", "") if issue.get("reason") == "Check thermostat" else "", "failure")
                except (ValueError, OSError, TypeError, KeyError) as exc:
                    self.status[zone["id"]] = {"reason": "Needs attention", "detail": str(exc)[:16384]}
                    try:
                        await self.issue_notice(zone, str(exc)[:16384], "sensor" if "unavailable" in str(exc).lower() else "failure")
                    except (ValueError, OSError, TypeError, KeyError):
                        pass

    async def issue_notice(self, z, message, category):
        if not z["enabled"] or not self.ha.connected:
            self.contact_notice_since.pop(z["id"], None)
            return
        if category == "sensor" and message.startswith("Door/window readings unavailable:"):
            # Only delay the notification, never the safety decision in evaluate.
            # One continuous outage keeps its age even if the affected set changes.
            since = self.contact_notice_since.setdefault(z["id"], self.now())
            if (self.now() - since).total_seconds() < 60:
                return
        else:
            self.contact_notice_since.pop(z["id"], None)
        # A missing service is not a send attempt. Wait for its registration;
        # after an actual attempt the durable claim still prevents retries.
        if message and z.get("alerts", {}).get(category, True) and z["notify"]["service"] not in self.ha.services:
            return
        runtime = copy.deepcopy(self.store.data["runtime"].get(z["id"], {}))
        if runtime.get("issue", "") == message:
            return
        runtime["issue"] = message
        self.store.patch_runtime(z["id"], runtime)
        if message and z.get("alerts", {}).get(category, True) and z["notify"]["service"] in self.ha.services:
            problems = self.problem_sensors(z, runtime) if category == "sensor" else []
            if problems and z["notify"]["service"].startswith("notify.mobile_app_"):
                for sensor in problems:
                    runtime = copy.deepcopy(self.store.data["runtime"].get(z["id"], {}))
                    actions = runtime.setdefault("sensorActions", {})
                    if sensor in actions:
                        continue
                    token = secrets.token_hex(16)
                    actions[sensor] = token
                    self.store.patch_runtime(z["id"], runtime)
                    name = self.sensor_name(sensor)
                    prefix = "pixora_thermostat:" + token + ":"
                    try:
                        await self.send_notice(z, {"title": z["name"] + ": " + name, "message": message + " Okay keeps protection unchanged. Ignore excludes only " + name + " until you mark it Fixed in the app.", "data": {"tag": "pixora-issue-" + z["id"] + "-" + sensor, "actions": [{"action": prefix + "okay", "title": "Okay"}, {"action": prefix + "ignore", "title": "Ignore"}]}})
                    except (ValueError, OSError, asyncio.TimeoutError):
                        pass
                return
            try:
                await self.send_notice(z, {"title": z["name"], "message": message})
            except (ValueError, OSError, asyncio.TimeoutError):
                pass

    def sensor_name(self, ident):
        return str(self.ha.states.get(ident, {}).get("attributes", {}).get("friendly_name") or ident)

    def problem_sensors(self, z, runtime):
        ignored = runtime.get("ignored", {})
        result = [ident for ident in z["openings"] if ident not in ignored and self.ha.states.get(ident, {}).get("state") not in {"on", "off"}]
        outdoor = z["outdoor"]
        if outdoor["enabled"] and outdoor["entity"] not in ignored:
            try:
                temperature(self.ha.states.get(outdoor["entity"]), z["unit"])
            except ValueError:
                result.append(outdoor["entity"])
        return result

    async def preview(self, z):
        # Copies are bounded by the controller/catalog limits. No real store or
        # service is reachable through this simulation.
        store = copy.copy(self.store)
        store.data = copy.deepcopy(self.store.data)
        store.write = lambda value: setattr(store, "data", copy.deepcopy(value))
        ha = copy.copy(self.ha)
        ha.states = copy.deepcopy(self.ha.states)
        calls = []
        async def capture(service, fields):
            calls.append({"service": service, "data": fields})
        ha.call = capture
        shadow = Engine(store, ha, self.now)
        shadow.timers = copy.deepcopy(self.timers)
        try:
            await shadow.evaluate(copy.deepcopy(z))
        except (ValueError, OSError, TypeError, KeyError) as exc:
            shadow.status[z["id"]] = {"reason": "Needs attention", "detail": str(exc)}
        return {"status": shadow.status.get(z["id"], {}), "wouldSend": calls, "readOnly": True}

    async def handle_voice(self, request):
        ident = request.get("request_id") if isinstance(request, dict) else None
        expires = request.get("expires_at") if isinstance(request, dict) else None
        if not isinstance(ident, str) or len(ident) != 32 or ident in self.voice_seen:
            return
        if not isinstance(expires, (int, float)) or not math.isfinite(expires) or not time.time() < expires <= time.time() + 15:
            return
        self.voice_seen.append(ident)
        reply = {"request_id": ident}
        z = next((z for z in self.store.data["zones"] if z["entity"] == request.get("entity_id")), None)
        try:
            if not self.ha.connected:
                raise ValueError("Home Assistant is reconnecting. I haven't changed the thermostat.")
            if z is None:
                reply["unmanaged"] = True
            else:
                runtime = copy.deepcopy(self.store.data["runtime"].get(z["id"], {}))
                if not z["enabled"] and request.get("service") != "controller_status":
                    raise ValueError("That thermostat controller is disabled. Enable it before asking for an override.")
                if request.get("service") not in {"controller_status", "controller_resume"} and (runtime.get("pending") or runtime.get("blocked")):
                    raise ValueError("Please check the pending thermostat command before asking for another change.")
                if request.get("service") == "controller_status":
                    status = self.status.get(z["id"], {}) if z["enabled"] else {"reason": "Disabled", "detail": "Automatic control is disabled; the thermostat keeps its current settings."}
                    hold = runtime.get("override")
                    reply["speech"] = z["name"] + ": " + status.get("reason", "Starting") + ". " + status.get("detail", "")
                    if hold:
                        remaining = max(0, int((datetime.fromisoformat(hold["until"]) - self.now()).total_seconds() / 60))
                        reply["speech"] += (" Away hold ends when the selected person returns." if hold.get("returnPerson") else f" The override has about {remaining} minutes left.")
                    else:
                        reply["speech"] += " There is no active override."
                    await self.ha.request("events/pixora_thermostat_voice_reply", reply)
                    return
                if request.get("service") == "controller_resume":
                    if runtime.get("pending") or runtime.get("blocked"):
                        raise ValueError("Please check the pending thermostat command first.")
                    runtime["override"] = None
                    self.store.patch_runtime(z["id"], runtime, "Voice resumed schedule; protection remains active.")
                    reply["speech"] = "Okay, I've resumed the schedule. Window and outdoor protections still apply."
                    await self.ha.request("events/pixora_thermostat_voice_reply", reply)
                    return
                if request.get("service") != "set_temperature":
                    raise ValueError("For a managed thermostat, please ask for a temperature. Mode changes belong in Thermostat Controller.")
                state = self.ha.states.get(z["entity"])
                if not state:
                    raise ValueError("I can't reach that thermostat right now.")
                override = runtime.get("override")
                wanted = copy.deepcopy(override["target"] if override and datetime.fromisoformat(override["until"]) > self.now() else target(schedule_at(z["schedule"], self.now(), self.ha.timezone)))
                if wanted["mode"] not in {"heat", "cool"}:
                    raise ValueError("Please choose heat or cool in the controller before requesting one temperature.")
                value = request.get("temperature")
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ValueError("Please ask for a valid temperature.")
                wanted[wanted["mode"]] = value
                service_for(wanted, state, z["unit"], self.ha.unit, self.ha.services)
                runtime["override"] = {"target": wanted, "until": (self.now() + timedelta(minutes=z["manualMinutes"])).isoformat(), "source": "Voice override"}
                self.store.patch_runtime(z["id"], runtime, "Voice timed override saved; window and outdoor protections remain active.")
                reply["speech"] = f"Okay, I've saved a {z['manualMinutes']}-minute override at {value:g} degrees for {z['name']}. Window and outdoor protections still apply."
        except ValueError as exc:
            reply["speech"] = str(exc)
        except (KeyError, TypeError, OSError):
            reply["speech"] = "I couldn't save that thermostat override. Please check the controller; I haven't bypassed its protections."
        try:
            await self.ha.request("events/pixora_thermostat_voice_reply", reply)
        except (ValueError, OSError, asyncio.TimeoutError):
            pass  # No command or override replay after uncertain delivery.

    def handle_approval(self, action):
        for z in self.store.data["zones"]:
            runtime = copy.deepcopy(self.store.data["runtime"].get(z["id"], {}))
            for sensor, token in list(runtime.get("sensorActions", {}).items()):
                prefix = "pixora_thermostat:" + token + ":"
                if action not in {prefix + "okay", prefix + "ignore"}:
                    continue
                if not z["enabled"] or not self.ha.connected or sensor not in self.problem_sensors(z, runtime):
                    return
                runtime["sensorActions"].pop(sensor, None)
                if action.endswith(":ignore"):
                    runtime.setdefault("ignored", {})[sensor] = {"name": self.sensor_name(sensor), "at": self.now().isoformat()}
                    runtime["issue"] = ""
                    self.timers.pop(z["id"], None)
                    message = self.sensor_name(sensor) + " ignored by notification action. Its protection is excluded until marked Fixed."
                else:
                    message = self.sensor_name(sensor) + " issue acknowledged. Protection remains active."
                self.store.patch_runtime(z["id"], runtime, message, "warning" if action.endswith(":ignore") else "info")
                return
            approval = runtime.get("approval")
            if not approval or approval.get("decision") != "pending" or not z["enabled"] or not self.ha.connected:
                continue
            prefix = "pixora_thermostat:" + approval["token"] + ":"
            if action not in {prefix + "yes", prefix + "no"}:
                continue
            if self.now() >= datetime.fromisoformat(approval["until"]):
                return
            try:
                outside = temperature(self.ha.states.get(z["outdoor"]["entity"]), z["unit"])
            except ValueError:
                return
            if not z["outdoor"]["enabled"] or z["outdoor"]["entity"] in runtime.get("ignored", {}) or z["outdoor"]["mode"] != "ask" or outside <= z["outdoor"]["limit"]:
                approval["decision"] = "expired"
                self.store.patch_runtime(z["id"], runtime, "Outdoor action ignored: the temperature rule no longer matches.")
                return
            approval["decision"] = "yes" if action.endswith(":yes") else "no"
            self.store.patch_runtime(z["id"], runtime, "Outdoor heat-off request: " + approval["decision"] + ".")
            return

    async def evaluate(self, z):
        ident, now = z["id"], self.now()
        previous = copy.deepcopy(self.store.data["runtime"].get(ident, {}))
        runtime = copy.deepcopy(previous)
        problems = self.problem_sensors(z, runtime)
        stale = [key for key in runtime.get("sensorActions", {}) if key not in problems]
        if stale:
            for key in stale:
                runtime["sensorActions"].pop(key, None)
            self.store.patch_runtime(ident, runtime)
        timers = self.timers.setdefault(ident, {})
        if not z["enabled"]:
            self.status[ident] = {"reason": "Disabled", "detail": "The thermostat keeps its current settings."}
            self.timers.pop(ident, None)
            return
        if not self.ha.connected:
            self.status[ident] = {"reason": "Reconnecting", "detail": "Waiting for fresh Home Assistant readings. No commands sent."}
            self.timers.pop(ident, None)
            return
        state = self.ha.states.get(z["entity"])
        if not state or state.get("state") in {"unknown", "unavailable"}:
            raise ValueError("Thermostat is unavailable. No commands sent.")
        actual = observed(state)
        # Resolve an acknowledged action from the live thermostat, including after restart.
        pending = runtime.get("pending")
        if pending:
            if same(actual, pending["target"]):
                runtime.update(last=pending["target"], pending=None, blocked="")
                context = pending.get("context") or "Thermostat adjustment"
                runtime["activityContext"] = context
                self.store.patch_runtime(ident, runtime, "Confirmed: " + context + ". Home Assistant reports " + target_text(actual, z["unit"]) + ".")
            elif (now - datetime.fromisoformat(pending["at"])).total_seconds() >= 30:
                runtime["blocked"] = "A thermostat command could not be confirmed. Check the thermostat before resuming; it will not be retried."
        if runtime.get("blocked"):
            self.status[ident] = {"reason": "Check thermostat", "detail": runtime["blocked"]}
            if runtime != previous:
                self.store.patch_runtime(ident, runtime)
            return
        if runtime.get("pending"):
            self.status[ident] = {"reason": "Waiting for thermostat", "detail": "Command sent once; waiting for its live state."}
            return

        override = runtime.get("override")
        if override and datetime.fromisoformat(override["until"]) <= now:
            runtime["override"] = override = None
        if override and override.get("returnPerson"):
            person = self.ha.states.get(override["returnPerson"], {})
            if person.get("state") not in {None, "unknown", "unavailable", "home"}:
                override["seenAway"] = True
            elif person.get("state") == "home" and override.get("seenAway"):
                runtime["override"] = override = None
        # Physical/app changes become a bounded manual hold instead of a control fight.
        if runtime.get("last") and not same(actual, runtime["last"]):
            if not runtime.get("window") and not runtime.get("outdoor") or actual["mode"] == "off":
                override = {"target": actual, "until": (now + timedelta(minutes=z["manualMinutes"])).isoformat(), "source": "Thermostat change"}
                runtime.update(override=override, last=actual)

        row = schedule_at(z["schedule"], now, self.ha.timezone)
        desired = copy.deepcopy(override["target"] if override else target(row)) if row else None
        if not desired:
            raise ValueError("No schedule is configured.")
        reason = "Temporary override" if override else "Schedule"
        detail = hold_detail(override, self.ha.timezone) if override else row.get("name", "Period starting " + clock_time(row["time"])) + " at " + clock_time(row["time"])

        opened, unknown = [], []
        contacts = timers.setdefault("contacts", {})
        close_signature = []
        for sensor in z["openings"]:
            if sensor in runtime.get("ignored", {}):
                continue
            contact = self.ha.states.get(sensor, {})
            close_signature.append((sensor, contact.get("last_changed")))
            if contact.get("state") == "on":
                opened.append(contact.get("attributes", {}).get("friendly_name") or sensor)
                seen = contacts.get(sensor)
                if not seen or seen["stamp"] != contact.get("last_changed"):
                    contacts[sensor] = {"at": now, "stamp": contact.get("last_changed")}
            elif contact.get("state") != "off":
                name = str(contact.get("attributes", {}).get("friendly_name") or sensor)[:160]
                reading = str(contact.get("state") or "missing from Home Assistant")[:80]
                unknown.append(f"{name} ({reading})")
                contacts.pop(sensor, None)
            else:
                contacts.pop(sensor, None)
        # Unknown does not mean closed; never restore a protected thermostat on it.
        if unknown:
            timers.pop("open", None)
            timers.pop("closed", None)
            contacts.clear()
            message = "Door/window readings unavailable: " + "; ".join(unknown) + "."
            if opened:
                message += " Also open: " + ", ".join(opened) + "."
            raise ValueError(message + " Previous protection is retained; no new command sent.")
        if opened:
            timers.pop("closed", None)
            timers["open"] = min(c["at"] for c in contacts.values())
            if (now - timers["open"]).total_seconds() >= z["openMinutes"] * 60:
                runtime["window"] = True
        else:
            timers.pop("open", None)
            if runtime.get("window"):
                if timers.get("closedSignature") != close_signature:
                    timers["closed"] = now
                timers.setdefault("closed", now)
                timers["closedSignature"] = close_signature
                if (now - timers["closed"]).total_seconds() >= z["closeMinutes"] * 60:
                    runtime["window"] = False
        if not any(sensor not in runtime.get("ignored", {}) for sensor in z["openings"]):
            runtime["window"] = False

        outdoor = z["outdoor"]
        outside = None
        if outdoor["enabled"] and outdoor["entity"] not in runtime.get("ignored", {}):
            outside = temperature(self.ha.states.get(outdoor["entity"]), z["unit"])
            if outside > outdoor["limit"]:
                runtime["outdoorCrossed"] = True
            elif outside <= outdoor["limit"] - outdoor["margin"]:
                runtime["outdoorCrossed"] = False
        else:
            runtime["outdoorCrossed"] = False
        if not runtime.get("outdoorCrossed"):
            runtime.pop("approval", None)
        elif outdoor["mode"] == "ask":
            approval = runtime.get("approval")
            if not approval and desired["mode"] in {"heat", "heat_cool"}:
                approval = {"token": secrets.token_hex(16), "until": (now + timedelta(minutes=10)).isoformat(), "decision": "pending"}
                runtime["approval"] = approval
                self.store.patch_runtime(ident, runtime, "Asked the selected person whether to turn heat off.")
                prefix = "pixora_thermostat:" + approval["token"] + ":"
                try:
                    if z["notify"]["service"] not in self.ha.services:
                        raise ValueError("Notification destination unavailable.")
                    await self.send_notice(z, {"title": z["name"], "message": f"It's over {outdoor['limit']} degrees {z['unit']} outside. Should I turn the heat off?", "data": {"tag": "pixora-thermostat-" + ident, "actions": [{"action": prefix + "yes", "title": "Yes"}, {"action": prefix + "no", "title": "No"}]}})
                except (ValueError, asyncio.TimeoutError, OSError):
                    self.store.patch_runtime(ident, runtime, "Action notification could not be confirmed; no thermostat approval was assumed.", "warning")
            if approval and now >= datetime.fromisoformat(approval["until"]) and approval["decision"] == "pending":
                approval["decision"] = "expired"
        runtime["outdoor"] = bool(runtime.get("outdoorCrossed") and (outdoor["mode"] == "auto" or runtime.get("approval", {}).get("decision") == "yes"))
        if runtime.get("approval", {}).get("decision") == "pending":
            detail += " Outdoor heat-off notification is awaiting Yes/No."

        if runtime.get("window"):
            reason = "Window/door setback"
            detail = "Open: " + ", ".join(opened) if opened else "Waiting for the closed-contact return delay."
            if desired["mode"] == "heat":
                desired["heat"] = min(desired["heat"], z["setback"])
            elif desired["mode"] == "heat_cool":
                # Keep heating at its setback and stop cooling with an open window.
                desired = {"mode": "heat", "heat": min(desired["heat"], z["setback"])}
            elif desired["mode"] == "cool":
                desired = {"mode": "off"}
        if runtime.get("outdoor"):
            reason = "Outdoor heat lockout"
            detail = f"Outdoor temperature {outside:.1f} {z['unit']}; heat limit {outdoor['limit']} {z['unit']}."
            if desired["mode"] in {"heat", "heat_cool"}:
                # Do not turn cooling on as a side effect of a heat lockout.
                desired = {"mode": "off"}

        flags = {"window": bool(runtime.get("window")), "outdoor": bool(runtime.get("outdoor"))}
        period_name = row.get("name") or "Period at " + clock_time(row["time"])
        activity = ("Schedule “" + period_name + "”" if reason == "Schedule" else reason + " (scheduled period: “" + period_name + "”)") + " — " + target_text(desired, z["unit"])
        self.status[ident] = {"reason": reason, "detail": detail, "target": desired, "actual": actual, "outdoor": outside,
                              "open": opened, "openSince": timers.get("open").isoformat() if timers.get("open") else None,
                              "override": override, "schedule": {"name": row.get("name", "Period starting " + row["time"]), "time": row["time"], "target": target(row)}, "protection": flags, "nextPeriod": next_period(z["schedule"], now, self.ha.timezone).isoformat()}
        if not same(actual, desired):
            action, fields = service_for(desired, state, z["unit"], self.ha.unit, self.ha.services)
            # Write the claim before the network request. A crash/timeout is never replayed.
            runtime["pending"] = {"target": desired, "at": now.isoformat(), "context": activity}
            self.store.patch_runtime(ident, runtime, "Requested: " + activity + ". Waiting for thermostat confirmation.")
            try:
                await self.ha.call(action, fields)
            except (ValueError, asyncio.TimeoutError, OSError) as exc:
                runtime["blocked"] = "Thermostat command result is uncertain. Check the thermostat before resuming. No automatic retry."
                self.store.patch_runtime(ident, runtime, runtime["blocked"], "warning")
            return
        runtime["last"] = actual
        if runtime.get("activityContext") != activity:
            runtime["activityContext"] = activity
            self.store.patch_runtime(ident, runtime, "Following: " + activity + ". Thermostat already matches; no command needed.")
        # Notify once per observed protection transition, after the target is confirmed.
        notices = runtime.setdefault("notices", {})
        for flag, active in flags.items():
            open_signature = sorted(opened) if flag == "window" and active else []
            changed_openings = flag == "window" and active and bool(open_signature) and notices.get("openings", []) != open_signature
            if notices.get(flag, False) == active and not changed_openings:
                continue
            notices[flag] = active
            if flag == "window":
                notices["openings"] = open_signature
            setting = "off" if actual["mode"] == "off" else " / ".join(k.capitalize() + " " + str(v) + " degrees " + z["unit"] for k, v in actual.items() if k != "mode")
            text = (("Open: " + ", ".join(opened) + ". " if opened else "All monitored openings are now closed; waiting for the return delay. ") + "Door/window protection is active. Thermostat confirmed: " + setting + "." if flag == "window" else "Outdoor heat limit reached: heating is off.") if active else ("All monitored openings are closed. Following the active schedule or override." if flag == "window" else "Outdoor heat limit cleared. Following the active schedule or override.")
            # Consume and persist door/window changes even while off, so they
            # cannot queue up and replay after a restart or later schedule.
            # The outdoor heat-off confirmation is a separate action result.
            if flag == "window" and actual["mode"] == "off":
                self.store.patch_runtime(ident, runtime, text + " Phone notification suppressed because the thermostat is off.")
                continue
            # Durable claim also prevents notification replay after a crash.
            self.store.patch_runtime(ident, runtime, text)
            service = z["notify"]["service"]
            if service and z.get("alerts", {}).get("setback" if active else "restore", True):
                try:
                    if service not in self.ha.services:
                        raise ValueError("Notification destination is unavailable.")
                    await self.send_notice(z, {"title": "Pixora Thermostat Controller", "message": z["name"] + ": " + text})
                except (ValueError, asyncio.TimeoutError, OSError):
                    self.store.patch_runtime(ident, runtime, "Notification delivery could not be confirmed; it was not retried.", "warning")
        if runtime != self.store.data["runtime"].get(ident, {}):
            self.store.patch_runtime(ident, runtime)
