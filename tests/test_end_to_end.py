"""A complete generic journey across a process restart and schema update."""

import tempfile
import unittest
from pathlib import Path

from studio.runner import Runner
from studio.store import Store
from studio.transport import HTTPResult


class QueueTransport:
    def __init__(self, bodies):
        self.bodies = list(bodies)
        self.requests = []

    def send(self, request):
        self.requests.append(request)
        return HTTPResult(200, {"Content-Type": "application/json"}, self.bodies.pop(0), 2)


class EndToEndTests(unittest.TestCase):
    def test_import_configure_pause_resume_reimport_and_inspect_complete_timeline(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "studio.db"
            store = Store(db)
            project = store.create_project("Store API", "https://api.example.test")
            project_id = project["id"]
            store.import_schema(project_id, '{"openapi":"3.1.0","paths":{"/send":{"post":{}},'
                                            '"/verify":{"post":{}},"/items":{"get":{}},'
                                            '"/orders":{"post":{}},"/orders/{order_id}":{"get":{}}}}')
            store.set_variable(project_id, "email", "demo@example.test")
            flow = store.save_flow(project_id, {"name": "Order", "steps": [
                {"kind": "http", "name": "Send", "method": "POST", "path": "/send",
                 "body": {"email": "{{email}}"}},
                {"kind": "manual", "name": "Code", "manual_variables": ["code"],
                 "sensitive_variables": ["code"]},
                {"kind": "http", "name": "Verify", "method": "POST", "path": "/verify",
                 "body": {"code": "{{code}}"},
                 "captures": [{"name": "token", "path": "access", "sensitive": True}]},
                {"kind": "http", "name": "Items", "method": "GET", "path": "/items",
                 "headers": {"Authorization": "Bearer {{token}}"},
                 "captures": [{"name": "item_id", "path": "results[0].id"}]},
                {"kind": "http", "name": "Create", "method": "POST", "path": "/orders",
                 "body": {"item": "{{item_id}}"},
                 "captures": [{"name": "order_id", "path": "id"}]},
                {"kind": "http", "name": "Inspect", "method": "GET", "path": "/orders/{order_id}",
                 "assertions": [{"path": "status", "equals": "ready"}]},
            ]})
            transport = QueueTransport([{"sent": True}, {"access": "jwt"},
                                        {"results": [{"id": 42}]}, {"id": "order-7"},
                                        {"status": "ready"}])
            run_id = Runner(store, transport).start(flow["id"])
            self.assertEqual(Runner(store, transport).advance(run_id)["next_index"], 1)
            diff = store.import_schema(project_id, '{"openapi":"3.1.0","paths":{"/new":{"get":{}}}}')
            self.assertIn("POST /send", diff["missing"])
            restarted = Store(db)
            done = Runner(restarted, transport).advance(run_id, {"code": "654321"})
            self.assertEqual(done["status"], "completed")
            self.assertEqual(restarted.get_variables(project_id)["order_id"]["value"], "order-7")
            self.assertEqual([item["url"] for item in restarted.list_exchanges(run_id)], [
                "https://api.example.test/send", "https://api.example.test/verify",
                "https://api.example.test/items", "https://api.example.test/orders",
                "https://api.example.test/orders/order-7",
            ])
            self.assertEqual(restarted.list_exchanges(run_id)[3]["request_body"], {"item": 42})
            self.assertEqual(restarted.list_exchanges(run_id)[-1]["response_body"], {"status": "ready"})
            self.assertEqual(transport.requests[2].headers["Authorization"], "Bearer jwt")


if __name__ == "__main__":
    unittest.main()
