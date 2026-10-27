"""Bounded SQLite event journal, accessed off the asyncio event loop."""
import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from model import ENTITY, validate_settings, valid_exclusion, target_exclusion, activity_exclusions

DEFAULTS = {"days": 7, "limit": 20000, "excluded": []}


class Store:
    def __init__(self, root):
        Path(root).mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(Path(root) / "insight.sqlite"), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=NORMAL;
            PRAGMA max_page_count=16384;
            PRAGMA journal_size_limit=1048576;
            PRAGMA wal_autocheckpoint=256;
            CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, kind TEXT NOT NULL,
                title TEXT NOT NULL, name TEXT NOT NULL, context TEXT NOT NULL,
                parent TEXT NOT NULL, user INTEGER NOT NULL, details TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS targets (event INTEGER REFERENCES events(id) ON DELETE CASCADE, entity TEXT NOT NULL, PRIMARY KEY(event,entity));
            CREATE INDEX IF NOT EXISTS target_entity ON targets(entity,event);
            CREATE INDEX IF NOT EXISTS event_time ON events(at);
            CREATE INDEX IF NOT EXISTS event_context ON events(context);
            PRAGMA foreign_keys=ON;
        """)
        self.db.execute("INSERT OR IGNORE INTO settings VALUES(1,?)", (json.dumps(DEFAULTS),))
        self.db.commit()
        self.settings = validate_settings(json.loads(self.db.execute("SELECT value FROM settings WHERE id=1").fetchone()[0]))
        self.prune()

    def close(self):
        with self.lock:
            self.db.close()

    def prune(self):
        with self.lock, self.db:
            cutoff = (datetime.now(timezone.utc)-timedelta(days=self.settings["days"])).isoformat()
            self.db.execute("DELETE FROM events WHERE at < ?", (cutoff,))
            self.db.execute("DELETE FROM events WHERE id IN (SELECT id FROM events ORDER BY id DESC LIMIT -1 OFFSET ?)", (self.settings["limit"],))

    def save_settings(self, incoming):
        incoming = validate_settings(incoming)
        with self.lock, self.db:
            self.db.execute("UPDATE settings SET value=? WHERE id=1", (json.dumps(incoming),))
        self.settings = incoming
        self.prune()
        return incoming

    def make_room(self):
        with self.lock, self.db:
            self.db.execute("DELETE FROM events WHERE id IN (SELECT id FROM events ORDER BY id LIMIT 1000)")
        self.prune()

    def exclude(self, entity, restore=False):
        if not valid_exclusion(entity):
            raise ValueError("Choose a valid entity.")
        # Merge under the same lock as other settings writes; never replace
        # newer retention settings or another simultaneous exclusion.
        with self.lock:
            values = set(self.settings["excluded"])
            values.discard(entity) if restore else values.add(entity)
            incoming = {**self.settings, "excluded": sorted(values)}
            return self.save_settings(incoming)

    def append(self, rows):
        with self.lock, self.db:
            excluded = set(self.settings["excluded"])
            contains = [key[len("contains:"):] for key in excluded if key.startswith("contains:")]
            for row in rows:
                if any(fragment in entity for fragment in contains for entity in row["entities"]) or any(option["key"] in excluded for option in activity_exclusions(row)) or set(row["entities"]) & excluded or target_exclusion(row) in excluded or any("device:" + d in excluded for d in row["details"].get("deviceIds", [])):
                    continue
                payload = json.dumps(row["details"], ensure_ascii=False)
                if len(payload.encode("utf-8")) > 8192:
                    payload = json.dumps({"note": "Large detail omitted; event and context retained."})
                result = self.db.execute("INSERT INTO events(at,kind,title,name,context,parent,user,details) VALUES(?,?,?,?,?,?,?,?)",
                    (row["at"], row["kind"], row["title"], row["name"], row["context"], row["parent"], row["user"], payload))
                self.db.executemany("INSERT OR IGNORE INTO targets VALUES(?,?)", ((result.lastrowid, entity) for entity in row["entities"]))
        self.prune()

    def unpack(self, row):
        item = dict(row)
        item["details"] = json.loads(item["details"])
        item["user"] = bool(item["user"])
        item["entities"] = [r[0] for r in self.db.execute("SELECT entity FROM targets WHERE event=? ORDER BY entity", (item["id"],))]
        return item

    def query(self, entity="", search="", kind="", before=0):
        # Housekeeping notices are retained but do not clutter activity pages.
        housekeeping = (
            "An entity was excluded from future recording. Earlier records expire normally.",
            "An entity, device or display was excluded from future recording. Earlier records expire normally.",
            "Recording restored for an exclusion.",
            "Retention or exclusions changed. Exclusions affect future recording; retained earlier events expire normally.",
        )
        clauses = ["NOT (kind='coverage' AND title IN (?,?,?,?))"]
        args = list(housekeeping)
        if entity:
            clauses.append("id IN (SELECT event FROM targets WHERE entity=?)"); args.append(entity)
        if search:
            clauses.append("(instr(lower(title),lower(?))>0 OR instr(lower(details),lower(?))>0 OR id IN (SELECT event FROM targets WHERE instr(lower(entity),lower(?))>0))"); args.extend((search, search, search))
        if kind:
            clauses.append("kind=?"); args.append(kind)
        if before:
            clauses.append("id<?"); args.append(before)
        sql = "SELECT * FROM events" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY id DESC LIMIT 51"
        with self.lock:
            rows = [self.unpack(row) for row in self.db.execute(sql, args)]
        return {"events": rows[:50], "next": rows[49]["id"] if len(rows) > 50 else None}

    def stats(self):
        with self.lock:
            count, first, last = self.db.execute("SELECT count(*),min(at),max(at) FROM events").fetchone()
            size = self.db.execute("PRAGMA page_count").fetchone()[0] * self.db.execute("PRAGMA page_size").fetchone()[0]
            return {"count": count, "first": first, "last": last, "databaseBytes": size, "settings": self.settings}

    def explain(self, ident):
        with self.lock:
            row = self.db.execute("SELECT * FROM events WHERE id=?", (ident,)).fetchone()
            if not row:
                return None
            item = self.unpack(row)
            context = item["context"]
            contexts, evidence, seen = [context, item["parent"]], [], {item["id"]}
            visited = set()
            # Strict HA context links only; temporal proximity never establishes cause.
            for _ in range(8):
                keys = [key for key in contexts if key and key not in visited]
                if not keys:
                    break
                contexts = []
                for key in keys[:16]:
                    visited.add(key)
                    matches = self.db.execute("SELECT * FROM events WHERE context=? ORDER BY id DESC LIMIT 40", (key,))
                    for match in matches:
                        related = self.unpack(match)
                        if related["id"] in seen:
                            continue
                        seen.add(related["id"])
                        indirect = bool(related["details"].get("operation")) and (not related["entities"] or related["details"].get("operation") == "scene.turn_on")
                        reported_origin = (related["kind"] == "pixora_insight" and related["details"].get("actionContext") == key and (bool(set(item["entities"]) & set(related["entities"])) or indirect or item["kind"] == "call_service" and related["details"].get("operation") == item["details"].get("service")))
                        if related["kind"] == "pixora_insight" and not reported_origin:
                            continue
                        if related["at"] > item["at"] and not reported_origin:
                            continue
                        # Same-context state reports on other entities are siblings,
                        # never evidence that one device caused another.
                        if related["kind"] == "state_changed" and key == context:
                            continue
                        if related["kind"] == "call_service" and not set(item["entities"]) & set(related["entities"]):
                            continue
                        evidence.append(related)
                        if related["parent"]:
                            contexts.append(related["parent"])
                        if len(evidence) >= 16:
                            break
                    if len(evidence) >= 16:
                        break
                if len(evidence) >= 16:
                    break
            if item["kind"] == "call_service":
                answer = "Home Assistant recorded this command request. A request alone does not confirm the device acted."
                origins = [e for e in evidence if e["kind"] == "pixora_insight"]
                if len(origins) == 1:answer = origins[0]["details"]["source"] + " reports: " + origins[0]["details"]["reason"] + " A request alone does not confirm the device acted."
            elif item["kind"] == "state_changed":
                commands = [e for e in evidence if e["kind"] == "call_service"]
                runs = [e for e in evidence if e["kind"] in {"automation_triggered", "script_started"}]
                origins = [e for e in evidence if e["kind"] == "pixora_insight"]
                if len(origins) == 1:
                    answer = origins[0]["details"]["source"] + " reports: " + origins[0]["details"]["reason"]
                elif len(origins) > 1:
                    answer = "Several app-reported origins share this device action context. Inspect the linked evidence; the exact origin is ambiguous."
                elif len(commands) == 1:
                    action = commands[0]["details"]["service"].split(".", 1)[-1].replace("_", " ")
                    source = "“" + runs[0]["title"].split(": ", 1)[-1] + "” and its " if runs else "a "
                    answer = "Home Assistant links this reported change to " + source + "“" + action + "” request for this device."
                elif commands:
                    answer = "Several requests for this entity share the HA context. The specific initiating command is ambiguous; inspect the linked evidence."
                elif runs:
                    answer = "HA linked this reported change to " + runs[0]["title"] + ". The exact action or condition is not available here."
                elif item["user"]:
                    answer = "HA attached a user-associated context to this change, but the initiating command was not recorded."
                else:
                    answer = "The entity reported a change, but its cause is unknown in the retained records."
            elif item["kind"] == "pixora_insight":
                answer = item["details"]["source"] + " reported: " + item["details"]["reason"]
            else:
                answer = "HA recorded this automation or script starting. This does not prove every action completed."
            return {"event": item, "answer": answer, "evidence": sorted(evidence, key=lambda e: e["id"]),
                    "note": "Only retained HA context links are shown. Missing events, reconnect gaps and integrations that omit context limit explanations. App-reported decisions are identified as reports, not independently verified causes."}
