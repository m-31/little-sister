"""The golden envelope is what this API actually answers, and so is the golden
answer of the series read.

`little_sister.contract` ships one envelope in the wheel and the family shares it
with the macOS client, so that the two repositories test **one** artifact rather
than each maintaining its own hand-written JSON — the drift that entry existed to
end. An artifact nobody holds to the code is a fixture that quietly stops being
true, so this builds the scene the artifact was made from, asks the real API for it,
and compares. The series read's artifact (ADR-0122 decision 9) is made and held the
same way, from a scene of its own whose instants are fixed.

Run ``python tests/test_contract_fixture.py`` to rewrite both artifacts after a
deliberate change to either answer; the diff it produces is the review.
"""
import json
import os
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest import TestCase, mock

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister import contract
from little_sister.checks.base import Check, CheckResult, Measurement
from little_sister.checks.file import FileFreshnessCheck
from little_sister.checks.ssh import HostMetricsCheck
from little_sister.engine import Engine
from little_sister.reasons import Entry
from little_sister.series import MemoryStore, SeriesKey, SeriesRecord
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
        # **A refused record** (2.6.0): the line stands as its grading wrote it,
        # its record is null, and `refused` says why — the one shape of the field
        # that is not null.
        Entry("1001-workflow-9-main", "acme/api (main) / Deploy: passed (#12)",
              code=StatusCode.OK, subject="1001",
              refused="it is 2,811 bytes and the limit is 2,048"),
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
    # The envelope a server with no engine answers (`disabled`): this suite imports
    # the application and never starts it (ADR-0091), and the artifact is not about
    # that.
    with mock.patch.object(app_module, "engine_error", None):
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
        # 2.6.0's `refused`: a line whose record the seam refused carries a null
        # record and the reason beside it, and every other line carries null.
        refused, = [item for item in items if item["refused"]]
        self.assertIsNone(refused["data"])
        self.assertTrue(refused["subject"])
        self.assertTrue(any(item["refused"] is None for item in items))
        # The typed keys of a record, at any depth.
        record, = [item["data"] for item in items if item["data"]]
        self.assertIn("at", record)
        self.assertIn("started", record["run"])
        self.assertIn("ended", record["run"])


#: The request the series artifact answers: the root, over an hour of the scene.
SERIES_REQUEST = "/series?from=2026-09-26T15:00:00Z&to=2026-09-26T16:00:00Z"

#: What differs between two correct runs of it. Every instant a reading carries is
#: fixed by the scene, and so is the window, so this is the clock the request was
#: read by and the version that answered — and nothing a reader decodes.
SERIES_VOLATILE = ["generated_at", "version"]

#: The scene's first instant. A Saturday, like every date the artifact holds.
T0 = datetime(2026, 9, 26, 15, 0, tzinfo=UTC)


class _Jobs(Check):
    """Carries the scene's series of runs. It is never run: it is here for what the
    engine reads off a check — its type, its mount, its measures and whether it
    keeps a series."""

    type_name = "jobs"

    def measure(self) -> Sequence[Measurement]:
        raise NotImplementedError("the scene writes its readings into the store")

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        raise NotImplementedError("the scene writes its nodes into the tree")


def _host(minutes: int, *, failed: bool = False) -> SeriesRecord:
    """One reading of the scene's host: its memory, its load and its two volumes —
    or, ``failed``, the reading that did not answer."""
    if failed:
        return SeriesRecord(
            {"exit_code": 255,
             "error": "ssh to alpha.example failed (exit 255): refused",
             "mem_pct": None, "cpu_pct": None, "load1": None,
             "load1_per_core": None, "ncpu": None, "disk_pct": None},
            T0 + timedelta(minutes=minutes), code=StatusCode.ERROR,
            texts=("ssh to alpha.example failed (exit 255): refused",))
    return SeriesRecord(
        {"exit_code": 0, "mem_pct": 62 + minutes, "cpu_pct": 11, "load1": 0.4,
         "ncpu": 4, "load1_per_core": 0.1, "disk_pct": 51,
         "volumes": {"root": {"path": "/", "pct": 51},
                     "data": {"path": "/data", "pct": 72}},
         "os": "Linux", "hostname": "alpha"},
        T0 + timedelta(minutes=minutes), code=StatusCode.OK,
        # a reading placed on a node keeps that node's lines
        texts=("memory fine", "disk fine"))


def _run(number: int, ended: datetime, seconds: int, observed: datetime,
         code: StatusCode | None, text: str = "") -> SeriesRecord:
    """One run of the scene's job: an event with a time of its own, read later."""
    started = ended - timedelta(seconds=seconds)
    stamp = "%Y-%m-%dT%H:%M:%SZ"
    return SeriesRecord(
        {"job": "import", "run": number, "seconds": seconds,
         "started": started.strftime(stamp), "ended": ended.strftime(stamp),
         # the record's own time, which is where the series places it
         "at": ended.strftime(stamp)},
        observed, identity=f"import-{number}", code=code,
        texts=(text,) if text else ())


def build_series_scene(tree: StatusTree, directory: Path) -> Engine:
    """One tree, and what its checks keep, carrying every shape the series read
    has (ADR-0122 decision 9).

    Every line below is here for a shape: a reader who deletes one deletes a shape
    the artifact no longer holds. Nothing is run — the readings are written into the
    store the engine reads, at instants this scene fixes, and the nodes into the
    tree as the newest run left them.
    """
    script = directory / "metrics.sh"
    script.write_text("echo hi\n")
    # A series on its check's own node, with measures on other nodes: the type
    # declares one for every volume a reading counts, and this host has two.
    host = HostMetricsCheck.from_config(
        {"type": "host-metrics", "path": "/hosts/alpha", "host": "alpha.example",
         "script": "metrics.sh", "frequency": "2m", "series_keep": 720}, directory)
    # A series that declares no measure: what it keeps is a time.
    beat = FileFreshnessCheck.from_config(
        {"type": "file", "path": "/hosts/alpha/beat", "file": "/var/run/beat",
         "max_age": "5m", "frequency": "3m", "series_keep": 480}, directory)
    # A check that keeps its own state and a run of each job name, and declares one
    # measure for all of them, with no end to its axis.
    jobs = _Jobs(path="/batch", subject="queue/live", series_keep=30,
                 measure_defaults={"seconds": {"unit": "s", "label": "Run time"}})
    store = MemoryStore()
    # Gauges: a reading every two minutes, and one of them failed.
    for minutes, failed in ((0, False), (2, True), (4, False)):
        store.add(SeriesKey("host-metrics", "/hosts/alpha", "alpha.example"),
                  _host(minutes, failed=failed), keep=720)
    for minutes in (1, 4):
        store.add(SeriesKey("file", "/hosts/alpha/beat", "/var/run/beat"),
                  SeriesRecord({"modified": {"at": "2026-09-26T14:59:30Z"}},
                               T0 + timedelta(minutes=minutes),
                               code=StatusCode.OK, texts=("fresh",)), keep=480)
    # A state: read twice and unchanged, so one reading, from when it began.
    for minutes in (0, 30):
        store.add(SeriesKey("jobs", "/batch", "queue/live"),
                  SeriesRecord({"jobs": 2}, T0 + timedelta(minutes=minutes),
                               state="open", code=StatusCode.OK,
                               texts=("2 job names in the queue",)), keep=30)
    # Runs, each at its own time and read after it: one that passed, one that
    # failed, and one without a verdict — no line carried it, so it kept neither a
    # code nor a sentence, and an absence is not an `OK`.
    imports = SeriesKey("jobs", "/batch", "job/import")
    store.add(imports, _run(41, T0 + timedelta(minutes=6, seconds=1), 61,
                            T0 + timedelta(minutes=8), StatusCode.OK,
                            "import #41: succeeded in 1m 1s"), keep=30)
    store.add(imports, _run(42, T0 + timedelta(minutes=20, seconds=7), 7,
                            T0 + timedelta(minutes=22), StatusCode.ERROR,
                            "import #42: failed after 7 s"), keep=30)
    store.add(imports, _run(43, T0 + timedelta(minutes=40), 58,
                            T0 + timedelta(minutes=42), None), keep=30)
    # A series with no reading in the window: its one run ended two hours before
    # it. No node stands for its subject either, so it is shown on its check's.
    store.add(SeriesKey("jobs", "/batch", "job/export"),
              SeriesRecord({"job": "export", "run": 7, "seconds": 12,
                            "at": "2026-09-26T13:00:12Z"},
                           T0 - timedelta(minutes=118), identity="export-7",
                           code=StatusCode.OK, texts=("export #7: succeeded",)),
              keep=30)
    tree.upsert("/hosts/alpha", StatusCode.OK, ["memory fine", "disk fine"],
                frequency_seconds=120, subject="alpha.example")
    tree.upsert("/hosts/alpha/beat", StatusCode.OK, "fresh",
                frequency_seconds=180, subject="/var/run/beat")
    tree.upsert("/batch", StatusCode.OK, "2 job names in the queue",
                frequency_seconds=300, subject="queue/live")
    # The node that stands for a subject: its lines name that subject and no other
    # (ADR-0106 decision 2), so the subject's series is shown on it.
    tree.upsert("/batch/import", StatusCode.ERROR, [
        Entry("import", "import #42: failed after 7 s", code=StatusCode.ERROR,
              subject="job/import", data={"job": "import", "run": 42})],
        members=True)
    return Engine([host, beat, jobs], tree, series=store)


def series_from(tree: StatusTree, engine: Engine,
                request: str = SERIES_REQUEST) -> dict:
    """What the series read answers ``request`` over the scene."""
    app_module.app.config["TESTING"] = True
    saved = (app_module.status_tree, app_module.engine, app_module.api_tokens)
    app_module.status_tree, app_module.engine = tree, engine
    app_module.api_tokens = {"tester": TOKEN}
    try:
        answer = app_module.app.test_client().get(request, headers=JSON_HEADERS)
    finally:
        (app_module.status_tree, app_module.engine,
         app_module.api_tokens) = saved
    assert answer.status_code == 200, answer.status_code
    body: dict = answer.get_json()
    return body


def series_artifact_path() -> Path:
    return artifact_path().with_name(contract.SERIES_ARTIFACT)


class GoldenSeriesTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.tree = StatusTree()
        self.engine = build_series_scene(self.tree, Path(self.directory.name))

    def test_the_api_still_answers_what_the_artifact_holds(self):
        """The shipped bytes are what this application answers the artifact's own
        request, field for field, once the clock and the version are normalized
        away."""
        asked = contract.golden_series_artifact()["request"]
        live = contract.normalize(series_from(self.tree, self.engine, asked),
                                  SERIES_VOLATILE)
        held = contract.normalize(contract.golden_series(), SERIES_VOLATILE)
        self.assertEqual(held, live)

    def test_the_artifact_names_what_was_asked_and_its_own_volatile_fields(self):
        artifact = contract.golden_series_artifact()
        self.assertEqual(set(artifact),
                         {"schema_version", "volatile", "request", "answer"})
        self.assertEqual(artifact["request"], SERIES_REQUEST)
        self.assertEqual(artifact["volatile"], SERIES_VOLATILE)
        self.assertEqual(artifact["schema_version"], 2)
        self.assertEqual(contract.golden_series()["schema_version"], 2)

    def test_every_time_a_reading_carries_is_a_value_a_reader_decodes(self):
        """The scene fixes every instant, so nothing a reading carries is blanked:
        only the clock the request was read by and the version that answered are."""
        answer = contract.golden_series()
        self.assertEqual(answer["generated_at"], "<volatile>")
        self.assertEqual(answer["instance"]["version"], "<volatile>")
        self.assertEqual(answer["window"], {"from": "2026-09-26T15:00:00Z",
                                            "to": "2026-09-26T16:00:00Z"})
        readings = [reading for series in answer["series"]
                    for reading in series["readings"]]
        self.assertTrue(readings)
        for reading in readings:
            for name in ("at", "observed_at"):
                self.assertEqual(datetime.fromisoformat(reading[name]).tzinfo, UTC,
                                 reading)
        self.assertNotIn("<volatile>", json.dumps(answer["series"]))

    def test_it_carries_every_shape_a_reader_must_decode(self):
        """ADR-0122 decision 9's list, one assertion a shape."""
        answer = contract.golden_series()
        self.assertEqual(answer["path"], "/")
        series: list[dict[str, Any]] = answer["series"]
        by_subject = {one["key"]["subject"]: one for one in series}
        self.assertEqual(len(by_subject), len(series))
        # a series on its check's node, and one on its subject's
        self.assertEqual(by_subject["queue/live"]["node"], "/batch")
        self.assertEqual(by_subject["queue/live"]["key"]["mount"], "/batch")
        self.assertEqual(by_subject["job/import"]["node"], "/batch/import")
        self.assertEqual(by_subject["job/import"]["key"]["mount"], "/batch")
        # a measure a `*` expanded — one for each key, each on its own node — and
        # one with no `axis_to`
        measures = {measure["field"]: measure
                    for measure in by_subject["alpha.example"]["measures"]}
        self.assertEqual(
            {field: measure["node"] for field, measure in measures.items()
             if field.startswith("volumes.")},
            {"volumes.root.pct": "/hosts/alpha/disk/root",
             "volumes.data.pct": "/hosts/alpha/disk/data"})
        self.assertEqual(measures["volumes.root.pct"]["axis_to"], 100)
        self.assertEqual(measures["volumes.root.pct"]["label"],
                         "Disk space used on root")
        self.assertIsNone(measures["load1_per_core"]["axis_to"])
        self.assertFalse(any("*" in json.dumps(one["measures"]) for one in series))
        # a series without measures
        self.assertEqual(by_subject["/var/run/beat"]["measures"], [])
        self.assertTrue(by_subject["/var/run/beat"]["readings"])
        # a reading that failed, and one placed on a node with that node's lines
        ok, failed, _ = by_subject["alpha.example"]["readings"]
        self.assertEqual((failed["code"], failed["record"]["mem_pct"]),
                         ("ERROR", None))
        self.assertTrue(failed["record"]["error"])
        self.assertEqual(ok["texts"], ["memory fine", "disk fine"])
        # a run with its own time, read later; the typed keys of its record
        passed, broke, unjudged = by_subject["job/import"]["readings"]
        self.assertEqual((passed["at"], passed["observed_at"]),
                         ("2026-09-26T15:06:01Z", "2026-09-26T15:08:00Z"))
        self.assertEqual(passed["identity"], "import-41")
        self.assertEqual({name: passed["record"][name]
                          for name in ("at", "started", "ended")},
                         {"at": "2026-09-26T15:06:01Z",
                          "started": "2026-09-26T15:05:00Z",
                          "ended": "2026-09-26T15:06:01Z"})
        self.assertEqual((broke["code"], broke["identity"]), ("ERROR", "import-42"))
        # a run without a verdict: no code, no sentence — and not an `OK`
        self.assertIsNone(unjudged["code"])
        self.assertEqual(unjudged["texts"], [])
        self.assertEqual(unjudged["identity"], "import-43")
        # a state: one reading from when it began, last read later
        state, = by_subject["queue/live"]["readings"]
        self.assertEqual((state["state"], state["identity"]), ("open", ""))
        self.assertEqual((state["at"], state["observed_at"]),
                         ("2026-09-26T15:00:00Z", "2026-09-26T15:30:00Z"))
        # a series with no reading in the window keeps its place
        self.assertEqual(by_subject["job/export"]["readings"], [])
        self.assertEqual(by_subject["job/export"]["node"], "/batch")
        # a gauge names neither an identity nor a state
        self.assertEqual((ok["identity"], ok["state"]), ("", ""))
        # and the order: the tree's, then the key's where two stand on one node
        self.assertEqual(
            [one["key"]["subject"] for one in series],
            ["job/export", "queue/live", "job/import", "alpha.example",
             "/var/run/beat"])


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
    with tempfile.TemporaryDirectory() as directory:
        tree = StatusTree()
        engine = build_series_scene(tree, Path(directory))
        answer = series_from(tree, engine)
    series = {
        "schema_version": 2,
        "volatile": SERIES_VOLATILE,
        "request": SERIES_REQUEST,
        "answer": contract.normalize(answer, SERIES_VOLATILE),
    }
    series_artifact_path().write_text(
        json.dumps(series, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {series_artifact_path()}")


if __name__ == "__main__":
    rewrite()
