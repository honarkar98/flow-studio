import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from studio.runner import Runner
from studio.store import Store
from studio.transport import HTTPResult


class FakeTransport:
    def __init__(self, results):
        self.results = list(results)
        self.requests = []

    def send(self, request):
        self.requests.append(request)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class RunnerTests(unittest.TestCase):
    def test_editing_failed_step_updates_retry_in_same_run(self):
        flow = self.flow([{"name": "Get", "kind": "http", "method": "GET", "path": "/old"}])
        first = FakeTransport([HTTPResult(500, {}, {"error": "temporary"}, 1)])
        runner = Runner(self.store, first)
        run_id = runner.start(flow["id"])
        self.assertEqual(runner.advance(run_id)["status"], "failed")
        flow["steps"][0]["path"] = "/new"
        self.store.save_flow(self.project["id"], flow)
        retry = FakeTransport([HTTPResult(200, {}, {"ok": True}, 1)])
        self.assertEqual(Runner(self.store, retry).advance(run_id)["status"], "completed")
        self.assertEqual([e["url"] for e in self.store.list_exchanges(run_id)],
                         ["https://example.test/old", "https://example.test/new"])

    def test_invalid_capture_name_is_rejected_before_post_is_sent(self):
        flow = self.flow([{"kind": "http", "method": "POST", "path": "/create",
                           "captures": [{"name": "bad-name", "path": "id"}]}])
        transport = FakeTransport([HTTPResult(201, {}, {"id": 1}, 1)])
        runner = Runner(self.store, transport)
        run_id = runner.start(flow["id"])
        run = runner.advance(run_id)
        self.assertEqual((run["status"], run["next_index"]), ("waiting", 0))
        self.assertEqual(transport.requests, [])
        self.assertEqual(self.store.list_exchanges(run_id), [])

    def test_missing_capture_field_records_successful_post_response(self):
        flow = self.flow([{"kind": "http", "method": "POST", "path": "/create",
                           "captures": [{"name": "id", "path": "missing"}]}])
        runner = Runner(self.store, FakeTransport([HTTPResult(201, {}, {"id": 1}, 1)]))
        run_id = runner.start(flow["id"])
        run = runner.advance(run_id)
        self.assertEqual(run["status"], "failed")
        self.assertEqual(self.store.list_exchanges(run_id)[0]["response_body"], {"id": 1})

    def test_concurrent_advance_sends_post_only_once(self):
        flow = self.flow([{"kind": "http", "method": "POST", "path": "/create"}])
        entered = threading.Event()
        release = threading.Event()

        class BlockingTransport:
            calls = 0

            def send(self, request):
                self.calls += 1
                entered.set()
                release.wait(3)
                return HTTPResult(201, {}, {"id": 1}, 1)

        transport = BlockingTransport()
        runner = Runner(self.store, transport)
        run_id = runner.start(flow["id"])
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(runner.advance, run_id)
            self.assertTrue(entered.wait(2))
            with self.assertRaisesRegex(ValueError, "در حال انجام"):
                runner.advance(run_id)
            release.set()
            self.assertEqual(first.result().get("status"), "completed")
        self.assertEqual(transport.calls, 1)
        self.assertEqual(len(self.store.list_exchanges(run_id)), 1)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "studio.sqlite3"
        self.store = Store(self.db)
        self.project = self.store.create_project("Any API", "https://example.test")

    def flow(self, steps):
        return self.store.save_flow(self.project["id"], {"name": "Journey", "steps": steps})

    def test_manual_otp_pauses_and_resume_after_restart_keeps_exchange_order(self):
        flow = self.flow([
            {"name": "Send", "kind": "http", "method": "POST", "path": "/send", "body": {"mobile": "{{mobile}}"}},
            {"name": "OTP", "kind": "manual", "manual_variables": ["otp"]},
            {"name": "Verify", "kind": "http", "method": "POST", "path": "/verify",
             "body": {"code": "{{otp}}"}, "captures": [{"name": "access", "path": "tokens.access", "sensitive": True}]},
        ])
        self.store.set_variable(self.project["id"], "mobile", "TEST-MOBILE")
        transport = FakeTransport([HTTPResult(200, {}, {"sent": True}, 3),
                                   HTTPResult(200, {}, {"tokens": {"access": "JWT"}}, 4)])
        run_id = Runner(self.store, transport).start(flow["id"])

        paused = Runner(self.store, transport).advance(run_id)
        self.assertEqual((paused["status"], paused["next_index"]), ("waiting", 1))
        restarted = Store(self.db)
        done = Runner(restarted, transport).advance(run_id, {"otp": "123456"})
        self.assertEqual(done["status"], "completed")
        self.assertEqual(restarted.get_variables(self.project["id"])["access"]["value"], "JWT")
        self.assertEqual(transport.requests[-1].body, {"code": "123456"})
        exchanges = restarted.list_exchanges(run_id)
        self.assertEqual([(e["sequence"], e["url"], e["response_body"]) for e in exchanges], [
            (1, "https://example.test/send", {"sent": True}),
            (2, "https://example.test/verify", {"tokens": {"access": "JWT"}}),
        ])

    def test_start_from_later_step_uses_saved_contract_id(self):
        flow = self.flow([
            {"name": "Create", "kind": "http", "method": "POST", "path": "/contracts"},
            {"name": "Use", "kind": "http", "method": "GET", "path": "/contracts/{contract_id}"},
        ])
        self.store.set_variable(self.project["id"], "contract_id", "abc-123")
        transport = FakeTransport([HTTPResult(200, {}, {"id": "abc-123"}, 2)])
        run_id = Runner(self.store, transport).start(flow["id"], start_index=1)
        self.assertEqual(Runner(self.store, transport).advance(run_id)["status"], "completed")
        self.assertEqual(transport.requests[0].url, "https://example.test/contracts/abc-123")

    def test_http_error_and_timeout_keep_checkpoint_and_prior_variable(self):
        flow = self.flow([{"name": "Get", "kind": "http", "method": "GET", "path": "/items",
                           "captures": [{"name": "item_id", "path": "id"}]}])
        self.store.set_variable(self.project["id"], "item_id", "old")
        run_id = Runner(self.store, FakeTransport([HTTPResult(500, {}, {"error": "bad"}, 5)])).start(flow["id"])
        failed = Runner(self.store, FakeTransport([HTTPResult(500, {}, {"error": "bad"}, 5)])).advance(run_id)
        self.assertEqual((failed["status"], failed["next_index"]), ("failed", 0))
        self.assertEqual(self.store.get_variables(self.project["id"])["item_id"]["value"], "old")
        self.assertEqual(self.store.list_exchanges(run_id)[0]["response_status"], 500)

        retry = Runner(self.store, FakeTransport([TimeoutError("timed out")])).advance(run_id)
        self.assertEqual((retry["status"], retry["next_index"]), ("failed", 0))
        self.assertEqual(len(self.store.list_exchanges(run_id)), 2)

    def test_repeating_successful_post_requires_acknowledgement(self):
        flow = self.flow([{"name": "Create", "kind": "http", "method": "POST", "path": "/items"}])
        runner = Runner(self.store, FakeTransport([HTTPResult(201, {}, {"id": 1}, 1)]))
        runner.advance(runner.start(flow["id"]))
        with self.assertRaisesRegex(ValueError, "POST"):
            runner.start(flow["id"])
        second = runner.start(flow["id"], acknowledge_post=True)
        self.assertEqual(self.store.get_run(second)["next_index"], 0)
        self.assertEqual(Runner(self.store, FakeTransport([HTTPResult(201, {}, {"id": 2}, 1)]))
                         .advance(second)["status"], "completed")

    def test_configured_refresh_logs_all_attempts_and_updates_tokens(self):
        self.store.save_project(self.project["id"], {"refresh": {
            "method": "POST", "path": "/refresh", "body": {"refresh": "{{refresh_token}}"},
            "captures": [{"name": "access_token", "path": "access", "sensitive": True},
                         {"name": "refresh_token", "path": "refresh", "sensitive": True}],
        }})
        self.store.set_variable(self.project["id"], "access_token", "old", sensitive=True)
        self.store.set_variable(self.project["id"], "refresh_token", "r1", sensitive=True)
        self.store.set_variable(self.project["id"], "contract_id", "keep")
        flow = self.flow([{"name": "List", "kind": "http", "method": "GET", "path": "/items",
                           "headers": {"Authorization": "Bearer {{access_token}}"}, "refresh_on_401": True}])
        transport = FakeTransport([
            HTTPResult(401, {}, {"code": "expired"}, 1),
            HTTPResult(200, {}, {"access": "new", "refresh": "r2"}, 1),
            HTTPResult(200, {}, {"results": []}, 1),
        ])
        runner = Runner(self.store, transport)
        run_id = runner.start(flow["id"])
        self.assertEqual(runner.advance(run_id)["status"], "completed")
        self.assertEqual([e["response_status"] for e in self.store.list_exchanges(run_id)], [401, 200, 200])
        self.assertEqual(transport.requests[-1].headers["Authorization"], "Bearer new")
        self.assertEqual(self.store.get_variables(self.project["id"])["contract_id"]["value"], "keep")

    def test_refresh_failure_preserves_unrelated_variables_and_records_both_attempts(self):
        self.store.save_project(self.project["id"], {"refresh": {
            "method": "POST", "path": "/refresh", "body": {"refresh": "{{refresh_token}}"},
            "captures": [{"name": "access_token", "path": "access"}],
        }})
        self.store.set_variable(self.project["id"], "refresh_token", "expired")
        self.store.set_variable(self.project["id"], "contract_id", "keep")
        flow = self.flow([{"name": "List", "kind": "http", "method": "GET", "path": "/items",
                           "refresh_on_401": True}])
        runner = Runner(self.store, FakeTransport([
            HTTPResult(401, {}, {"code": "expired"}, 1), HTTPResult(401, {}, {"code": "bad_refresh"}, 1),
        ]))
        run_id = runner.start(flow["id"])
        self.assertEqual(runner.advance(run_id)["status"], "waiting")
        self.assertEqual(self.store.get_variables(self.project["id"])["contract_id"]["value"], "keep")
        self.assertEqual([e["response_status"] for e in self.store.list_exchanges(run_id)], [401, 401])

    def test_invalid_refreshed_path_value_waits_with_both_attempts_saved(self):
        self.store.save_project(self.project["id"], {"refresh": {
            "method": "POST", "path": "/refresh", "captures": [
                {"name": "access_token", "path": "access", "sensitive": True}],
        }})
        self.store.set_variable(self.project["id"], "access_token", "old", sensitive=True)
        flow = self.flow([{"kind": "http", "method": "GET", "path": "/items/{access_token}",
                           "refresh_on_401": True}])
        runner = Runner(self.store, FakeTransport([
            HTTPResult(401, {}, {}, 1), HTTPResult(200, {}, {"access": {"invalid": True}}, 1),
        ]))
        run_id = runner.start(flow["id"])
        run = runner.advance(run_id)
        self.assertEqual((run["status"], run["next_index"]), ("waiting", 0))
        self.assertEqual(len(self.store.list_exchanges(run_id)), 2)

    def test_condition_routes_to_selected_branch(self):
        flow = self.flow([
            {"kind": "condition", "name": "Decision", "condition": {"variable": "approved", "operator": "equals", "value": True}},
            {"kind": "http", "method": "GET", "path": "/yes"},
            {"kind": "http", "method": "GET", "path": "/no"},
        ])
        first, yes, no = (step["_id"] for step in flow["steps"])
        flow["steps"][0]["routes"] = {"yes": yes, "no": no}
        flow["steps"][1]["routes"] = {"next": None}
        flow["steps"][2]["routes"] = {"next": None}
        self.store.save_flow(self.project["id"], flow)
        self.store.set_variable(self.project["id"], "approved", False)
        transport = FakeTransport([HTTPResult(200, {}, {}, 1)])
        run_id = Runner(self.store, transport).start(flow["id"])
        self.assertEqual(Runner(self.store, transport).advance(run_id)["status"], "completed")
        self.assertEqual([request.url for request in transport.requests], ["https://example.test/no"])
        self.assertEqual(self.store.get_run(run_id)["graph_state"]["trace"], [first, no])

    def test_foreach_resume_after_manual_input_keeps_cursor(self):
        flow = self.flow([
            {"kind": "foreach", "loop": {"list_variable": "items", "item_variable": "item", "index_variable": "item_index"}},
            {"kind": "http", "method": "GET", "path": "/items/{item}"},
            {"kind": "manual", "name": "Approve", "manual_variables": ["otp"]},
            {"kind": "http", "method": "GET", "path": "/done"},
        ])
        loop, request, manual, done = (step["_id"] for step in flow["steps"])
        flow["steps"][0]["routes"] = {"body": request, "done": done}
        flow["steps"][2]["routes"] = {"next": loop}
        flow["steps"][3]["routes"] = {"next": None}
        self.store.save_flow(self.project["id"], flow)
        self.store.set_variable(self.project["id"], "items", ["a", "b"])
        transport = FakeTransport([HTTPResult(200, {}, {}, 1), HTTPResult(200, {}, {}, 1),
                                   HTTPResult(200, {}, {}, 1)])
        run_id = Runner(self.store, transport).start(flow["id"])
        paused = Runner(self.store, transport).advance(run_id)
        self.assertEqual((paused["status"], paused["next_index"]), ("waiting", 2))
        self.assertEqual(paused["graph_state"]["loops"][loop]["cursor"], 0)
        restarted = Store(self.db)
        second = Runner(restarted, transport).advance(run_id, {"otp": "1234"})
        self.assertEqual((second["status"], second["next_index"]), ("waiting", 2))
        self.assertEqual(second["graph_state"]["loops"][loop]["cursor"], 1)
        finished = Runner(restarted, transport).advance(run_id, {"otp": "5678"})
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(finished["graph_state"]["loops"], {})
        self.assertEqual([request.url for request in transport.requests],
                         ["https://example.test/items/a", "https://example.test/items/b", "https://example.test/done"])

    def test_error_route_records_full_detail_and_continues(self):
        flow = self.flow([{"kind": "http", "method": "GET", "path": "/fail"},
                          {"kind": "http", "method": "GET", "path": "/recover"}])
        flow["steps"][0]["routes"] = {"error": flow["steps"][1]["_id"]}
        self.store.save_flow(self.project["id"], flow)
        transport = FakeTransport([HTTPResult(422, {}, {"message": "Invalid input", "code": "bad_input",
                                                      "errors": {"field": ["required"]}}, 1),
                                   HTTPResult(200, {}, {}, 1)])
        run_id = Runner(self.store, transport).start(flow["id"])
        self.assertEqual(Runner(self.store, transport).advance(run_id)["status"], "completed")
        exchange = self.store.list_exchanges(run_id)[0]
        self.assertIn("Invalid input", exchange["error"])
        self.assertIn("bad_input", exchange["error"])
        self.assertEqual(len(self.store.list_exchanges(run_id)), 2)

    def test_transport_error_uses_error_route(self):
        flow = self.flow([{"kind": "http", "method": "GET", "path": "/timeout"},
                          {"kind": "http", "method": "GET", "path": "/recover"}])
        flow["steps"][0]["routes"] = {"error": flow["steps"][1]["_id"]}
        self.store.save_flow(self.project["id"], flow)
        transport = FakeTransport([TimeoutError("timed out"), HTTPResult(200, {}, {}, 1)])
        run_id = Runner(self.store, transport).start(flow["id"])
        self.assertEqual(Runner(self.store, transport).advance(run_id)["status"], "completed")
        self.assertEqual(self.store.list_exchanges(run_id)[0]["error"], "timed out")


if __name__ == "__main__":
    unittest.main()
