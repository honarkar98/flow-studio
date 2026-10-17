"""Loopback-only web API and static UI for the generic flow studio."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, quote, quote_plus, urlsplit
from urllib.request import urlopen
from uuid import uuid4

from .presets import install_clm_v2_preset
from .runner import Runner
from .schema import MAX_SCHEMA_BYTES
from .store import _secret_leaves
from .transport import UrllibTransport


WEB = Path(__file__).resolve().parent.parent / "web"
MASK = "••••••"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def _mask(value, secrets):
    if isinstance(value, dict):
        return {key: _mask(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [_mask(item, secrets) for item in value]
    if isinstance(value, (str, int, float)) and value in secrets:
        return MASK
    if isinstance(value, str):
        forms = set()
        for secret in secrets:
            if isinstance(secret, str) and secret:
                forms.update((secret, quote(secret, safe=""), quote_plus(secret, safe="")))
        for form in sorted(forms, key=len, reverse=True):
            value = value.replace(form, MASK)
    return value


def _secrets(store, project_id):
    secrets = store.get_secret_values(project_id)
    for entry in store.get_variables(project_id).values():
        if entry["sensitive"]:
            secrets.extend(_secret_leaves(entry["value"]))
    return secrets


def _run_view(store, run, reveal=False):
    if reveal:
        return run
    secrets = _secrets(store, run["project_id"])
    return {**run, "error": _mask(run.get("error"), secrets),
            "graph_state": _mask(run.get("graph_state", {}), secrets)}


def create_server(host, port, store, transport=None):
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("برنامه فقط روی رایانهٔ محلی اجرا می‌شود.")
    transport = transport or UrllibTransport()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # URLs and payloads can contain credentials.

        def _json(self, status, value):
            raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _read_json(self):
            size = int(self.headers.get("Content-Length", "0"))
            if size > MAX_SCHEMA_BYTES + 1024 * 1024:
                raise ValueError("درخواست بیش از حد بزرگ است.")
            raw = self.rfile.read(size)
            try:
                body = json.loads(raw or b"{}")
            except json.JSONDecodeError as exc:
                raise ValueError("JSON درخواست معتبر نیست.") from exc
            if not isinstance(body, dict):
                raise ValueError("بدنهٔ درخواست باید شیء JSON باشد.")
            return body

        def _upload(self):
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= MAX_UPLOAD_BYTES:
                raise ValueError("فایل باید بین ۱ بایت و ۲۰ مگابایت باشد.")
            name = Path(self.headers.get("X-Filename", "upload.bin")).name
            suffix = Path(name).suffix
            if len(suffix) > 12 or not suffix[1:].isalnum():
                suffix = ".bin"
            directory = store.path.parent / "uploads"
            directory.mkdir(mode=0o700, exist_ok=True)
            target = directory / f"{uuid4().hex}{suffix}"
            descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                with os.fdopen(descriptor, "wb") as file:
                    remaining = size
                    while remaining:
                        chunk = self.rfile.read(min(65536, remaining))
                        if not chunk:
                            raise ValueError("فایل ناقص دریافت شد.")
                        file.write(chunk)
                        remaining -= len(chunk)
            except Exception:
                target.unlink(missing_ok=True)
                raise
            return {"name": name, "path": str(target.resolve()), "size": size}

        def _serve_static(self, path):
            name = {"/": "index.html", "/app.js": "app.js", "/diagram.js": "diagram.js",
                    "/style.css": "style.css"}.get(path)
            if not name:
                self.send_error(404)
                return
            file = WEB / name
            raw = file.read_bytes()
            types = {"html": "text/html", "js": "text/javascript", "css": "text/css"}
            self.send_response(200)
            self.send_header("Content-Type", types[file.suffix[1:]] + "; charset=utf-8")
            self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'; script-src 'self'; style-src 'self'")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _route(self, method):
            host_header = self.headers.get("Host", "").split(":")[0].strip("[]")
            if host_header not in ("127.0.0.1", "localhost", "::1"):
                return self._json(403, {"error": "میزبان مجاز نیست."})
            origin = self.headers.get("Origin")
            if origin and not origin.startswith(("http://127.0.0.1:", "http://localhost:")):
                return self._json(403, {"error": "مبدأ مجاز نیست."})
            parsed = urlsplit(self.path)
            if not parsed.path.startswith("/api/"):
                return self._serve_static(parsed.path) if method == "GET" else self._json(404, {"error": "یافت نشد."})
            parts = parsed.path.strip("/").split("/")
            query = parse_qs(parsed.query)
            if parts == ["api", "uploads"] and method == "POST":
                return self._json(201, self._upload())
            body = self._read_json() if method in ("POST", "PUT", "PATCH") else {}
            runner = Runner(store, transport)
            if parts == ["api", "health"] and method == "GET":
                return self._json(200, {"ok": True})
            if parts == ["api", "projects"]:
                if method == "GET":
                    return self._json(200, store.list_projects())
                if method == "POST":
                    return self._json(201, store.create_project(body.get("name"), body.get("base_url")))
            if len(parts) >= 3 and parts[:2] == ["api", "projects"]:
                project_id = parts[2]
                if len(parts) == 3:
                    if method == "GET":
                        return self._json(200, store.get_project(project_id))
                    if method in ("PUT", "PATCH"):
                        return self._json(200, store.save_project(project_id, body))
                if len(parts) == 4:
                    resource = parts[3]
                    if resource == "schema" and method == "POST":
                        return self._json(200, store.import_schema(project_id, body.get("text")))
                    if resource == "schema-url" and method == "POST":
                        url = body.get("url", "")
                        if not url.startswith(("http://", "https://")):
                            raise ValueError("URL schema معتبر نیست.")
                        with urlopen(url, timeout=20) as response:
                            raw = response.read(MAX_SCHEMA_BYTES + 1)
                        if len(raw) > MAX_SCHEMA_BYTES:
                            raise ValueError("schema بیش از ۱۰ مگابایت است.")
                        return self._json(200, store.import_schema(project_id, raw.decode("utf-8")))
                    if resource == "operations" and method == "GET":
                        return self._json(200, store.list_operations(project_id))
                    if resource == "flows":
                        if method == "GET":
                            return self._json(200, store.list_flows(project_id))
                        if method == "POST":
                            return self._json(201, store.save_flow(project_id, body))
                    if resource == "variables":
                        if method == "GET":
                            values = store.get_variables(project_id)
                            if query.get("reveal") != ["1"]:
                                values = {name: {**entry, "value": MASK if entry["sensitive"] else entry["value"]}
                                          for name, entry in values.items()}
                            return self._json(200, values)
                        if method == "POST":
                            store.set_variable(project_id, body.get("name"), body.get("value"),
                                               body.get("sensitive", False))
                            return self._json(200, {"ok": True})
                    if resource == "runs" and method == "GET":
                        runs = store.list_runs(project_id)
                        return self._json(200, [_run_view(store, run, query.get("reveal") == ["1"])
                                                for run in runs])
                if len(parts) == 5 and parts[3] == "variables" and method == "DELETE":
                    store.delete_variable(project_id, parts[4])
                    return self._json(200, {"ok": True})
                if parts[3:] == ["preset", "clm-v2"] and method == "POST":
                    return self._json(201, {"flow_id": install_clm_v2_preset(store, project_id)})
            if len(parts) >= 3 and parts[:2] == ["api", "flows"]:
                flow_id = parts[2]
                if len(parts) == 3:
                    if method == "GET":
                        return self._json(200, store.get_flow(flow_id))
                    if method in ("PUT", "PATCH"):
                        flow = store.get_flow(flow_id)
                        return self._json(200, store.save_flow(flow["project_id"], {**body, "id": flow_id}))
                    if method == "DELETE":
                        store.delete_flow(flow_id)
                        return self._json(200, {"ok": True})
                if len(parts) == 4 and parts[3] == "preview" and method == "GET":
                    preview = runner.preview(flow_id, int(query.get("step", [0])[0]))
                    if query.get("reveal") != ["1"]:
                        project_id = store.get_flow(flow_id)["project_id"]
                        preview = _mask(preview, _secrets(store, project_id))
                    return self._json(200, preview)
                if len(parts) == 4 and parts[3] == "runs" and method == "POST":
                    run_id = runner.start(flow_id, int(body.get("start_index", 0)),
                                          bool(body.get("acknowledge_post", False)))
                    return self._json(201, _run_view(store, store.get_run(run_id)))
            if len(parts) >= 3 and parts[:2] == ["api", "runs"]:
                run_id = parts[2]
                if len(parts) == 3 and method == "GET":
                    return self._json(200, _run_view(store, store.get_run(run_id), query.get("reveal") == ["1"]))
                if len(parts) == 4:
                    if parts[3] == "advance" and method == "POST":
                        run = runner.advance(run_id, body.get("manual_values"),
                                             bool(body.get("acknowledge_post", False)))
                        return self._json(200, _run_view(store, run))
                    if parts[3] == "exchanges" and method == "GET":
                        exchanges = store.list_exchanges(run_id)
                        if query.get("reveal") != ["1"]:
                            secrets = _secrets(store, store.get_run(run_id)["project_id"])
                            fields = ("url", "request_headers", "request_body", "response_headers",
                                      "response_body", "error")
                            exchanges = [{**exchange, **{field: _mask(exchange[field], secrets)
                                                         for field in fields}} for exchange in exchanges]
                        return self._json(200, exchanges)
            return self._json(404, {"error": "مسیر API یافت نشد."})

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

        def do_PUT(self):
            self._handle("PUT")

        def do_DELETE(self):
            self._handle("DELETE")

        def _handle(self, method):
            try:
                self._route(method)
            except KeyError as exc:
                self._json(404, {"error": str(exc)})
            except (ValueError, TypeError, IndexError, UnicodeDecodeError) as exc:
                self._json(400, {"error": str(exc)})
            except Exception:
                self._json(500, {"error": "خطای داخلی سرور."})

    return ThreadingHTTPServer((host, port), Handler)
