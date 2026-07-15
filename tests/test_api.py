import json
import os
import unittest
from datetime import UTC, datetime
from unittest import TestCase

# Import the app with the background engine disabled (no threads/network).
os.environ.setdefault("LITTLE_SISTER_ENGINE", "0")
os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import api
from little_sister import app as app_module
from little_sister.status import StatusCode
from little_sister.tree import StatusTree

TOKEN = "secret-token"
JSON = {"Accept": "application/json", "Authorization": f"Bearer {TOKEN}"}


class JsonApiTests(TestCase):
    def setUp(self):
        app_module.app.config["TESTING"] = True
        # Each test gets its own tree and token map (the route reads these globals).
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        app_module.api_tokens = {"tester": TOKEN}
        self.client = app_module.app.test_client()

    def test_tree_as_json(self):
        self.tree.upsert("/services/web", StatusCode.OK)
        self.tree.upsert("/db", StatusCode.ERROR, "connection refused")
        resp = self.client.get("/status", headers=JSON)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.mimetype, "application/json")
        body = resp.get_json()
        self.assertEqual(body["schema_version"], 1)
        self.assertTrue(body["generated_at"].endswith("Z"))
        root = body["status"]
        self.assertEqual(root["code"], "ERROR")        # rolled up from db
        self.assertEqual(root["own_code"], "UNDEFINED")  # the root reports nothing
        names = {child["name"] for child in root["children"]}
        self.assertEqual(names, {"services", "db"})

    def test_branch_as_json(self):
        self.tree.upsert("/services/web", StatusCode.OK)
        resp = self.client.get("/status/services", headers=JSON)
        body = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(body["status"]["name"], "services")
        self.assertEqual(body["status"]["children"][0]["name"], "web")

    def test_codes_are_names_and_reasons_plural(self):
        self.tree.upsert("/db", StatusCode.ERROR, "boom")
        node = self.client.get("/status/db", headers=JSON).get_json()["status"]
        self.assertEqual(node["own_code"], "ERROR")
        self.assertEqual(node["code"], "ERROR")
        self.assertEqual(node["reasons"], ["boom"])

    def test_metadata_fields_in_json_envelope(self):
        # the envelope carries the node-metadata fields as raw Markdown (ADR-0008)
        self.tree.upsert("/db", StatusCode.OK, config="- **url:** http://x")
        self.tree.set_about("/db", "the **billing** db")
        self.tree.set_title("/db", "prod")
        node = self.client.get("/status/db", headers=JSON).get_json()["status"]
        self.assertEqual(node["config"], "- **url:** http://x")    # raw, not rendered
        self.assertEqual(node["about"], "the **billing** db")
        self.assertEqual(node["title"], "prod")

    def test_timestamps_are_utc_z(self):
        self.tree.upsert("/db", StatusCode.OK)
        body = self.client.get("/status/db", headers=JSON).get_json()
        self.assertTrue(body["status"]["timestamp"].endswith("Z"))
        self.assertTrue(body["generated_at"].endswith("Z"))

    def test_maintenance_serialized(self):
        self.tree.upsert("/db", StatusCode.OK)
        self.tree.set_maintenance("/db", "planned", set_by="ada",
                                  expires_at=datetime(2999, 1, 1))
        node = self.client.get("/status/db", headers=JSON).get_json()["status"]
        self.assertTrue(node["maintenance"])
        self.assertEqual(node["own_code"], "MAINTENANCE")
        # the override's details ride along as a nested object (ADR-0014)
        details = node["maintenance_details"]
        self.assertEqual(details["reason"], "planned")
        self.assertEqual(details["set_by"], "ada")
        self.assertTrue(details["expires_at"].endswith("Z"))     # RFC 3339 UTC

    def test_maintenance_details_null_when_not_in_maintenance(self):
        self.tree.upsert("/db", StatusCode.OK)
        node = self.client.get("/status/db", headers=JSON).get_json()["status"]
        self.assertFalse(node["maintenance"])
        self.assertIsNone(node["maintenance_details"])

    def test_missing_token_is_401_problem(self):
        resp = self.client.get("/status", headers={"Accept": "application/json"})
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.mimetype, "application/problem+json")
        body = json.loads(resp.get_data(as_text=True))
        self.assertEqual(body["status"], 401)
        self.assertEqual(body["title"], "Unauthorized")

    def test_bad_token_is_401(self):
        resp = self.client.get(
            "/status",
            headers={"Accept": "application/json",
                     "Authorization": "Bearer nope"})
        self.assertEqual(resp.status_code, 401)

    def test_unknown_branch_is_404_problem(self):
        resp = self.client.get("/status/nope", headers=JSON)
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.mimetype, "application/problem+json")
        self.assertEqual(json.loads(resp.get_data(as_text=True))["status"], 404)

    def test_x_flow_id_echoed(self):
        resp = self.client.get("/status", headers={**JSON, "X-Flow-Id": "abc-123"})
        self.assertEqual(resp.headers.get("X-Flow-Id"), "abc-123")

    def test_html_path_unaffected_and_needs_session(self):
        # No JSON Accept → the HTML dashboard still requires a session.
        self.assertEqual(self.client.get("/status").status_code, 302)
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})
        resp = self.client.get("/status")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/html", resp.content_type)

    def test_json_does_not_need_session(self):
        self.tree.upsert("/db", StatusCode.OK)
        resp = self.client.get("/status", headers=JSON)
        self.assertEqual(resp.status_code, 200)


class SerializerUnitTests(TestCase):
    def test_parse_api_tokens(self):
        self.assertEqual(
            api.parse_api_tokens("a=1, b=2 , bad,=x,c="),
            {"a": "1", "b": "2"})

    def test_authenticate(self):
        tokens = {"client": "tok"}
        self.assertEqual(api.authenticate("Bearer tok", tokens), "client")
        self.assertEqual(api.authenticate("bearer tok", tokens), "client")
        self.assertIsNone(api.authenticate("Bearer wrong", tokens))
        self.assertIsNone(api.authenticate("Basic tok", tokens))
        self.assertIsNone(api.authenticate(None, tokens))

    def test_envelope_uses_utc_and_version(self):
        tree = StatusTree()
        tree.upsert("/db", StatusCode.OK)
        snap = tree.snapshot("/db")
        env = api.status_envelope(
            snap, now=datetime(2026, 6, 25, 12, 0, tzinfo=UTC))
        self.assertEqual(env["generated_at"], "2026-06-25T12:00:00Z")
        self.assertEqual(env["schema_version"], 1)


if __name__ == "__main__":
    unittest.main()
