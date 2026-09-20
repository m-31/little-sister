"""The golden envelope is what this API actually answers.

`little_sister.contract` ships one envelope in the wheel and the family shares it
with the macOS client, so that the two repositories test **one** artifact rather
than each maintaining its own hand-written JSON — the drift that entry existed to
end. An artifact nobody holds to the code is a fixture that quietly stops being
true, so this builds the scene the artifact was made from, asks the real API for it,
and compares.

Run ``python tests/test_contract_fixture.py`` to rewrite the artifact after a
deliberate envelope change; the diff it produces is the review.
"""
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from unittest import TestCase

os.environ.setdefault("LITTLE_SISTER_ENGINE", "0")
os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister import contract
from little_sister.reasons import Entry
from little_sister.status import StatusCode
from little_sister.tree import StatusTree

TOKEN = "secret-token"
JSON_HEADERS = {"Accept": "application/json", "Authorization": f"Bearer {TOKEN}"}

#: The field names that differ between two correct runs. Kept here **and** in the
#: artifact, because the artifact is read by a client that cannot import this.
VOLATILE = ["generated_at", "observed_at", "next_at", "version",
            "set_at", "created_at"]


def build_scene(tree: StatusTree) -> None:
    """One tree carrying every optional shape `schema_version` 2 has.

    Every line below is here because the envelope has a field that is otherwise
    never populated: a reader who deletes one deletes a shape the client is no
    longer tested against.
    """
    # A plain leaf: `run` present, entries empty, nothing optional set — and no
    # `frequency_seconds`, which is the *paced* shape a client must also decode.
    tree.upsert("/services/web", StatusCode.OK)
    # A scheduled leaf: the interval it is read on and the tolerance the server
    # applied. The client has a test per field of this, so an artifact without it
    # would leave that suite on its own fixtures whatever else happened.
    tree.upsert("/services/api", StatusCode.OK,
                frequency_seconds=300, stale_after=900.0)
    # Prose entries, and a node whose parent rolls up from it.
    tree.upsert("/services/db", StatusCode.ERROR, "connection refused")
    # Display metadata that is not a status claim (ADR-0044): report, title,
    # about, config, order, show_when_quiet.
    tree.upsert("/platform", StatusCode.WARN, "one repository is short",
                description="the platform team's repositories",
                report="- [api](https://example.test/api)",
                config="checks/platform.yaml", about="what this watches",
                title="Platform", order=3, show_when_quiet=False)
    # Addressable entries: a slug of its own, its own code, a subject and a record
    # on one, and neither on the next — the two halves of ADR-0082.
    tree.upsert("/platform/actions", StatusCode.ERROR, [
        Entry("1001-workflow-42-main", "acme/api (main) / CI: failed (#128)",
              code=StatusCode.ERROR, subject="1001",
              data={"repository": "acme/api", "workflow": "CI",
                    "branch": "main", "verdict": "failed",
                    # `at`, `started` and `ended` are the only typed keys of a
                    # record, at any depth, and they are RFC 3339 UTC. A record
                    # without them leaves the one thing a client must parse in
                    # `data` untested.
                    "at": "2026-09-18T06:12:04Z",
                    "run": {"number": 128, "status": "completed",
                            "conclusion": "failure",
                            "started": "2026-09-18T06:04:41Z",
                            "ended": "2026-09-18T06:12:04Z"}}),
        Entry("1001-workflow-77", "acme/api / nightly: disabled manually",
              code=StatusCode.WARN),
    ])
    # A branch that answers for nothing itself: `run` is absent here.
    tree.upsert("/platform/actions/acme-api", StatusCode.OK)
    # **A damped node**, and it is the case the whole `contribution` field changed
    # shape for. Until damping, every rule at that boundary *withheld* a node and
    # `contribution.code` was always null, so a client could read the field as "this
    # node was not counted" and be right. Damping **transforms**: the node is ERROR,
    # the parent counted the held WARN, and `contribution.code` is deliberately the
    # value the node's own `code` is not. An artifact without this asserts the old
    # shape, and the first client written against it reads the damped case wrong.
    tree.upsert("/services/queue", StatusCode.OK, escalate_after=3)
    tree.upsert("/services/queue", StatusCode.ERROR, "the consumer is behind",
                escalate_after=3)
    # **A measured node**: 2.5.0's addition, and the shape a check that reads one
    # object now produces — the measurement on the node that stands for the object,
    # with the object's own identifier rather than the node's path. Every other node
    # in this scene carries an empty subject and a null record, which is what a
    # client meets on a container and on a mount two checks share.
    tree.upsert("/services/web", StatusCode.OK, subject="http://web01.example",
                record={"status": 200, "response_ms": 412})
    # **A shielded node**: 2.4.0's addition, and the second rule that speaks about a
    # *reading* rather than about the node. The gateway is failing, so the unit
    # reached through it keeps its own `ERROR` and contributes nothing at all, and
    # `shielded_by` is the one field that says where to go and look. Every other node
    # here carries it as null, which is the shape a client meets everywhere else.
    tree.upsert("/network/vpn", StatusCode.ERROR, "the tunnel is down")
    tree.upsert("/services/cache", StatusCode.ERROR, "connect: no route to host")
    tree.set_dependency("/services/cache", "/network/vpn")
    # A pin: the one shape whose absence would have made this artifact's own
    # description false, and which nothing above produces on its own.
    tree.set_maintenance("/services/db", "waiting on the vendor",
                         expires_at=datetime(2027, 1, 1, tzinfo=UTC),
                         set_by="lex")


def envelope_from(tree: StatusTree) -> dict:
    app_module.app.config["TESTING"] = True
    app_module.status_tree = tree
    app_module.api_tokens = {"tester": TOKEN}
    client = app_module.app.test_client()
    answer = client.get("/status", headers=JSON_HEADERS)
    assert answer.status_code == 200, answer.status_code
    body: dict = answer.get_json()
    return body


def artifact_path() -> Path:
    return Path(__file__).resolve().parents[1] / "src" / "little_sister" / \
        "contract" / contract.ARTIFACT


class GoldenEnvelopeTests(TestCase):
    def setUp(self):
        self.tree = StatusTree()
        build_scene(self.tree)

    def test_the_api_still_answers_what_the_artifact_holds(self):
        """The one assertion that keeps the artifact honest: the shipped bytes are
        what this application produces, field for field, once the clock and the
        version are normalized away."""
        live = contract.normalize(envelope_from(self.tree), VOLATILE)
        held = contract.normalize(contract.golden_envelope(), VOLATILE)
        self.assertEqual(held, live)

    def test_the_artifact_names_its_own_volatile_fields(self):
        """A consumer in another language reads the list out of the file rather
        than keeping a copy of it — which is the copy that would drift."""
        self.assertEqual(contract.golden_artifact()["volatile"], VOLATILE)
        self.assertEqual(contract.golden_artifact()["schema_version"], 2)
        self.assertEqual(contract.golden_envelope()["schema_version"], 2)

    def test_it_carries_every_optional_shape_a_client_must_decode(self):
        """The scene is only worth shipping if it is not the easy case. Each of
        these is a field a hand-written fixture forgets."""
        envelope = contract.golden_envelope()
        nodes: list[dict] = []

        def walk(node: dict) -> None:
            nodes.append(node)
            for child in node["children"]:
                walk(child)
        walk(envelope["status"])
        self.assertIn("instance", envelope)
        self.assertTrue(any(node.get("run") for node in nodes))
        self.assertTrue(any("run" not in node for node in nodes))
        self.assertTrue(any(node["entries"]["addressable"] for node in nodes))
        self.assertTrue(any(not node["entries"]["addressable"]
                            and node["entries"]["items"] for node in nodes))
        self.assertTrue(any(node["report"] for node in nodes))
        self.assertTrue(any(node["show_when_quiet"] is not None
                            for node in nodes))
        items = [item for node in nodes for item in node["entries"]["items"]]
        self.assertTrue(any(item["subject"] and item["data"] for item in items))
        self.assertTrue(any(not item["subject"] and not item["data"]
                            for item in items))
        self.assertTrue(any(item["code"] for item in items))
        # The two shapes the client tests field by field, and which nothing in the
        # scene produces unless it is asked for.
        self.assertTrue(any(node.get("maintenance") for node in nodes))
        self.assertTrue(any(node["maintenance"] is None for node in nodes))
        runs = [node["run"] for node in nodes if node.get("run")]
        self.assertTrue(any(run.get("frequency_seconds") for run in runs))
        self.assertTrue(any(run.get("stale_after_seconds") for run in runs))
        self.assertTrue(any("frequency_seconds" not in run for run in runs))
        # The pin puts a `contribution` on its node, naming the rule that
        # transformed the code. Its `code` is null — the *withheld* shape. A real
        # code there is 2.2.0's addition and needs a damped node; when one joins
        # this scene, assert it here and the artifact is complete.
        rules = {node["contribution"]["by"]: node["contribution"]
                 for node in nodes if node["contribution"]}
        # Withheld, and transformed: 2.2.0's two shapes of one field.
        self.assertIsNone(rules["maintenance"]["code"])
        self.assertIsNotNone(rules["damping"]["code"])
        damped, = [node for node in nodes
                   if (node["contribution"] or {}).get("by") == "damping"]
        self.assertNotEqual(damped["code"], damped["contribution"]["code"])
        # The measurement at the run: the object named, and the record beside it.
        measured, = [node for node in nodes if node["record"]]
        self.assertTrue(measured["subject"])
        self.assertNotEqual(measured["subject"], measured["path"],
                            "the object is not the node's path")
        self.assertTrue(any(not node["subject"] and node["record"] is None
                            for node in nodes))
        # The shield: withheld like a pin, but on a node that still holds a ranked
        # reading of its own — which is what makes `shielded_by` a field and not a
        # thing a client could read off `code`.
        shielded, = [node for node in nodes if node["shielded_by"]]
        self.assertEqual(shielded["contribution"]["by"], "dependency")
        self.assertIsNone(shielded["contribution"]["code"])
        self.assertEqual(shielded["code"], "ERROR")
        self.assertTrue(any(node["shielded_by"] is None for node in nodes))
        # The typed keys of a record, at any depth.
        record, = [item["data"] for item in items if item["data"]]
        self.assertIn("at", record)
        self.assertIn("started", record["run"])
        self.assertIn("ended", record["run"])


def rewrite() -> None:
    tree = StatusTree()
    build_scene(tree)
    artifact = {
        "schema_version": 2,
        "volatile": VOLATILE,
        "envelope": contract.normalize(envelope_from(tree), VOLATILE),
    }
    artifact_path().write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {artifact_path()}")


if __name__ == "__main__":
    rewrite()
