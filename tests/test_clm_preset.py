import tempfile
import unittest
from pathlib import Path

from studio.presets import install_clm_v2_preset
from studio.runner import Runner
from studio.store import Store
from studio.transport import HTTPResult


class QueueTransport:
    def __init__(self, bodies):
        self.bodies = list(bodies)
        self.requests = []

    def send(self, request):
        self.requests.append(request)
        return HTTPResult(200, {}, self.bodies.pop(0), 1)


class PresetTests(unittest.TestCase):
    def test_preset_is_editable_flow_data_in_an_ordinary_project(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "db.sqlite3")
            project = store.create_project("Any project", "http://127.0.0.1:8000")
            flow_id = install_clm_v2_preset(store, project["id"])
            flow = store.get_flow(flow_id)
            self.assertEqual(len(flow["steps"]), 12)
            self.assertEqual(flow["steps"][1]["kind"], "manual")
            self.assertEqual(flow["steps"][3]["captures"][0]["path"], "[0].id")
            self.assertEqual(flow["steps"][-1]["assertions"],
                             [{"path": "contract.status", "equals": "signing"}])
            self.assertEqual(flow["steps"][-1]["path"],
                             "/api/v2/tenants/{tenant_id}/contracts/{contract_id}/send-for-signing/")
            flow["name"] = "Edited"
            store.save_flow(project["id"], flow)
            self.assertEqual(store.get_flow(flow_id)["name"], "Edited")
            self.assertEqual(store.get_project(project["id"])["refresh"]["path"],
                             "/api/auth/token/refresh/")

    def test_preset_preserves_existing_settings_and_marks_identity_values_sensitive(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "db.sqlite3")
            project = store.create_project("Existing", "https://example.test")
            pid = project["id"]
            refresh = {"method": "POST", "path": "/my-refresh"}
            store.save_project(pid, {"refresh": refresh})
            store.set_variable(pid, "contract_content", {"json": {"custom": True}})
            install_clm_v2_preset(store, pid)
            self.assertEqual(store.get_project(pid)["refresh"], refresh)
            self.assertEqual(store.get_variables(pid)["contract_content"]["value"],
                             {"json": {"custom": True}})
            store.set_variable(pid, "national_id", "TEST-NATIONAL-ID")
            self.assertTrue(store.get_variables(pid)["national_id"]["sensitive"])

    def test_clm_preset_composes_all_12_steps_through_signing(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "db.sqlite3")
            project = store.create_project("CLM", "http://127.0.0.1:8000")
            pid = project["id"]
            flow_id = install_clm_v2_preset(store, pid)
            for name, value in {"mobile": "TEST-MOBILE", "national_id": "TEST-NATIONAL-ID",
                                "address": "تهران", "contract_title": "نمونه",
                                "end_date": "2027-10-17", "signer_user_id": 9}.items():
                store.set_variable(pid, name, value)
            transport = QueueTransport([
                {"message": "sent"},
                {"tokens": {"access": "jwt", "refresh": "refresh"}, "user": {"id": 3}},
                [{"id": "tenant-1"}], {"results": []},
                {"id": "contract-1", "contract": {"status": "draft"}},
                {"contract": {"status": "draft"}}, {"id": "party-1"},
                {"contract": {"status": "under_approval"}}, [],
                {"contract": {"status": "approved"}},
                {"contract": {"status": "signing"}},
            ])
            runner = Runner(store, transport)
            run_id = runner.start(flow_id)
            self.assertEqual(runner.advance(run_id)["next_index"], 1)
            self.assertEqual(runner.advance(run_id, {"otp": "123456"})["status"], "completed")
            self.assertEqual(len(store.list_exchanges(run_id)), 11)
            self.assertEqual(transport.requests[6].body["members"][0]["user_id"], 9)
            self.assertEqual(transport.requests[-1].url,
                             "http://127.0.0.1:8000/api/v2/tenants/tenant-1/contracts/contract-1/send-for-signing/")
            self.assertEqual(store.get_variables(pid)["contract_id"]["value"], "contract-1")


if __name__ == "__main__":
    unittest.main()
