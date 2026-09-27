import json
import os
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar
from unittest import TestCase, mock

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import api
from little_sister import app as app_module
from little_sister.reasons import Entry
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
        self.assertEqual(body["schema_version"], 2)
        self.assertTrue(body["generated_at"].endswith("Z"))
        root = body["status"]
        self.assertEqual(root["code"], "ERROR")      # rolled up from db
        self.assertEqual(root["own"], "UNDEFINED")   # the root reports nothing
        names = {child["name"] for child in root["children"]}
        self.assertEqual(names, {"services", "db"})

    def test_branch_as_json(self):
        self.tree.upsert("/services/web", StatusCode.OK)
        resp = self.client.get("/status/services", headers=JSON)
        body = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(body["status"]["name"], "services")
        self.assertEqual(body["status"]["children"][0]["name"], "web")

    def test_three_codes_under_their_own_names(self):
        """ADR-0032's three statuses, published as `reported` / `own` / `code`
        (ADR-0080 decision 2). All three agree on an unpinned node that reports for
        itself — which is why the pinned case below is the one that proves them
        apart."""
        self.tree.upsert("/db", StatusCode.ERROR, "boom")
        node = self.client.get("/status/db", headers=JSON).get_json()["status"]
        self.assertEqual(node["reported"], "ERROR")
        self.assertEqual(node["own"], "ERROR")
        self.assertEqual(node["code"], "ERROR")
        self.assertNotIn("own_code", node)

    def test_a_pin_moves_own_and_leaves_reported_saying_what_the_check_said(self):
        """The whole reason `reported` is published: a silenced node still says what
        it is doing, and *we are silencing an error* is what a surface must be able to
        show (ADR-0032 rule 5)."""
        self.tree.upsert("/db", StatusCode.ERROR, "connection refused")
        self.tree.set_maintenance("/db", "planned", set_by="ada",
                                  expires_at=datetime(2999, 1, 1))
        node = self.client.get("/status/db", headers=JSON).get_json()["status"]
        self.assertEqual(node["reported"], "ERROR")
        self.assertEqual(node["own"], "MAINTENANCE")
        self.assertEqual(node["code"], "MAINTENANCE")
        self.assertEqual([item["text"] for item in node["entries"]["items"]],
                         ["connection refused"])

    def test_entries_replace_the_string_reasons(self):
        """An object, not an array of strings: prose and members are different things
        and the old shape could say which only by convention (ADR-0036)."""
        self.tree.upsert("/db", StatusCode.ERROR, "boom")
        node = self.client.get("/status/db", headers=JSON).get_json()["status"]
        self.assertNotIn("reasons", node)
        self.assertFalse(node["entries"]["addressable"])
        item, = node["entries"]["items"]
        self.assertEqual(item["text"], "boom")
        self.assertFalse(item["running"])
        self.assertIsNone(item["maintenance"])
        self.assertIsNone(item["code"], "carries the node's, not one of its own")

    def test_addressable_entries_carry_their_key_their_code_and_their_pin(self):
        """`addressable` is the snapshot's `members`: whether these may be pinned one
        by one (ADR-0036), and an entry's own code is its own (ADR-0042)."""
        self.tree.upsert("/ci", StatusCode.ERROR, [
            Entry("build", "build #4215 failed", code=StatusCode.ERROR,
                  running=True),
            Entry("lint", "lint #4215 passed", code=StatusCode.OK),
        ], members=True)
        self.tree.set_entry_maintenance("/ci", "build", "known",
                                        expires_at=datetime(2999, 1, 1),
                                        set_by="ada")
        node = self.client.get("/status/ci", headers=JSON).get_json()["status"]
        self.assertTrue(node["entries"]["addressable"])
        build, lint = node["entries"]["items"]
        self.assertEqual([build["slug"], lint["slug"]], ["build", "lint"])
        self.assertEqual([build["code"], lint["code"]], ["ERROR", "OK"])
        self.assertTrue(build["running"])
        self.assertEqual(build["maintenance"]["note"], "known")
        self.assertIsNone(lint["maintenance"])
        self.assertEqual(node["own"], "OK", "what the unpinned entries leave")

    def test_an_entry_carries_its_subject_and_its_record(self):
        """The two fields ADR-0080 said would join the entry "in the change that
        adds them to the snapshot" — additive, `schema_version` unchanged."""
        self.tree.upsert("/ci", StatusCode.ERROR, [
            Entry("build", "CI: failed (#41)", code=StatusCode.ERROR,
                  subject="1296269",
                  data={"workflow": "CI", "run_number": 41,
                        "completed": {"at": "2026-09-19T09:12:00Z"}}),
        ], members=True)
        envelope = self.client.get("/status/ci", headers=JSON).get_json()
        self.assertEqual(envelope["schema_version"], 2)
        item, = envelope["status"]["entries"]["items"]
        self.assertEqual(item["subject"], "1296269")
        self.assertEqual(item["data"]["run_number"], 41)
        self.assertEqual(item["data"]["completed"]["at"], "2026-09-19T09:12:00Z")

    def test_an_entry_without_either_says_so_rather_than_omitting_them(self):
        """Both are always present, because both are always known: empty is "the
        check did not say", null is "no record" — not a field a client has to
        discover the absence of."""
        self.tree.upsert("/db", StatusCode.ERROR, "boom")
        node = self.client.get("/status/db", headers=JSON).get_json()["status"]
        item, = node["entries"]["items"]
        self.assertEqual(item["subject"], "")
        self.assertIsNone(item["data"])

    def test_an_entry_whose_record_was_refused_says_why_beside_a_null_record(self):
        """2.6.0 (ADR-0093): the line stands as its grading wrote it, and `refused`
        is the sentence the node's page shows — null on every other line, and never
        absent, for the reason `subject` and `data` never are."""
        self.tree.upsert("/ci", StatusCode.ERROR, [
            Entry("build", "CI: failed (#41)", code=StatusCode.ERROR,
                  subject="1296269",
                  refused="it is 2,811 bytes and the limit is 2,048"),
            Entry("lint", "lint passed", code=StatusCode.OK),
        ], members=True)
        envelope = self.client.get("/status/ci", headers=JSON).get_json()
        self.assertEqual(envelope["schema_version"], 2)
        build, lint = envelope["status"]["entries"]["items"]
        self.assertEqual(build["refused"], "it is 2,811 bytes and the limit is 2,048")
        self.assertIsNone(build["data"])
        self.assertEqual((build["text"], build["code"], build["subject"]),
                         ("CI: failed (#41)", "ERROR", "1296269"))
        self.assertIsNone(lint["refused"])

    def test_a_damped_node_publishes_a_real_code_in_its_contribution(self):
        """The first rule that **transforms** rather than withholds: `code` is the
        value the parent counted, not null, which is the case ADR-0080 decision 2
        described before there was a rule of that kind."""
        self.tree.upsert("/svc/api", StatusCode.OK, escalate_after=3)
        self.tree.upsert("/svc/api", StatusCode.ERROR)
        node = self.client.get("/status/svc/api", headers=JSON).get_json()["status"]
        self.assertEqual(node["code"], "ERROR", "the node is honest")
        self.assertEqual(node["contribution"], {"code": "OK", "by": "damping"})

    def test_a_withheld_node_still_says_null_and_names_its_rule(self):
        self.tree.upsert("/svc/api", StatusCode.UNDEFINED)
        node = self.client.get("/status/svc/api", headers=JSON).get_json()["status"]
        self.assertEqual(node["contribution"], {"code": None, "by": "undefined"})

    def test_a_node_publishes_what_its_check_measured(self):
        """2.5.0's addition, and where a measurement now lives: the object's own
        identifier and the reading, on the node that stands for the object."""
        self.tree.upsert("/web", StatusCode.OK, subject="http://web01.example",
                         record={"status": 200, "response_ms": 412})
        node = self.client.get("/status/web", headers=JSON).get_json()["status"]
        self.assertEqual(node["subject"], "http://web01.example")
        self.assertEqual(node["record"], {"status": 200, "response_ms": 412})

    def test_a_node_nobody_measured_says_so(self):
        self.tree.upsert("/web/page", StatusCode.OK)
        node = self.client.get("/status/web", headers=JSON).get_json()["status"]
        self.assertEqual(node["subject"], "")
        self.assertIsNone(node["record"])

    def test_a_shielded_node_names_the_dependency_it_is_reached_through(self):
        """2.4.0's field, and the reason it is a field: `contribution.by` says a
        dependency withheld the node, and only this says **which** — the one fact a
        client can act on. The node's own `code` is untouched."""
        self.tree.upsert("/net/vpn", StatusCode.ERROR)
        self.tree.upsert("/svc/api", StatusCode.ERROR)
        self.tree.set_dependency("/svc/api", "/net/vpn")
        node = self.client.get("/status/svc/api", headers=JSON).get_json()["status"]
        self.assertEqual(node["code"], "ERROR", "the node is honest")
        self.assertEqual(node["shielded_by"], "/net/vpn")
        self.assertEqual(node["contribution"], {"code": None, "by": "dependency"})

    def test_a_node_reaching_its_parent_says_null(self):
        self.tree.upsert("/svc/api", StatusCode.OK)
        node = self.client.get("/status/svc/api", headers=JSON).get_json()["status"]
        self.assertIsNone(node["shielded_by"])

    def test_metadata_fields_in_json_envelope(self):
        # the envelope carries the node-metadata fields as raw Markdown (ADR-0008)
        self.tree.upsert("/db", StatusCode.OK, config="- **url:** http://x")
        self.tree.set_about("/db", "the **billing** db")
        self.tree.set_title("/db", "prod")
        node = self.client.get("/status/db", headers=JSON).get_json()["status"]
        self.assertEqual(node["config"], "- **url:** http://x")    # raw, not rendered
        self.assertEqual(node["about"], "the **billing** db")
        self.assertEqual(node["title"], "prod")

    def test_the_envelope_still_carries_a_title_the_web_declines_to_draw(self):
        # A title that only repeats the name is suppressed on every *surface*
        # (`titles.py`) and on none of the contract: dropping a field is a change
        # to ADR-0008, and a client rendering its own chips is entitled to its own
        # decision about the word.
        self.tree.upsert("/github/severity/critical", StatusCode.OK)
        self.tree.set_title("/github/severity/critical", "Critical")
        node = self.client.get("/status/github/severity/critical",
                               headers=JSON).get_json()["status"]
        self.assertEqual(node["title"], "Critical")

    def test_a_declared_rank_moves_children_and_now_ships_as_a_field(self):
        """The rank the children were sorted by, so a client can *see* the order it
        was handed rather than infer it from the sequence (ADR-0055, ADR-0080
        decision 6)."""
        for band in ("critical", "high", "informational", "low", "medium"):
            self.tree.upsert(f"/wiz/{band}", StatusCode.OK,
                             order=1 if band == "informational" else 0)
        node = self.client.get("/status/wiz", headers=JSON).get_json()["status"]
        self.assertEqual([child["name"] for child in node["children"]],
                         ["critical", "high", "low", "medium", "informational"])
        self.assertEqual([child["order"] for child in node["children"]],
                         [0, 0, 0, 0, 1])

    def test_report_ships_beside_config(self):
        """What the run *found*, beside what it ran *with* — the pair ADR-0044 keeps
        under one ownership rule, and the half the envelope never carried."""
        self.tree.upsert("/db", StatusCode.OK, report="- 14 repositories",
                         config="- **url:** http://x")
        node = self.client.get("/status/db", headers=JSON).get_json()["status"]
        self.assertEqual(node["report"], "- 14 repositories")
        self.assertEqual(node["config"], "- **url:** http://x")

    def test_show_when_quiet_is_published_as_the_tri_state_it_is(self):
        """Null where nobody said, and a stated `false` is a declaration rather than
        a silence (ADR-0063) — flattening the two would throw away the difference the
        fill rule turns on."""
        self.tree.upsert("/loud", StatusCode.OK, show_when_quiet=True)
        self.tree.upsert("/hushed", StatusCode.OK, show_when_quiet=False)
        self.tree.upsert("/silent", StatusCode.OK)
        said = {child["name"]: child["show_when_quiet"] for child
                in self.client.get("/status", headers=JSON).get_json()
                ["status"]["children"]}
        self.assertEqual(said, {"loud": True, "hushed": False, "silent": None})

    def test_timestamps_are_utc_z(self):
        self.tree.upsert("/db", StatusCode.OK)
        body = self.client.get("/status/db", headers=JSON).get_json()
        self.assertTrue(body["status"]["run"]["observed_at"].endswith("Z"))
        self.assertTrue(body["generated_at"].endswith("Z"))
        self.assertNotIn("timestamp", body["status"])

    def test_a_node_nothing_answers_for_has_no_run_block_at_all(self):
        """Absent, not null. *Nothing answers for this node* and *a check answers and
        has never written* were the same null before this version, and a client that
        guessed read a container's inherited stamp as its own data age (ADR-0027's
        defect, ADR-0080 decision 5)."""
        self.tree.upsert("/svc/api", StatusCode.OK)
        node = self.client.get("/status/svc", headers=JSON).get_json()["status"]
        self.assertNotIn("run", node)
        self.assertIn("run", node["children"][0])
        self.assertIsNotNone(node["children"][0]["run"]["observed_at"])

    def test_the_run_block_carries_the_tolerance_freshness_applied(self):
        """The number, not the rule (ADR-0079 decision 5): roughly two intervals
        today, and a client that computed it from `frequency_seconds` would hold a
        second copy of a rule that is about to grow a branch."""
        self.tree.upsert("/db", StatusCode.OK, frequency_seconds=60)
        run = self.client.get("/status/db",
                              headers=JSON).get_json()["status"]["run"]
        self.assertEqual(run["frequency_seconds"], 60)
        self.assertEqual(run["stale_after_seconds"], 120.0)
        self.assertIsNone(run["wall_seconds"], "no engine ran this check")

    def test_a_node_with_no_schedule_names_no_tolerance(self):
        """It can never be stale by its own stamp, so there is no number to name."""
        self.tree.upsert("/db", StatusCode.OK)
        run = self.client.get("/status/db",
                              headers=JSON).get_json()["status"]["run"]
        self.assertNotIn("stale_after_seconds", run)
        self.assertNotIn("frequency_seconds", run)

    def test_a_node_read_on_no_schedule_publishes_its_tolerance_alone(self):
        """The instance's own nodes (ADR-0081): a stamp, a freshness promise, and
        no period. `frequency_seconds` is a claim that a subject was read on that
        interval and is only true of a check, so the branch the engine re-asserts
        on its own tick carries the tolerance and nothing a client could render as
        a check's period. Nothing in the envelope moved to say it — the two fields
        were already separate (ADR-0079 decision 5)."""
        self.tree.upsert("/little-sister/startup", StatusCode.OK, stale_after=31.0)
        run = self.client.get("/status/little-sister/startup",
                              headers=JSON).get_json()["status"]["run"]
        self.assertNotIn("frequency_seconds", run)
        self.assertEqual(run["stale_after_seconds"], 31.0)
        self.assertIsNotNone(run["observed_at"], "the tick wrote it")

    def test_maintenance_is_one_object_and_carries_both_dates(self):
        """The bool and the details object were one fact in two fields, and the bool
        is the half that cannot say anything: *pinned* is this being non-null
        (ADR-0080 decision 4). Both dates ship, because an entry whose creation was
        never recorded reads its set (ADR-0014)."""
        self.tree.upsert("/db", StatusCode.OK)
        self.tree.set_maintenance("/db", "planned", set_by="ada",
                                  expires_at=datetime(2999, 1, 1))
        node = self.client.get("/status/db", headers=JSON).get_json()["status"]
        self.assertNotIn("maintenance_details", node)
        pin = node["maintenance"]
        self.assertEqual(pin["note"], "planned",
                         "the name ADR-0047 will use, taken in the one release where "
                         "changing it is free")
        self.assertEqual(pin["set_by"], "ada")
        self.assertEqual(pin["created_by"], "ada")
        self.assertTrue(pin["expires_at"].endswith("Z"))     # RFC 3339 UTC
        self.assertTrue(pin["created_at"].endswith("Z"))

    def test_maintenance_is_null_when_nothing_is_pinned(self):
        self.tree.upsert("/db", StatusCode.OK)
        node = self.client.get("/status/db", headers=JSON).get_json()["status"]
        self.assertIsNone(node["maintenance"])

    def test_a_contribution_names_the_rule_that_withheld_the_node(self):
        """What the parent counted, and why it was not the node's `code` — ADR-0032
        rule 5 reaching the API. Null on the ordinary case, so the interesting one is
        the only one present."""
        self.tree.upsert("/ok", StatusCode.OK)
        self.tree.upsert("/pinned", StatusCode.ERROR, "boom")
        self.tree.upsert("/quiet/leaf", StatusCode.OK)
        self.tree.set_maintenance("/pinned", "planned", set_by="ada",
                                  expires_at=datetime(2999, 1, 1))
        children = {child["name"]: child for child in self.client.get(
            "/status", headers=JSON).get_json()["status"]["children"]}
        self.assertIsNone(children["ok"]["contribution"])
        self.assertEqual(children["pinned"]["contribution"],
                         {"code": None, "by": "maintenance"})
        self.assertEqual(children["quiet"]["children"][0]["contribution"], None)
        root = self.client.get("/status", headers=JSON).get_json()["status"]
        self.assertEqual(root["code"], "OK", "the pinned error is not counted")

    def test_a_node_that_never_reported_says_so_the_same_way(self):
        """`UNDEFINED` contributes nothing for a different reason than a pin does,
        and the field names which (ADR-0004 §2/§3 from the node's side)."""
        self.tree.upsert("/svc/api", StatusCode.UNDEFINED)
        node = self.client.get("/status/svc", headers=JSON).get_json()["status"]
        self.assertEqual(node["contribution"], {"code": None, "by": "undefined"})

    def test_the_instance_block_says_who_answered(self):
        """The two facts `/health` withholds from an ungated caller (ADR-0066), fine
        behind the token. Per envelope, never per node."""
        self.tree.upsert("/db", StatusCode.OK)
        with mock.patch.object(app_module, "engine_error", None):
            body = self.client.get("/status/db", headers=JSON).get_json()
        self.assertEqual(set(body["instance"]), {"version", "engine"})
        self.assertEqual(body["instance"]["engine"], "disabled")
        self.assertNotIn("instance", body["status"])

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


class TheSpecIsTheContract(TestCase):
    """`docs/api/openapi.yaml` is normative (ADR-0080), and this holds the served
    bytes to it in **both** directions: every property the envelope carries is one the
    spec declares, and every property the spec requires is served.

    The second direction is the one that pays. A field added to the serializer and not
    to the spec is exactly the drift the round exists to end, and it is invisible to
    every test that asserts what it already knows to look for.
    """

    TYPES: ClassVar[dict[str, object]] = {
        "string": str, "integer": int, "number": (int, float),
        "boolean": bool, "array": list, "object": dict, "null": type(None)}

    #: The only properties the spec may declare and a response not carry: the ones
    #: whose absence is itself the fact (ADR-0080 decision 5). Everything else must
    #: turn up in the fixture below, or the spec is promising something no run emits.
    CONDITIONAL: ClassVar[dict[str, set[str]]] = {
        "Status": {"run"},
        "Run": {"frequency_seconds", "stale_after_seconds"}}

    def setUp(self):
        import yaml
        spec = Path(__file__).resolve().parents[1] / "docs/api/openapi.yaml"
        self.schemas = yaml.safe_load(
            spec.read_text(encoding="utf-8"))["components"]["schemas"]
        self.served: dict[str, set[str]] = {}
        app_module.app.config["TESTING"] = True
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        app_module.api_tokens = {"tester": TOKEN}
        self.client = app_module.app.test_client()

    def _named(self, ref: str) -> dict:
        return self.schemas[ref.rsplit("/", 1)[-1]]

    def _check(self, value, schema, where, name=None):
        """One value against one schema node. Only what this contract uses: a `$ref`,
        a `oneOf` of a ref and null, an array of refs, an object, and scalar types."""
        if "$ref" in schema:
            ref = schema["$ref"].rsplit("/", 1)[-1]
            return self._check(value, self._named(schema["$ref"]), where, ref)
        if "oneOf" in schema:
            self.assertTrue(
                any(self._matches(value, option) for option in schema["oneOf"]),
                f"{where}: {value!r} matches none of the alternatives")
            if isinstance(value, dict):
                for option in schema["oneOf"]:
                    if "$ref" in option:
                        self._check(value, self._named(option["$ref"]), where)
            return None
        declared = schema.get("type")
        if declared is not None:
            allowed = declared if isinstance(declared, list) else [declared]
            types = tuple(self.TYPES[name] for name in allowed)
            if bool not in types:
                self.assertNotIsInstance(value, bool, f"{where}: a bool for {allowed}")
            self.assertIsInstance(value, types, f"{where}: expected {allowed}")
        if schema.get("type") == "array":
            for index, item in enumerate(value):
                self._check(item, schema["items"], f"{where}[{index}]")
            return None
        if (allowed := schema.get("enum")) is not None:
            self.assertIn(value, allowed, f"{where}: outside the declared vocabulary")
        if "properties" not in schema:
            return None
        properties = schema["properties"]
        if name is not None:
            self.served.setdefault(name, set()).update(value)
        self.assertLessEqual(
            set(value), set(properties),
            f"{where}: served properties the spec does not declare")
        self.assertLessEqual(
            set(schema.get("required", ())), set(value),
            f"{where}: the spec requires properties the envelope does not carry")
        for name, sub in properties.items():
            if name in value:
                self._check(value[name], sub, f"{where}.{name}")
        return None

    def _matches(self, value, option) -> bool:
        if "$ref" in option:
            option = self._named(option["$ref"])
        declared = option.get("type", "object")
        allowed = declared if isinstance(declared, list) else [declared]
        types = tuple(self.TYPES[name] for name in allowed)
        if bool not in types and isinstance(value, bool):
            return False
        return isinstance(value, types)

    def _a_tree_that_uses_every_shape(self):
        """One tree exercising every branch of the schema that has one: a pinned
        node, a pinned entry, a coded entry, an entry whose record was refused, a
        rank, a schedule, a container nothing answers for, and a node that has never
        reported."""
        self.tree.upsert("/ci", StatusCode.ERROR, [
            Entry("build", "build #4215 failed", code=StatusCode.ERROR, running=True),
            Entry("lint", "lint #4215 passed", code=StatusCode.OK),
            Entry("deploy", "deploy #88 passed", code=StatusCode.OK,
                  refused="it is 2,811 bytes and the limit is 2,048"),
        ], members=True, frequency_seconds=300, order=2,
            config="- **repo:** example", report="- 14 workflows",
            about="the build", title="CI", show_when_quiet=False)
        self.tree.upsert("/db", StatusCode.WARN, "slow", frequency_seconds=60)
        self.tree.upsert("/svc/api", StatusCode.UNDEFINED)
        self.tree.set_maintenance("/db", "planned", set_by="ada",
                                  expires_at=datetime(2999, 1, 1))
        self.tree.set_entry_maintenance("/ci", "build", "known", set_by="ada",
                                        expires_at=datetime(2999, 1, 1))

    def test_the_served_envelope_and_the_spec_agree_in_both_directions(self):
        self._a_tree_that_uses_every_shape()
        body = self.client.get("/status", headers=JSON).get_json()
        self._check(body, self.schemas["StatusResponse"], "status_response")

    def test_the_spec_would_notice_a_field_nobody_documented(self):
        """The check above is worth only what it refuses. A property the serializer
        invents and the spec does not declare is a failure, not a shrug."""
        self._a_tree_that_uses_every_shape()
        body = self.client.get("/status", headers=JSON).get_json()
        body["status"]["undocumented"] = "surprise"
        with self.assertRaises(AssertionError):
            self._check(body, self.schemas["StatusResponse"], "status_response")

    def test_the_spec_would_notice_a_required_field_that_went_missing(self):
        self._a_tree_that_uses_every_shape()
        body = self.client.get("/status", headers=JSON).get_json()
        del body["status"]["contribution"]
        with self.assertRaises(AssertionError):
            self._check(body, self.schemas["StatusResponse"], "status_response")

    def test_the_spec_declares_nothing_the_envelope_never_carries(self):
        """The other edge of ADR-0080 decision 1: a field the schema promises and no
        run fills is a promise no test can check and no reader can trust. So a
        property declared here has to turn up in a response — the fixture is one tree
        that uses every shape — unless its absence is the fact it carries."""
        self._a_tree_that_uses_every_shape()
        body = self.client.get("/status", headers=JSON).get_json()
        self._check(body, self.schemas["StatusResponse"], "status_response",
                    "StatusResponse")
        for name, served in sorted(self.served.items()):
            declared = set(self.schemas[name]["properties"])
            self.assertEqual(declared - served - self.CONDITIONAL.get(name, set()),
                             set(), f"{name}: declared and never served")

    def test_the_version_in_the_spec_is_the_version_on_the_wire(self):
        """`schema_version` and the spec's major are one decision (ADR-0080 decision
        1), and nothing else keeps them together."""
        import yaml
        spec = Path(__file__).resolve().parents[1] / "docs/api/openapi.yaml"
        version = yaml.safe_load(spec.read_text(encoding="utf-8"))["info"]["version"]
        self.assertEqual(version.split(".")[0], str(api.SCHEMA_VERSION))


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

    def test_a_non_ascii_bearer_token_is_refused_rather_than_raised(self):
        # A bearer token arrives off the wire and may be anything at all, while the
        # standard library's `compare_digest` raises `TypeError` for non-ASCII text
        # — so the obvious comparison turns a garbage header into a 500 instead of a
        # 401. `secrets.same_secret` compares bytes, where it does not.
        self.assertIsNone(api.authenticate("Bearer ünsinn", {"client": "tok"}))
        self.assertEqual(api.authenticate("Bearer schlüssel",
                                          {"client": "schlüssel"}), "client")

    def test_envelope_uses_utc_and_version(self):
        tree = StatusTree()
        tree.upsert("/db", StatusCode.OK)
        snap = tree.snapshot("/db")
        env = api.status_envelope(
            snap, version="0.3.16", engine="running",
            now=datetime(2026, 6, 25, 12, 0, tzinfo=UTC))
        self.assertEqual(env["generated_at"], "2026-06-25T12:00:00Z")
        self.assertEqual(env["schema_version"], 2)
        self.assertEqual(env["instance"],
                         {"version": "0.3.16", "engine": "running"})


if __name__ == "__main__":
    unittest.main()
