"""Administrator-only HA ingress UI and local controller lifecycle."""
import asyncio
import copy
import json
import os
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit
from aiohttp import ClientSession, web
from engine import Store, Engine
from ha import HomeAssistant
from policy import validate, target, next_period, service_for, observed, number

VERSION = "0.1.0"
ROOT = Path(__file__).parent


def make_app(root=Path("/data"), test_ha=None):
    @web.middleware
    async def protect(request, handler):
        if request.remote != "172.30.32.2":
            raise web.HTTPForbidden(text="Open this app through Home Assistant.")
        if request.method != "GET":
            origin = request.headers.get("Origin")
            host = request.headers.get("X-Forwarded-Host", request.host).split(",")[0].strip()
            if request.headers.get("X-Pixora-Request") != "1" or origin and urlsplit(origin).netloc != host:
                raise web.HTTPForbidden(text="Use the Home Assistant app page.")
        try:
            response = await handler(request)
        except (ValueError, TypeError, KeyError) as exc:
            response = web.json_response({"error": str(exc)[:240]}, status=422)
        except OSError:
            response = web.json_response({"error": "Local storage is unavailable. No settings were changed."}, status=503)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'"
        return response

    app = web.Application(middlewares=[protect], client_max_size=128 * 1024)
    store = Store(root)
    validate({"zones": store.data["zones"]})
    app["store"] = store

    async def status(request):
        ha, engine = app["ha"], app["engine"]
        runtime = copy.deepcopy(store.data["runtime"])
        for item in runtime.values():
            if item.get("approval"):
                item["approval"].pop("token", None)
        entities = [{"id": s["entity_id"], "name": s.get("attributes", {}).get("friendly_name") or s["entity_id"],
                     "state": s.get("state"), "attributes": s.get("attributes", {})} for s in ha.states.values()]
        entities.sort(key=lambda s: s["name"].casefold())
        return web.json_response({"version": VERSION, "connected": ha.connected, "notice": ha.notice, "timezone": ha.timezone,
            "unit": ha.unit, "revision": store.data["revision"], "zones": store.data["zones"], "runtime": runtime,
            "status": engine.status, "events": store.data["events"][-60:][::-1], "entities": entities,
            "destinations": sorted(s for s in ha.services if s.startswith("notify.") and s != "notify.send_message")})

    async def settings(request):
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("Use a settings object.")
        engine, ha = app["engine"], app["ha"]
        async with engine.lock:
            if type(body.get("revision")) is not int or body.get("revision") != store.data["revision"]:
                return web.json_response({"error": "Settings changed in another window. Reload before saving."}, status=409)
            value = validate({"zones": body.get("zones")})
            old = {z["id"]: z for z in store.data["zones"]}
            # Validate live capabilities before allowing an enabled configuration.
            if any(z["enabled"] for z in value["zones"]) and not ha.connected:
                raise ValueError("Wait for Home Assistant to reconnect before enabling a controller.")
            for z in value["zones"]:
                if not z["enabled"]:
                    continue
                state = ha.states.get(z["entity"])
                if not state:
                    raise ValueError("Choose an available thermostat.")
                for row in z["schedule"]:
                    service_for(target(row), state, z["unit"], ha.unit, ha.services)
                for ident in z["openings"]:
                    contact = ha.states.get(ident)
                    if not contact or contact.get("attributes", {}).get("device_class") not in {"door", "window", "opening", "garage_door"}:
                        raise ValueError("Choose door/window contact sensors for opening protection.")
                if z["openings"]:
                    service_for({"mode": "heat", "heat": z["setback"]}, state, z["unit"], ha.unit, ha.services)
                if z["outdoor"]["enabled"]:
                    from policy import temperature
                    temperature(ha.states.get(z["outdoor"]["entity"]), z["unit"])
                    service_for({"mode": "off"}, state, z["unit"], ha.unit, ha.services)
                if z["notify"]["service"] and z["notify"]["service"] not in ha.services:
                    raise ValueError("Choose an available notification destination.")
                prior = old.get(z["id"])
                if prior and prior["entity"] != z["entity"] and store.data["runtime"].get(z["id"], {}).get("pending"):
                    raise ValueError("Check the pending thermostat command before changing its binding.")
            saved = copy.deepcopy(store.data)
            saved.update(zones=value["zones"], revision=saved["revision"] + 1)
            saved["runtime"] = {z["id"]: saved["runtime"].get(z["id"], {}) if old.get(z["id"], {}).get("entity") == z["entity"] else {} for z in value["zones"]}
            for z in value["zones"]:
                if old.get(z["id"], {}).get("outdoor") != z["outdoor"] or old.get(z["id"], {}).get("notify") != z["notify"] or old.get(z["id"], {}).get("enabled") != z["enabled"]:
                    saved["runtime"][z["id"]].pop("approval", None)
            store.write(saved)
            # Preserve observations for unchanged protection settings, including
            # when a different controller or just its display name is edited.
            for ident in list(engine.timers):
                current = next((z for z in value["zones"] if z["id"] == ident), None)
                prior = old.get(ident)
                keys = ("entity", "enabled", "openings", "openMinutes", "closeMinutes")
                if not current or not prior or any(current[k] != prior[k] for k in keys):
                    engine.timers.pop(ident, None)
        await engine.tick()
        return web.json_response({"ok": True})

    async def action(request):
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("Use an action object.")
        engine, ha = app["engine"], app["ha"]
        async with engine.lock:
            z = next((z for z in store.data["zones"] if z["id"] == body.get("id")), None)
            if not z:
                raise ValueError("Controller not found.")
            runtime = copy.deepcopy(store.data["runtime"].get(z["id"], {}))
            kind = body.get("action")
            if kind == "override":
                if not ha.connected or not z["enabled"]:
                    raise ValueError("Enable this controller and wait for Home Assistant before setting an override.")
                wanted = target(body.get("target", {}))
                service_for(wanted, ha.states[z["entity"]], z["unit"], ha.unit, ha.services)
                until = next_period(z["schedule"], engine.now(), ha.timezone) if body.get("untilNext") is True else engine.now() + timedelta(minutes=number(body.get("minutes"), 5, 1440, "Override minutes"))
                if not until:
                    raise ValueError("No next schedule period is available.")
                runtime["override"] = {"target": wanted, "until": until.isoformat(), "source": "Controller override"}
            elif kind == "resume":
                runtime["override"] = None
            elif kind == "checked":
                if not ha.connected:
                    raise ValueError("Wait for fresh Home Assistant state before resuming.")
                # This is an explicit user decision after inspecting the physical thermostat.
                runtime.update(pending=None, blocked="", last=observed(ha.states[z["entity"]]))
            else:
                raise ValueError("Choose a supported controller action.")
            store.patch_runtime(z["id"], runtime, {"override": "Temporary override saved.", "resume": "Schedule resumed; protection remains active.", "checked": "User checked the thermostat and resumed control."}[kind])
        await engine.tick()
        return web.json_response({"ok": True})

    async def static(request):
        name = request.match_info.get("name") or "index.html"
        if name not in {"index.html", "ui.js", "style.css", "icon.svg"}:
            raise web.HTTPNotFound()
        return web.FileResponse(ROOT / name)

    async def background():
        while True:
            await app["engine"].tick()
            await asyncio.sleep(5)

    async def lifecycle(application):
        async with ClientSession() as session:
            application["ha"] = test_ha or HomeAssistant(session, os.environ.get("SUPERVISOR_TOKEN", ""))
            application["engine"] = Engine(store, application["ha"])
            tasks = [asyncio.create_task(background())]
            if not test_ha:
                tasks.append(asyncio.create_task(application["ha"].listen()))
            try:
                yield
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

    app.cleanup_ctx.append(lifecycle)
    app.router.add_get("/api/status", status)
    app.router.add_post("/api/settings", settings)
    app.router.add_post("/api/action", action)
    app.router.add_get("/", static)
    app.router.add_get("/{name}", static)
    return app


if __name__ == "__main__":
    web.run_app(make_app(), host="0.0.0.0", port=4192, print=None, access_log=None)
