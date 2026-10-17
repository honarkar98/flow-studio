import tempfile
import unittest
from pathlib import Path

from studio.schema import parse
from studio.store import Store


OPENAPI = """
openapi: 3.0.3
info: {title: Example, version: '1'}
paths:
  /items/:
    get: {operationId: listItems, summary: List items, responses: {'200': {description: OK}}}
    post: {operationId: createItem, summary: Create item, responses: {'201': {description: OK}}}
"""

SWAGGER = """
swagger: '2.0'
info: {title: Other, version: '1'}
paths:
  /ping:
    get: {operationId: ping, responses: {'200': {description: OK}}}
"""


class StoreSchemaTests(unittest.TestCase):
    def test_missing_names_are_rejected_and_schema_text_is_not_sent_in_project_list(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "studio.db")
            with self.assertRaises(ValueError):
                store.create_project(None, "https://example.test")
            project = store.create_project("Demo", "https://example.test")
            with self.assertRaises(ValueError):
                store.set_variable(project["id"], None, "x")
            store.import_schema(project["id"], '{"openapi":"3.0.0","paths":{}}')
            self.assertNotIn("schema_text", store.list_projects()[0])
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "studio.sqlite3"

    def test_parses_openapi_and_swagger_without_confusing_path_parameters(self):
        version, operations = parse(OPENAPI)
        self.assertEqual(version, "3.0.3")
        self.assertEqual([(o["method"], o["path"]) for o in operations],
                         [("GET", "/items/"), ("POST", "/items/")])
        self.assertEqual(parse(SWAGGER)[0], "2.0")

    def test_projects_have_separate_catalogues_variables_and_flows(self):
        self.store = Store(self.db_path)
        first = self.store.create_project("First", "https://first.example")
        second = self.store.create_project("Second", "https://second.example")
        self.store.import_schema(first["id"], OPENAPI)
        self.store.import_schema(second["id"], SWAGGER)
        self.store.set_variable(first["id"], "token", "private", sensitive=True)
        flow = self.store.save_flow(first["id"], {"name": "Create", "steps": [{"name": "A"}]})

        self.assertEqual([o["path"] for o in self.store.list_operations(first["id"])],
                         ["/items/", "/items/"])
        self.assertEqual([o["path"] for o in self.store.list_operations(second["id"])], ["/ping"])
        self.assertEqual(self.store.get_variables(second["id"]), {})
        self.assertEqual(self.store.list_flows(second["id"]), [])
        self.assertEqual(self.store.get_flow(flow["id"])["steps"][0]["name"], "A")
        self.assertTrue(self.store.get_flow(flow["id"])["steps"][0]["_id"])

    def test_reimport_marks_removed_operation_but_preserves_flow_and_variable(self):
        self.store = Store(self.db_path)
        project = self.store.create_project("Test", "http://localhost:8000")
        self.store.import_schema(project["id"], OPENAPI)
        flow = self.store.save_flow(project["id"], {
            "name": "Flow", "steps": [{"method": "POST", "path": "/items/"}],
        })
        self.store.set_variable(project["id"], "item_id", "123")

        diff = self.store.import_schema(project["id"], SWAGGER)

        self.assertIn("POST /items/", diff["missing"])
        self.assertEqual(diff["affected_flows"], [{"flow_id": flow["id"], "flow_name": "Flow",
                                                    "step_indexes": [0], "operations": ["POST /items/"]}])
        operations = self.store.list_operations(project["id"])
        old = next(o for o in operations if o["method"] == "POST")
        self.assertTrue(old["missing"])
        self.assertEqual(self.store.get_flow(flow["id"])["steps"][0]["path"], "/items/")
        self.assertEqual(self.store.get_variables(project["id"])["item_id"]["value"], "123")

    def test_rejects_yaml_object_constructor(self):
        with self.assertRaises(ValueError):
            parse("!!python/object/apply:os.system ['echo no']")


if __name__ == "__main__":
    unittest.main()
