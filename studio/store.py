"""SQLite persistence for projects, catalogues, flows and variables."""

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from uuid import uuid4

from .expressions import valid_name
from .schema import parse


def _now():
    return datetime.now(timezone.utc).isoformat()


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _secret_leaves(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _secret_leaves(item)
    elif isinstance(value, list):
        for item in value:
            yield from _secret_leaves(item)
    elif isinstance(value, (str, int, float)) and value:
        yield value


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, base_url TEXT NOT NULL,
                    refresh_json TEXT, schema_version TEXT, schema_text TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS operations (
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    method TEXT NOT NULL, path TEXT NOT NULL, operation_id TEXT NOT NULL,
                    summary TEXT NOT NULL, details_json TEXT NOT NULL, missing INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (project_id, method, path)
                );
                CREATE TABLE IF NOT EXISTS flows (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    name TEXT NOT NULL, steps_json TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS variables (
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    name TEXT NOT NULL, value_json TEXT NOT NULL, sensitive INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL, PRIMARY KEY (project_id, name)
                );
                CREATE TABLE IF NOT EXISTS secret_values (
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    value_json TEXT NOT NULL, PRIMARY KEY (project_id, value_json)
                );
                CREATE TABLE IF NOT EXISTS sensitive_names (
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    name TEXT NOT NULL, PRIMARY KEY (project_id, name)
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, flow_id TEXT NOT NULL REFERENCES flows(id) ON DELETE CASCADE,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    steps_json TEXT NOT NULL, next_index INTEGER NOT NULL,
                    status TEXT NOT NULL, error TEXT, allow_post_repeat INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS exchanges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                    sequence INTEGER NOT NULL, step_index INTEGER NOT NULL,
                    step_name TEXT NOT NULL, method TEXT NOT NULL, url TEXT NOT NULL,
                    request_headers_json TEXT NOT NULL, request_body_json TEXT,
                    response_status INTEGER, response_headers_json TEXT NOT NULL,
                    response_body_json TEXT, duration_ms INTEGER NOT NULL,
                    error TEXT, created_at TEXT NOT NULL,
                    UNIQUE(run_id, sequence)
                );
            """)
            if "allow_post_repeat" not in {row[1] for row in db.execute("PRAGMA table_info(runs)")}:
                db.execute("ALTER TABLE runs ADD COLUMN allow_post_repeat INTEGER NOT NULL DEFAULT 0")
            if "graph_state_json" not in {row[1] for row in db.execute("PRAGMA table_info(runs)")}:
                db.execute("ALTER TABLE runs ADD COLUMN graph_state_json TEXT NOT NULL DEFAULT '{}'")
            self._ensure_step_ids(db)
        os.chmod(self.path, 0o600)

    def _ensure_step_ids(self, db):
        """Give older saved flows/runs stable step identities for safe resume."""
        flows = {}
        for row in db.execute("SELECT id,steps_json FROM flows"):
            steps = json.loads(row["steps_json"])
            changed = False
            for step in steps:
                if isinstance(step, dict) and not step.get("_id"):
                    step["_id"] = str(uuid4())
                    changed = True
            flows[row["id"]] = steps
            if changed:
                db.execute("UPDATE flows SET steps_json=? WHERE id=?", (_json(steps), row["id"]))
        for row in db.execute("SELECT id,flow_id,steps_json FROM runs"):
            steps = json.loads(row["steps_json"])
            changed = False
            current = flows.get(row["flow_id"], [])
            for index, step in enumerate(steps):
                if isinstance(step, dict) and not step.get("_id"):
                    step["_id"] = current[index]["_id"] if index < len(current) else str(uuid4())
                    changed = True
            if changed:
                db.execute("UPDATE runs SET steps_json=? WHERE id=?", (_json(steps), row["id"]))

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @contextmanager
    def run_lock(self, run_id):
        """Claim one run across threads and processes; OS releases on crash."""
        digest = hashlib.sha256(str(run_id).encode()).hexdigest()
        lock_path = self.path.parent / f".run-{digest}.lock"
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError("این اجرا هم‌اکنون در حال انجام است.") from exc
            try:
                yield
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

    def create_project(self, name, base_url):
        name = name.strip() if isinstance(name, str) else ""
        base_url = base_url.strip().rstrip("/") if isinstance(base_url, str) else ""
        if not name or not base_url.startswith(("http://", "https://")):
            raise ValueError("نام و URL پایهٔ معتبر لازم است.")
        project_id = str(uuid4())
        now = _now()
        with self._db() as db:
            db.execute("INSERT INTO projects (id,name,base_url,created_at,updated_at) VALUES (?,?,?,?,?)",
                       (project_id, name, base_url, now, now))
        return self.get_project(project_id)

    def _project(self, row):
        if row is None:
            raise KeyError("پروژه یافت نشد.")
        result = dict(row)
        result["refresh"] = json.loads(result.pop("refresh_json") or "null")
        result.pop("schema_text", None)
        return result

    def get_project(self, project_id):
        with self._db() as db:
            return self._project(db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone())

    def list_projects(self):
        with self._db() as db:
            return [self._project(row) for row in db.execute("SELECT * FROM projects ORDER BY created_at")]

    def save_project(self, project_id, changes):
        allowed = {"name", "base_url", "refresh"}
        if not changes or set(changes) - allowed:
            raise ValueError("فیلد پروژه معتبر نیست.")
        project = self.get_project(project_id)
        project.update(changes)
        name = project["name"].strip() if isinstance(project["name"], str) else ""
        base_url = project["base_url"].strip().rstrip("/") if isinstance(project["base_url"], str) else ""
        if not name or not base_url.startswith(("http://", "https://")):
            raise ValueError("نام و URL پایهٔ معتبر لازم است.")
        with self._db() as db:
            db.execute("UPDATE projects SET name=?,base_url=?,refresh_json=?,updated_at=? WHERE id=?",
                       (name, base_url, _json(project.get("refresh")), _now(), project_id))
        return self.get_project(project_id)

    def import_schema(self, project_id, text):
        version, incoming = parse(text)
        self.get_project(project_id)
        new_keys = {(op["method"], op["path"]) for op in incoming}
        diff = {"version": version, "added": [], "updated": [], "missing": []}
        with self._db() as db:
            old = {(r["method"], r["path"]): dict(r) for r in db.execute(
                "SELECT * FROM operations WHERE project_id=?", (project_id,))}
            for op in incoming:
                key = (op["method"], op["path"])
                label = f"{op['method']} {op['path']}"
                details = _json(op["details"])
                if key not in old:
                    diff["added"].append(label)
                elif old[key]["details_json"] != details or old[key]["missing"]:
                    diff["updated"].append(label)
                db.execute("""INSERT INTO operations
                    (project_id,method,path,operation_id,summary,details_json,missing)
                    VALUES (?,?,?,?,?,?,0)
                    ON CONFLICT(project_id,method,path) DO UPDATE SET
                    operation_id=excluded.operation_id,summary=excluded.summary,
                    details_json=excluded.details_json,missing=0""",
                    (project_id, op["method"], op["path"], op["operation_id"], op["summary"], details))
            for method, path in old.keys() - new_keys:
                diff["missing"].append(f"{method} {path}")
                db.execute("UPDATE operations SET missing=1 WHERE project_id=? AND method=? AND path=?",
                           (project_id, method, path))
            db.execute("UPDATE projects SET schema_version=?,schema_text=?,updated_at=? WHERE id=?",
                       (version, text, _now(), project_id))
        for field in ("added", "updated", "missing"):
            diff[field].sort()
        changed = set(diff["updated"] + diff["missing"])
        diff["affected_flows"] = []
        if changed:
            for flow in self.list_flows(project_id):
                affected = [(index, f"{step.get('method', 'GET').upper()} {step.get('path', '')}")
                            for index, step in enumerate(flow["steps"]) if step.get("kind", "http") == "http"]
                affected = [(index, label) for index, label in affected if label in changed]
                if affected:
                    diff["affected_flows"].append({
                        "flow_id": flow["id"], "flow_name": flow["name"],
                        "step_indexes": [index for index, _ in affected],
                        "operations": [label for _, label in affected],
                    })
        return diff

    def list_operations(self, project_id):
        with self._db() as db:
            rows = db.execute("SELECT * FROM operations WHERE project_id=? ORDER BY path,method",
                              (project_id,)).fetchall()
        return [{"method": r["method"], "path": r["path"], "operation_id": r["operation_id"],
                 "summary": r["summary"], "details": json.loads(r["details_json"]),
                 "missing": bool(r["missing"])} for r in rows]

    def _flow(self, row):
        if row is None:
            raise KeyError("فلو یافت نشد.")
        result = dict(row)
        result["steps"] = json.loads(result.pop("steps_json"))
        return result

    def save_flow(self, project_id, flow):
        self.get_project(project_id)
        name = str(flow.get("name") or "").strip()
        steps = flow.get("steps", [])
        if not name or not isinstance(steps, list) or any(not isinstance(step, dict) for step in steps):
            raise ValueError("نام فلو و فهرست گام‌ها لازم است.")
        flow_id = flow.get("id") or str(uuid4())
        now = _now()
        with self._db() as db:
            existing = db.execute("SELECT project_id,steps_json FROM flows WHERE id=?", (flow_id,)).fetchone()
            if existing and existing["project_id"] != project_id:
                raise ValueError("فلو به پروژهٔ دیگری تعلق دارد.")
            previous = json.loads(existing["steps_json"]) if existing else []
            steps = [dict(step) for step in steps]
            for index, step in enumerate(steps):
                if not step.get("_id"):
                    step["_id"] = previous[index].get("_id") if index < len(previous) else None
                if not step["_id"]:
                    step["_id"] = str(uuid4())
            if len({step["_id"] for step in steps}) != len(steps):
                raise ValueError("شناسهٔ گام‌ها تکراری است.")
            ids = {step["_id"] for step in steps}
            ports = {"http": {"next", "error"}, "manual": {"next"},
                     "condition": {"yes", "no"}, "foreach": {"body", "done"}}
            for step in steps:
                kind = step.get("kind", "http")
                if kind not in ports:
                    raise ValueError("نوع گام شناخته نشد.")
                routes = step.get("routes", {})
                if not isinstance(routes, dict) or set(routes) - ports[kind]:
                    raise ValueError("مسیر خروجی گام معتبر نیست.")
                if any(target is not None and target not in ids for target in routes.values()):
                    raise ValueError("هدف اتصال در فلو یافت نشد.")
                if kind == "foreach" and routes.get("body") == step["_id"]:
                    raise ValueError("خروجی بدنهٔ حلقه باید به گام دیگری وصل شود.")
            db.execute("""INSERT INTO flows (id,project_id,name,steps_json,created_at,updated_at)
                VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,steps_json=excluded.steps_json,updated_at=excluded.updated_at""",
                (flow_id, project_id, name, _json(steps), now, now))
        return self.get_flow(flow_id)

    def rebase_run(self, run_id):
        """Use latest flow edits at the same pending logical step."""
        with self._db() as db:
            row = db.execute("SELECT flow_id,steps_json,next_index,status,graph_state_json FROM runs WHERE id=?",
                             (run_id,)).fetchone()
            if row is None:
                raise KeyError("اجرا یافت نشد.")
            if row["status"] == "completed":
                return
            old_steps = json.loads(row["steps_json"])
            new_row = db.execute("SELECT steps_json FROM flows WHERE id=?", (row["flow_id"],)).fetchone()
            new_steps = json.loads(new_row["steps_json"])
            if old_steps == new_steps:
                return
            index = row["next_index"]
            if index < len(old_steps):
                pending_id = old_steps[index].get("_id")
                matches = [i for i, step in enumerate(new_steps) if step.get("_id") == pending_id]
                if not matches:
                    raise ValueError("گام در انتظار از فلو حذف شده است؛ اجرای تازه را از گام دلخواه آغاز کنید.")
                new_index = matches[0]
                trace = json.loads(row["graph_state_json"] or "{}").get("trace", [])
                done_before = [step.get("_id") for step in old_steps[:index]]
                done_now = [step.get("_id") for step in new_steps[:new_index]]
                if not trace and done_before != done_now:
                    raise ValueError("ترتیب گام‌های انجام‌شده تغییر کرده است؛ اجرای تازه را از گام دلخواه آغاز کنید.")
                if trace and any(step_id not in {step.get("_id") for step in new_steps} for step_id in trace):
                    raise ValueError("گام انجام‌شده از فلو حذف شده است؛ اجرای تازه بسازید.")
                index = new_index
            else:
                index = len(new_steps)
            db.execute("UPDATE runs SET steps_json=?,next_index=?,updated_at=? WHERE id=?",
                       (_json(new_steps), index, _now(), run_id))

    def get_flow(self, flow_id):
        with self._db() as db:
            return self._flow(db.execute("SELECT * FROM flows WHERE id=?", (flow_id,)).fetchone())

    def list_flows(self, project_id):
        with self._db() as db:
            return [self._flow(r) for r in db.execute(
                "SELECT * FROM flows WHERE project_id=? ORDER BY created_at", (project_id,))]

    def delete_flow(self, flow_id):
        self.get_flow(flow_id)
        with self._db() as db:
            db.execute("DELETE FROM flows WHERE id=?", (flow_id,))

    def set_variable(self, project_id, name, value, sensitive=False):
        self.get_project(project_id)
        name = name.strip() if isinstance(name, str) else ""
        if not valid_name(name):
            raise ValueError("نام متغیر باید حروف، عدد یا زیرخط داشته باشد.")
        with self._db() as db:
            declared = db.execute("SELECT 1 FROM sensitive_names WHERE project_id=? AND name=?",
                                  (project_id, name)).fetchone()
            sensitive = bool(sensitive or declared)
            if sensitive:
                for leaf in _secret_leaves(value):
                    db.execute("INSERT OR IGNORE INTO secret_values (project_id,value_json) VALUES (?,?)",
                               (project_id, _json(leaf)))
            db.execute("""INSERT INTO variables (project_id,name,value_json,sensitive,updated_at)
                VALUES (?,?,?,?,?) ON CONFLICT(project_id,name) DO UPDATE SET
                value_json=excluded.value_json,sensitive=excluded.sensitive,
                updated_at=excluded.updated_at""",
                (project_id, name, _json(value), int(bool(sensitive)), _now()))

    def declare_sensitive(self, project_id, name):
        self.get_project(project_id)
        if not valid_name(name):
            raise ValueError("نام متغیر معتبر نیست.")
        with self._db() as db:
            db.execute("INSERT OR IGNORE INTO sensitive_names (project_id,name) VALUES (?,?)",
                       (project_id, name))
            row = db.execute("SELECT value_json FROM variables WHERE project_id=? AND name=?",
                             (project_id, name)).fetchone()
            if row:
                db.execute("UPDATE variables SET sensitive=1 WHERE project_id=? AND name=?",
                           (project_id, name))
                value = json.loads(row["value_json"])
                for leaf in _secret_leaves(value):
                    db.execute("INSERT OR IGNORE INTO secret_values (project_id,value_json) VALUES (?,?)",
                               (project_id, _json(leaf)))

    def get_variables(self, project_id):
        with self._db() as db:
            rows = db.execute("SELECT * FROM variables WHERE project_id=? ORDER BY name", (project_id,))
            return {r["name"]: {"value": json.loads(r["value_json"]), "sensitive": bool(r["sensitive"]),
                                "updated_at": r["updated_at"]} for r in rows}

    def get_secret_values(self, project_id):
        with self._db() as db:
            return [json.loads(row[0]) for row in db.execute(
                "SELECT value_json FROM secret_values WHERE project_id=?", (project_id,))]

    def delete_variable(self, project_id, name):
        with self._db() as db:
            db.execute("DELETE FROM variables WHERE project_id=? AND name=?", (project_id, name))

    def create_run(self, flow_id, start_index=0, acknowledge_post=False):
        flow = self.get_flow(flow_id)
        if not 0 <= start_index <= len(flow["steps"]):
            raise ValueError("شمارهٔ گام معتبر نیست.")
        run_id = str(uuid4())
        now = _now()
        with self._db() as db:
            db.execute("""INSERT INTO runs
                (id,flow_id,project_id,steps_json,next_index,status,allow_post_repeat,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (run_id, flow_id, flow["project_id"], _json(flow["steps"]), start_index,
                 "ready", int(bool(acknowledge_post)), now, now))
        return run_id

    def get_run(self, run_id):
        with self._db() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError("اجرا یافت نشد.")
        result = dict(row)
        result["steps"] = json.loads(result.pop("steps_json"))
        result["graph_state"] = json.loads(result.pop("graph_state_json") or "{}")
        result["allow_post_repeat"] = bool(result["allow_post_repeat"])
        return result

    def list_runs(self, project_id):
        with self._db() as db:
            rows = db.execute("SELECT * FROM runs WHERE project_id=? ORDER BY created_at DESC",
                              (project_id,)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["steps"] = json.loads(item.pop("steps_json"))
            item["graph_state"] = json.loads(item.pop("graph_state_json") or "{}")
            item["allow_post_repeat"] = bool(item["allow_post_repeat"])
            result.append(item)
        return result

    def has_successful_post(self, flow_id, step_index, exclude_run_id=None):
        with self._db() as db:
            row = db.execute("""SELECT 1 FROM exchanges e JOIN runs r ON e.run_id=r.id
                WHERE r.flow_id=? AND e.step_index=? AND e.method='POST'
                AND e.response_status BETWEEN 200 AND 299 AND e.run_id!=? LIMIT 1""",
                (flow_id, step_index, exclude_run_id or "")).fetchone()
        return row is not None

    def update_run(self, run_id, status, next_index=None, error=None, values=None, graph_state=None):
        """Commit cursor and variable changes together for manual steps."""
        with self._db() as db:
            run = db.execute("SELECT project_id,next_index FROM runs WHERE id=?", (run_id,)).fetchone()
            if run is None:
                raise KeyError("اجرا یافت نشد.")
            if values:
                self._write_variables(db, run["project_id"], values)
            db.execute("UPDATE runs SET status=?,next_index=?,error=?,graph_state_json=COALESCE(?,graph_state_json),updated_at=? WHERE id=?",
                       (status, run["next_index"] if next_index is None else next_index,
                        error, _json(graph_state) if graph_state is not None else None, _now(), run_id))
        return self.get_run(run_id)

    def _write_variables(self, db, project_id, values):
        for name, item in values.items():
            if not valid_name(name):
                raise ValueError("نام متغیر خروجی معتبر نیست.")
            value, sensitive = item
            previous = db.execute("SELECT sensitive FROM variables WHERE project_id=? AND name=?",
                                  (project_id, name)).fetchone()
            declared = db.execute("SELECT 1 FROM sensitive_names WHERE project_id=? AND name=?",
                                  (project_id, name)).fetchone()
            sensitive = bool(sensitive) or bool(previous and previous["sensitive"]) or bool(declared)
            if sensitive:
                for leaf in _secret_leaves(value):
                    db.execute("INSERT OR IGNORE INTO secret_values (project_id,value_json) VALUES (?,?)",
                               (project_id, _json(leaf)))
            db.execute("""INSERT INTO variables (project_id,name,value_json,sensitive,updated_at)
                VALUES (?,?,?,?,?) ON CONFLICT(project_id,name) DO UPDATE SET
                value_json=excluded.value_json,sensitive=excluded.sensitive,
                updated_at=excluded.updated_at""",
                (project_id, name, _json(value), int(sensitive), _now()))

    def record_attempt(self, run_id, exchange, status, next_index=None, error=None, values=None, graph_state=None):
        """Append one HTTP attempt and checkpoint in one SQLite transaction."""
        with self._db() as db:
            run = db.execute("SELECT project_id,next_index FROM runs WHERE id=?", (run_id,)).fetchone()
            if run is None:
                raise KeyError("اجرا یافت نشد.")
            sequence = db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM exchanges WHERE run_id=?",
                                  (run_id,)).fetchone()[0]
            db.execute("""INSERT INTO exchanges
                (run_id,sequence,step_index,step_name,method,url,request_headers_json,
                 request_body_json,response_status,response_headers_json,response_body_json,
                 duration_ms,error,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run_id, sequence, exchange["step_index"], exchange["step_name"],
                 exchange["method"], exchange["url"], _json(exchange.get("request_headers") or {}),
                 _json(exchange.get("request_body")), exchange.get("response_status"),
                 _json(exchange.get("response_headers") or {}), _json(exchange.get("response_body")),
                 exchange.get("duration_ms", 0), exchange.get("error"), _now()))
            if values:
                self._write_variables(db, run["project_id"], values)
            db.execute("UPDATE runs SET status=?,next_index=?,error=?,graph_state_json=COALESCE(?,graph_state_json),updated_at=? WHERE id=?",
                       (status, run["next_index"] if next_index is None else next_index,
                        error, _json(graph_state) if graph_state is not None else None, _now(), run_id))
        return self.get_run(run_id)

    def list_exchanges(self, run_id):
        with self._db() as db:
            rows = db.execute("SELECT * FROM exchanges WHERE run_id=? ORDER BY sequence",
                              (run_id,)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            for field in ("request_headers", "request_body", "response_headers", "response_body"):
                item[field] = json.loads(item.pop(field + "_json") or "null")
            result.append(item)
        return result
