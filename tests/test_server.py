import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from studio.server import create_server
from studio.store import Store
from studio.transport import HTTPResult


class FakeTransport:
    def send(self, request):
        return HTTPResult(200, {}, {"token": "secret", "echo": request.body}, 1)


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "db.sqlite3")
        self.server = create_server("127.0.0.1", 0, self.store, FakeTransport())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def call(self, method, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        request = Request(self.base + path, data=data, method=method,
                          headers={"Content-Type": "application/json"})
        try:
            with urlopen(request) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def test_create_import_edit_preview_and_run_with_masked_timeline(self):
        status, project = self.call("POST", "/api/projects", {"name": "Demo", "base_url": self.base})
        self.assertEqual(status, 201)
        pid = project["id"]
        schema = '{"openapi":"3.0.3","paths":{"/echo":{"post":{"summary":"Echo"}}}}'
        self.assertEqual(self.call("POST", f"/api/projects/{pid}/schema", {"text": schema})[1]["added"],
                         ["POST /echo"])
        self.assertEqual(len(self.call("GET", f"/api/projects/{pid}/operations")[1]), 1)
        status, flow = self.call("POST", f"/api/projects/{pid}/flows", {"name": "Flow", "steps": [
            {"name": "Manual", "kind": "manual", "manual_variables": ["input"]},
            {"name": "Echo", "kind": "http", "method": "POST", "path": "/echo",
             "body": {"value": "{{input}}"},
             "captures": [{"name": "token", "path": "token", "sensitive": True}]},
        ]})
        self.assertEqual(status, 201)
        self.assertEqual(self.call("GET", f"/api/flows/{flow['id']}/preview?step=1")[0], 400)
        run = self.call("POST", f"/api/flows/{flow['id']}/runs", {})[1]
        self.assertEqual(self.call("POST", f"/api/runs/{run['id']}/advance", {})[1]["status"], "waiting")
        done = self.call("POST", f"/api/runs/{run['id']}/advance", {"manual_values": {"input": "hello"}})[1]
        self.assertEqual(done["status"], "completed")
        self.assertEqual(self.call("GET", f"/api/runs/{run['id']}/exchanges")[1][0]["response_body"]["token"],
                         "••••••")
        self.assertEqual(self.call("GET", f"/api/runs/{run['id']}/exchanges?reveal=1")[1][0]["url"],
                         self.base + "/echo")
        self.assertEqual(self.call("POST", f"/api/flows/{flow['id']}/runs", {})[0], 400)
        self.assertEqual(self.call("POST", f"/api/flows/{flow['id']}/runs",
                                   {"acknowledge_post": True})[0], 201)
        self.assertEqual(self.call("PUT", f"/api/flows/{flow['id']}",
                                   {"name": "Edited", "steps": flow["steps"]})[1]["name"], "Edited")

    def test_schema_reimport_does_not_erase_flow_or_variable(self):
        project = self.call("POST", "/api/projects", {"name": "Other", "base_url": self.base})[1]
        pid = project["id"]
        self.call("POST", f"/api/projects/{pid}/variables", {"name": "x", "value": 12})
        flow = self.call("POST", f"/api/projects/{pid}/flows", {"name": "A", "steps": []})[1]
        first = '{"swagger":"2.0","paths":{"/old":{"get":{}}}}'
        second = '{"swagger":"2.0","paths":{"/new":{"get":{}}}}'
        self.call("POST", f"/api/projects/{pid}/schema", {"text": first})
        diff = self.call("POST", f"/api/projects/{pid}/schema", {"text": second})[1]
        self.assertEqual(diff["missing"], ["GET /old"])
        self.assertEqual(self.call("GET", f"/api/flows/{flow['id']}")[0], 200)
        self.assertEqual(self.call("GET", f"/api/projects/{pid}/variables")[1]["x"]["value"], 12)

    def test_static_ui_and_clm_preset_are_available(self):
        with urlopen(self.base + "/") as response:
            self.assertIn("استودیوی فلو API", response.read().decode())
        with urlopen(self.base + "/diagram.js") as response:
            self.assertIn("DiagramEditor", response.read().decode())
        project = self.call("POST", "/api/projects", {"name": "CLM", "base_url": self.base})[1]
        status, result = self.call("POST", f"/api/projects/{project['id']}/preset/clm-v2", {})
        self.assertEqual(status, 201)
        self.assertEqual(len(self.call("GET", f"/api/flows/{result['flow_id']}")[1]["steps"]), 12)

    def test_old_sensitive_token_remains_masked_after_refresh_changes_variable(self):
        project = self.call("POST", "/api/projects", {"name": "Tokens", "base_url": self.base})[1]
        pid = project["id"]
        self.call("POST", f"/api/projects/{pid}/variables",
                  {"name": "access", "value": "old-token", "sensitive": True})
        flow = self.call("POST", f"/api/projects/{pid}/flows", {"name": "A", "steps": [
            {"kind": "http", "method": "GET", "path": "/test",
             "headers": {"Authorization": "Bearer {{access}}"}}]})[1]
        run = self.call("POST", f"/api/flows/{flow['id']}/runs", {})[1]
        self.call("POST", f"/api/runs/{run['id']}/advance", {})
        self.call("POST", f"/api/projects/{pid}/variables",
                  {"name": "access", "value": "new-token", "sensitive": True})
        masked = self.call("GET", f"/api/runs/{run['id']}/exchanges")[1][0]
        self.assertNotIn("old-token", pretty_json(masked))

    def test_preview_and_url_encoded_history_mask_sensitive_path_value(self):
        project = self.call("POST", "/api/projects", {"name": "Secret URL", "base_url": self.base})[1]
        pid = project["id"]
        self.call("POST", f"/api/projects/{pid}/variables",
                  {"name": "secret", "value": "a/b", "sensitive": True})
        flow = self.call("POST", f"/api/projects/{pid}/flows", {"name": "A", "steps": [
            {"kind": "http", "method": "GET", "path": "/items/{secret}",
             "headers": {"X-Secret": "{{secret}}"}}]})[1]
        preview = self.call("GET", f"/api/flows/{flow['id']}/preview?step=0")[1]
        self.assertNotIn("a/b", pretty_json(preview))
        self.assertNotIn("a%2Fb", pretty_json(preview))
        run = self.call("POST", f"/api/flows/{flow['id']}/runs", {})[1]
        self.call("POST", f"/api/runs/{run['id']}/advance", {})
        timeline = self.call("GET", f"/api/runs/{run['id']}/exchanges")[1]
        self.assertNotIn("a%2Fb", pretty_json(timeline))
        raw = self.call("GET", f"/api/runs/{run['id']}/exchanges?reveal=1")[1]
        self.assertIn("a%2Fb", raw[0]["url"])

    def test_browser_upload_stages_file_for_multipart_step(self):
        request = Request(self.base + "/api/uploads", data=b"sample-file", method="POST",
                          headers={"Content-Type": "application/octet-stream",
                                   "X-Filename": "proof.txt"})
        with urlopen(request) as response:
            upload = json.load(response)
        self.assertEqual(upload["name"], "proof.txt")
        self.assertEqual(Path(upload["path"]).read_bytes(), b"sample-file")
        self.assertTrue(str(Path(upload["path"]).resolve()).startswith(self.tmp.name))

    def test_sensitive_loop_values_are_masked_in_run_state(self):
        project = self.call("POST", "/api/projects", {"name": "Sensitive loop", "base_url": self.base})[1]
        pid = project["id"]
        self.call("POST", f"/api/projects/{pid}/variables",
                  {"name": "items", "value": ["private-one", "private-two"], "sensitive": True})
        flow = self.call("POST", f"/api/projects/{pid}/flows", {"name": "Loop", "steps": [
            {"kind": "foreach", "loop": {"list_variable": "items"}},
            {"kind": "manual", "manual_variables": ["confirm"]},
        ]})[1]
        flow["steps"][0]["routes"] = {"body": flow["steps"][1]["_id"]}
        self.call("PUT", f"/api/flows/{flow['id']}", flow)
        run = self.call("POST", f"/api/flows/{flow['id']}/runs", {})[1]
        self.call("POST", f"/api/runs/{run['id']}/advance", {})
        masked = self.call("GET", f"/api/runs/{run['id']}")[1]
        self.assertNotIn("private-one", pretty_json(masked))
        revealed = self.call("GET", f"/api/runs/{run['id']}?reveal=1")[1]
        self.assertIn("private-one", pretty_json(revealed))


def pretty_json(value):
    return json.dumps(value)


if __name__ == "__main__":
    unittest.main()
