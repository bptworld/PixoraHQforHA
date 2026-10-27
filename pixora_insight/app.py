"""Ingress-only, read-only home explanations. No device-command endpoints."""
import asyncio
import json
import os
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit
from aiohttp import ClientSession, web
from collector import Collector, system_event
from model import ENTITY, EVENTS
from store import Store

VERSION = "0.1.3"
ROOT = Path(__file__).parent


def make_app(root=Path("/data"), test_collector=None):
    @web.middleware
    async def protect(request, handler):
        if request.remote != "172.30.32.2":
            raise web.HTTPForbidden(text="Open Pixora Insight through Home Assistant.")
        if request.method != "GET":
            origin = request.headers.get("Origin")
            host = request.headers.get("X-Forwarded-Host", request.host).split(",")[0].strip()
            if request.headers.get("X-Pixora-Request") != "1" or origin and urlsplit(origin).netloc != host:
                raise web.HTTPForbidden(text="Use the Home Assistant app page.")
        try:
            response = await handler(request)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            response = web.json_response({"error": "Check the selected settings or filters."}, status=422)
        except (sqlite3.Error, OSError):
            response = web.json_response({"error": "Local history storage is unavailable. Check the app log and available hub storage."}, status=503)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'"
        return response

    app = web.Application(middlewares=[protect], client_max_size=64*1024)
    store = Store(root)
    app["store"] = store
    if test_collector:
        app["collector"] = test_collector

    async def status(request):
        collector = app["collector"]
        stats = await asyncio.to_thread(store.stats)
        return web.json_response({**stats, "version": VERSION, "connected": collector.connected, "notice": collector.notice,
            "storageError": collector.storage_error, "dropped": collector.dropped, "queued": collector.queue.qsize(),
            "lastReceived": collector.last_received, "timezone": collector.timezone, "registryReady": collector.registry_ready,
            "entities": sorted(collector.catalog.entities.values(), key=lambda e: e["name"].casefold())})

    async def events(request):
        entity, search, kind = request.query.get("entity", ""), request.query.get("search", ""), request.query.get("kind", "")
        if entity and not ENTITY.fullmatch(entity) or len(search) > 100 or kind and kind not in {*EVENTS, "coverage"}:
            raise ValueError("Invalid filter")
        before = int(request.query.get("before", "0"))
        if before < 0:
            raise ValueError("Invalid cursor")
        return web.json_response(await asyncio.to_thread(store.query, entity, search, kind, before))

    async def explain(request):
        result = await asyncio.to_thread(store.explain, int(request.match_info["id"]))
        if not result:
            raise web.HTTPNotFound(text="This event has expired or was not recorded.")
        catalog = app["collector"].catalog
        item = result["event"]
        devices = set(item["details"].get("deviceIds", []))
        devices.update(catalog.registry.get(e, {}).get("device_id") for e in item["entities"])
        result["devices"] = sorted([{"id": d, "name": catalog.devices.get(d, {}).get("name") or d} for d in devices if d], key=lambda d: d["name"].casefold())
        return web.json_response(result)

    async def settings(request):
        body = await request.json()
        result = await asyncio.to_thread(store.save_settings, body)
        app["collector"].enqueue(system_event("Retention or exclusions changed. Exclusions affect future recording; retained earlier events expire normally."))
        return web.json_response({"settings": result})

    async def exclude(request):
        body = await request.json()
        if not isinstance(body, dict) or set(body) not in ({"entity"}, {"entity", "restore"}) or type(body.get("restore", False)) is not bool:
            raise ValueError("Choose one entity to exclude.")
        result = await asyncio.to_thread(store.exclude, body["entity"], body.get("restore", False))
        app["collector"].enqueue(system_event("Recording restored for an exclusion." if body.get("restore") else "An entity, device or display was excluded from future recording. Earlier records expire normally."))
        return web.json_response({"settings": result})

    async def static(request):
        name = request.match_info.get("name") or "index.html"
        if name not in {"index.html", "ui.js", "style.css", "icon.svg"}:
            raise web.HTTPNotFound()
        return web.FileResponse(ROOT / name)

    async def lifecycle(application):
        async with ClientSession() as session:
            collector = test_collector or Collector(session, os.environ.get("SUPERVISOR_TOKEN", ""), store)
            application["collector"] = collector
            collector.enqueue(system_event("Pixora Insight started. No old events were inferred or replayed."))
            tasks = [asyncio.create_task(collector.writer())]
            if not test_collector:
                tasks.append(asyncio.create_task(collector.listen()))
            try:
                yield
            finally:
                # Stop intake first, then let the writer commit its current
                # batch and drain. Never replay a possibly committed batch.
                for task in tasks[1:]:
                    task.cancel()
                await asyncio.gather(*tasks[1:], return_exceptions=True)
                collector.enqueue(system_event("Recording paused: Pixora Insight is stopping."))
                collector.stopping = True
                try:
                    await asyncio.wait_for(tasks[0], timeout=15)
                except asyncio.TimeoutError:
                    pass  # Next startup explicitly marks the coverage boundary.
                finally:
                    store.close()

    app.cleanup_ctx.append(lifecycle)
    app.router.add_get("/api/status", status)
    app.router.add_get("/api/events", events)
    app.router.add_get("/api/explain/{id}", explain)
    app.router.add_post("/api/settings", settings)
    app.router.add_post("/api/exclude", exclude)
    app.router.add_get("/", static)
    app.router.add_get("/{name}", static)
    return app


if __name__ == "__main__":
    web.run_app(make_app(), host="0.0.0.0", port=4194, print=None, access_log=None)
