import tempfile
import unittest
from pathlib import Path

from studio.expressions import render, extract, capture, assert_response
from studio.request import build_request


class ExpressionTests(unittest.TestCase):
    def test_exact_placeholder_keeps_json_type_and_embedded_text_is_a_string(self):
        result = render({"count": "{{count}}", "note": "ID {{id}}"}, {"count": 3, "id": "A7"})
        self.assertEqual(result, {"count": 3, "note": "ID A7"})

    def test_missing_variable_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "missing"):
            render({"id": "{{missing}}"}, {})

    def test_extracts_nested_array_and_rejects_empty_array(self):
        self.assertEqual(extract({"results": [{"id": "t-1"}]}, "results[0].id"), "t-1")
        with self.assertRaises(ValueError):
            extract({"results": []}, "results[0].id")

    def test_capture_does_not_partially_update_on_missing_path(self):
        old = {"tenant_id": "old"}
        with self.assertRaises(ValueError):
            capture({"results": []}, [
                {"name": "ok", "path": "$"}, {"name": "tenant_id", "path": "results[0].id"},
            ], old)
        self.assertEqual(old, {"tenant_id": "old"})

    def test_assertion_checks_response_value(self):
        assert_response({"contract": {"status": "approved"}},
                        [{"path": "contract.status", "equals": "approved"}])
        with self.assertRaises(ValueError):
            assert_response({"contract": {"status": "draft"}},
                            [{"path": "contract.status", "equals": "approved"}])

    def test_build_request_encodes_path_query_and_renders_headers_and_json(self):
        request = build_request({"base_url": "https://api.example.test/base"}, {
            "method": "POST", "path": "/items/{item_id}",
            "query": {"q": "{{search}}"},
            "headers": {"Authorization": "Bearer {{token}}"},
            "body": {"count": "{{count}}"},
        }, {"item_id": "a/b", "search": "a b", "token": "secret", "count": 2})
        self.assertEqual(request.url, "https://api.example.test/base/items/a%2Fb?q=a+b")
        self.assertEqual(request.headers["Authorization"], "Bearer secret")
        self.assertEqual(request.body, {"count": 2})
        self.assertEqual(request.content_type, "application/json")

    def test_multipart_request_carries_fields_and_file_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.txt"
            path.write_text("hello")
            request = build_request({"base_url": "http://localhost:8000"}, {
                "method": "POST", "path": "/upload", "body_mode": "multipart",
                "body": {"label": "{{label}}"}, "files": {"file": "{{file_path}}"},
            }, {"label": "photo", "file_path": str(path)})
            self.assertEqual(request.body, {"label": "photo"})
            self.assertEqual(request.files, {"file": str(path)})
            self.assertEqual(request.content_type, "multipart/form-data")


if __name__ == "__main__":
    unittest.main()
