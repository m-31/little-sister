"""A branch's period is kept beside the log, in its entry (ADR-0132 decisions 1, 3 and
4, and the consequence on the kept file's entries).

* Every branch's entry keeps the period of what it shows under ``period`` — the root's
  and a container's too, which have an entry for it alone, their two codes
  ``UNDEFINED`` — and a leaf's keeps none: ``code``, then ``since`` and either
  ``before`` or ``was`` and ``cause``, then ``by``. A bound has no ``was``, ``cause``
  or ``by``; a difference a tick found that no change explains has ``was`` alone.
* A start takes them at their word, and each goes on from its entry until the units
  beneath it have run — also where staleness made it, which the entries cannot say; a
  takeover adopts the holder's. A file written before the key is seeded from its log
  (``test_branch_periods``).
* The release before reads such a file with its own code, taken from its tag, in every
  run of the suite: it refuses nothing, and holds what it holds of the same file
  without the periods.
"""
from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from datetime import timedelta
from pathlib import Path

from little_sister import instants
from little_sister.status import HEARTBEAT_PATH
from little_sister.tree import (
    CAUSE_READING,
    CAUSE_REMOVED,
    CAUSE_STALE,
    Beginning,
    Period,
    StatusTree,
    nodes_from_payload,
)
from tests.test_branch_periods import (
    ERROR,
    OK,
    T0,
    WARN,
    _Clocked,
    as_before_the_key,
)

#: The keys an entry of the release before carries, and the one it reads of them:
#: ``shows`` and ``reported`` it requires of every entry (ADR-0110 decision 2).
RELEASE_BEFORE_KEYS = {"shows", "reported", "publishes", "since", "before", "was",
                       "cause"}

#: The project's root, whose tags name the releases.
ROOT = Path(__file__).resolve().parents[1]


def _stamp(at):
    return instants.stamp(at)


class TheEntryKeepsThePeriodTests(_Clocked):
    """Decisions 1 and 4: the period in a key of its own, in the entry's words."""

    def _failed(self):
        with self.tree.storing("/ci"):
            self.tree.upsert("/ci/alpha", OK)
            self.tree.upsert("/ci/beta", OK)
        failed = self.advance(60)
        with self.tree.storing("/ci"):
            self.tree.upsert("/ci/alpha", ERROR, "failed")
            self.tree.upsert("/ci/beta", OK)
        return failed

    def test_a_branch_keeps_its_period_in_its_entry_and_a_leaf_none(self):
        failed = self._failed()
        nodes = self.tree.events_payload()["nodes"]
        self.assertEqual(nodes["/ci"], {
            "shows": "UNDEFINED", "reported": "UNDEFINED",
            "period": {"code": "ERROR", "since": _stamp(failed), "was": "OK",
                       "cause": "reading", "by": "/ci/alpha"}})
        self.assertNotIn("period", nodes["/ci/alpha"])
        # the root, whose entry is for it alone too
        self.assertEqual(nodes["/"]["period"]["code"], "ERROR")
        self.assertEqual(nodes["/"].keys(), {"shows", "reported", "period"})

    def test_beside_a_nodes_own_period_where_it_has_one(self):
        with self.tree.storing("/svc"):
            self.tree.upsert("/svc", OK, "the service")
            self.tree.upsert("/svc/web", OK)
        failed = self.advance(60)
        with self.tree.storing("/svc"):
            self.tree.upsert("/svc", OK, "the service")
            self.tree.upsert("/svc/web", ERROR, "down")
        entry = self.tree.events_payload()["nodes"]["/svc"]
        self.assertEqual((entry["shows"], entry["since"], entry["before"]),
                         ("OK", _stamp(T0), True))
        self.assertEqual(entry["period"], {
            "code": "ERROR", "since": _stamp(failed), "was": "OK",
            "cause": "reading", "by": "/svc/web"})

    def test_a_bound_names_no_one(self):
        with self.tree.storing("/ci"):
            self.tree.upsert("/ci/alpha", ERROR, "failed")
        self.assertEqual(self.tree.events_payload()["nodes"]["/ci"]["period"],
                         {"code": "ERROR", "since": _stamp(T0), "before": True})

    def test_a_reading_gone_stale_is_its_cause(self):
        with self.tree.storing("/s"):
            self.tree.upsert("/s/a", OK, stale_after=300.0)
            self.tree.upsert("/s/b", OK)
        self.tree.compare_periods(self.advance(600))
        self.assertEqual(self.tree.events_payload()["nodes"]["/s"]["period"], {
            "code": "WARN", "since": _stamp(T0 + timedelta(seconds=300)),
            "was": "OK", "cause": "stale", "by": "/s/a"})

    def test_a_difference_no_change_explains_has_was_alone(self):
        self._failed()
        self.tree._periods["/ci"] = Period(WARN, Beginning(T0, was=OK))
        tick = self.advance(5)
        with self.assertLogs("little_sister.logger", level="WARNING"):
            self.tree.compare_periods()
        self.assertEqual(self.tree.events_payload()["nodes"]["/ci"]["period"],
                         {"code": "ERROR", "since": _stamp(tick), "was": "WARN"})

    def test_a_branch_its_check_removed_keeps_undefined_since_its_removal(self):
        with self.tree.storing("/m"):
            self.tree.upsert("/m/g", OK, "a group")
            self.tree.upsert("/m/g/x", ERROR, "down")
            self.tree.upsert("/m/k", OK)
        removed = self.advance(60)
        with self.tree.storing("/m"):
            self.tree.upsert("/m/k", OK)
            self.tree.prune("/m", {"k"})
        entry = self.tree.events_payload()["nodes"]["/m/g"]
        self.assertEqual(entry["period"], {
            "code": "UNDEFINED", "since": _stamp(removed), "was": "ERROR",
            "cause": "removed", "by": "/m/g"})
        self.assertEqual((entry["shows"], entry["cause"]), ("UNDEFINED", "removed"))

    def test_what_is_written_is_what_comes_back(self):
        self.tree.set_dependency("/svc/cache", "/net/vpn")
        with self.tree.storing("/svc"):
            self.tree.upsert("/svc/web", OK)
            self.tree.upsert("/svc/cache", ERROR, "no route to host")
        self.tree.upsert("/net/vpn", OK)
        self.advance(60)
        with self.tree.storing("/net/vpn"):
            self.tree.upsert("/net/vpn", ERROR, "the tunnel is down")
        self._failed()
        kept = nodes_from_payload(json.loads(json.dumps(
            self.tree.events_payload())))
        assert kept is not None
        periods = {path: entry.period for path, entry in kept.items()
                   if entry.period is not None}
        self.assertEqual(periods, self.tree._periods)
        self.assertEqual(periods["/svc"].by, "/net/vpn")

    def test_a_period_of_another_shape_refuses_the_file(self):
        since = _stamp(T0)
        for shape in ("ERROR", {"since": since}, {"code": "RED", "since": since},
                      {"code": "ERROR"},
                      {"code": "ERROR", "since": since, "before": True, "by": "/x"},
                      {"code": "ERROR", "since": since, "before": True, "was": "OK"},
                      {"code": "ERROR", "since": since, "was": "OK", "by": 7},
                      {"code": "ERROR", "since": "2026-10-17T09:00:00",
                       "was": "OK"}):
            with self.subTest(shape=shape), self.assertRaises(ValueError):
                nodes_from_payload({"nodes": {"/b": {
                    "shows": "UNDEFINED", "reported": "UNDEFINED",
                    "period": shape}}})


class AStartGoesOnFromTheEntriesTests(_Clocked):
    """Decision 3: a start takes the kept periods at their word, and each goes on
    from its entry until the units beneath it have run."""

    def test_past_the_logs_reach_a_branch_says_the_first_nodes_since(self):
        # the plan's case, across a restart and past the log: red from one node,
        # then from another
        tree = StatusTree(event_log_size=4)
        with tree.storing("/p"):
            tree.upsert("/p/a", OK)
            tree.upsert("/p/b", OK)
        first = self.advance(600)
        with tree.storing("/p"):
            tree.upsert("/p/a", ERROR, "a broke")
            tree.upsert("/p/b", OK)
        self.advance(600)
        with tree.storing("/p"):
            tree.upsert("/p/a", OK)
            tree.upsert("/p/b", ERROR, "b broke")
        for index in range(6):
            self.advance(60)
            tree.upsert("/busy", ERROR if index % 2 else OK, f"reading {index}")
        self.assertFalse([event for event in tree.recent_events()
                          if event.path.startswith("/p")])
        new = self.restarted(tree=tree)
        self.assertEqual(self.said("/p", new),
                         (ERROR, first, False, OK, CAUSE_READING, "/p/a"))
        # a file written before the key could say a bound at its oldest row alone
        self.assertTrue(self.said("/p", self.restarted(
            tree=tree, before_the_key=True))[2])

    def test_a_period_staleness_made_goes_on_until_the_unit_beneath_has_run(self):
        with self.tree.storing("/b"):
            self.tree.upsert("/b/leaf", OK, stale_after=300.0)
            self.tree.upsert("/b/other", OK)
        went = T0 + timedelta(seconds=300)
        self.tree.compare_periods(self.advance(600))
        self.assertEqual(self.said("/b"),
                         (WARN, went, False, OK, CAUSE_STALE, "/b/leaf"))
        new = self.restarted()
        # the leaf counts at its entry, ok, and is not weighed stale: the entries
        # cannot say the period, and still it goes on, and no tick calls it missed
        with self.assertNoLogs("little_sister.logger", level="WARNING"):
            new.compare_periods(self.advance(60))
        self.assertEqual(self.said("/b", new)[:2], (WARN, went))
        # a first reading beneath it that moves nothing is not what ends it
        self.advance(60)
        with new.storing("/b/other"):
            new.upsert("/b/other", OK)
        self.assertEqual(self.said("/b", new)[:2], (WARN, went))
        # the leaf's own is
        read = self.advance(60)
        with new.storing("/b/leaf"):
            new.upsert("/b/leaf", OK, stale_after=300.0)
        self.assertEqual(self.said("/b", new),
                         (OK, read, False, WARN, CAUSE_READING, "/b/leaf"))

    def test_a_change_while_the_entries_carry_is_a_change(self):
        # orange from a node that still counts at its entry, and a sibling's first
        # reading turns it red: that reading began the period
        with self.tree.storing("/b"):
            self.tree.upsert("/b/x", WARN, "slow")
            self.tree.upsert("/b/y", OK)
        new = self.restarted()
        run = self.advance(60)
        with new.storing("/b/y"):
            new.upsert("/b/y", ERROR, "down")
        self.assertEqual(self.said("/b", new),
                         (ERROR, run, False, WARN, CAUSE_READING, "/b/y"))

    def test_a_file_written_before_the_key_adopted_leaves_this_processs(self):
        holder = StatusTree()
        with holder.storing("/b"):
            holder.upsert("/b/a", ERROR, "down")
        with self.tree.storing("/b"):
            self.tree.upsert("/b/a", OK)
        mine = self.period("/b")
        payload = json.loads(json.dumps(holder.events_payload()))
        payload["nodes"] = as_before_the_key(payload["nodes"])
        self.tree.adopt_events(payload)
        self.assertEqual(self.period("/b"), mine)


def _version(text):
    """The leading numbers of a version, ``0.3.22`` of ``v0.3.22`` or ``0.3.22.dev0``;
    ``None`` where it starts with none."""
    found = re.match(r"v?(\d+(?:\.\d+)*)", text)
    return None if found is None else tuple(int(part)
                                            for part in found.group(1).split("."))


class TheReleaseBeforeReadsTheFileTests(_Clocked):
    """The kept file's consequence: a release before reads the keys it knows and
    passes over ``period``, so a rollback restores the file. Proven with that
    release's own code, taken from its tag, in every run."""

    def _kept_file(self):
        """A file this release writes, with every entry that could trip a reader that
        does not know ``period``: one it writes itself, its own period's beginning
        beside the branch's; one that publishes while it waits; the root's and a
        container's, of two ``UNDEFINED`` codes, which it writes none of; a removed
        branch's; and the stop's stamp. The periods take every shape beside them."""
        tree = self.tree
        tree.set_process_branch(HEARTBEAT_PATH)
        tree.set_dependency("/svc/cache", "/net/vpn")
        with tree.storing("/svc"):
            tree.upsert("/svc", OK, "the service")
            tree.upsert("/svc/web", OK)
            tree.upsert("/svc/cache", ERROR, "no route to host")
        with tree.storing("/net/vpn"):
            tree.upsert("/net/vpn", OK)
        with tree.storing("/w"):
            tree.upsert("/w/x", OK, escalate_after=3)
            tree.upsert("/w/y", OK)
        with tree.storing("/m"):
            tree.upsert("/m/g", OK, "a group")
            tree.upsert("/m/g/x", ERROR, "down")
            tree.upsert("/m/k", OK)
        with tree.storing("/s"):
            tree.upsert("/s/a", OK, stale_after=300.0)
            tree.upsert("/s/b", OK)
        self.advance(60)
        with tree.storing("/w"):
            tree.upsert("/w/x", ERROR, "down", escalate_after=3)
            tree.upsert("/w/y", OK)
        with tree.storing("/net/vpn"):
            tree.upsert("/net/vpn", ERROR, "the tunnel is down")
        with tree.storing("/m"):
            tree.upsert("/m/k", OK)
            tree.prune("/m", {"k"})
        tree.compare_periods(self.advance(600))
        tree._periods["/w"] = Period(OK, Beginning(self.wall, was=WARN))
        with tree.storing(HEARTBEAT_PATH):
            tree.upsert(HEARTBEAT_PATH, OK)
            tree.upsert(f"{HEARTBEAT_PATH}/engine", OK)
        tree.note_stop(self.advance(1))
        payload = json.loads(json.dumps(tree.events_payload()))
        nodes = payload["nodes"]
        # what the file must hold for the proof to be one
        self.assertEqual(nodes["/"].keys(), {"shows", "reported", "period"})
        self.assertEqual(nodes["/net"].keys(), {"shows", "reported", "period"})
        self.assertIn("since", nodes["/svc"])
        self.assertIn("period", nodes["/svc"])
        self.assertIn("publishes", nodes["/w/x"])
        self.assertEqual(nodes["/m/g"]["period"]["cause"], CAUSE_REMOVED)
        self.assertEqual(nodes["/s"]["period"]["cause"], CAUSE_STALE)
        self.assertEqual(nodes["/svc"]["period"]["by"], "/net/vpn")
        self.assertNotIn("cause", nodes["/w"]["period"])
        self.assertIn("stopped_at", payload)
        return payload

    def _release_before(self):
        """The release before's ``src``, extracted from its tag: the highest ``v*``
        tag below the version this checkout says it is — release tags sit on main's
        release commits, which this branch need not contain, so no ``describe``.
        Skips only where it cannot look: without ``.git``, or without such a tag."""
        if not (ROOT / ".git").exists():
            self.skipTest("no .git here, so no tag to read the release before from")
        version = _version(tomllib.loads((ROOT / "pyproject.toml").read_text(
            encoding="utf-8"))["project"]["version"])
        tags = subprocess.run(
            ["git", "--no-optional-locks", "-C", str(ROOT), "tag", "--list", "v*",
             "--sort=-v:refname"],
            capture_output=True, text=True, check=True).stdout.split()
        before = next((tag for tag in tags if (_version(tag) or ()) < version), None)
        if before is None:
            self.skipTest(f"no release tag below {version}")
        archive = subprocess.run(
            ["git", "--no-optional-locks", "-C", str(ROOT), "archive",
             "--format=tar", before, "src/little_sister"],
            capture_output=True, check=True).stdout
        work = Path(tempfile.mkdtemp(prefix="release-before-"))
        self.addCleanup(shutil.rmtree, work)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            if hasattr(tarfile, "data_filter"):
                tar.extractall(work, filter="data")
            else:  # pragma: no cover - a 3.11 before 3.11.4
                tar.extractall(work)
        return work, before

    def test_every_entry_carries_the_keys_the_release_before_requires(self):
        for path, entry in self._kept_file()["nodes"].items():
            with self.subTest(path=path):
                self.assertLessEqual({"shows", "reported"}, entry.keys())
                self.assertLessEqual(entry.keys() - RELEASE_BEFORE_KEYS, {"period"})
                if "period" in entry:
                    self.assertIsInstance(entry["period"], dict)

    def test_the_release_before_restores_a_file_this_release_wrote(self):
        work, before = self._release_before()
        payload = self._kept_file()
        theirs = dict(payload, nodes=as_before_the_key(payload["nodes"]))
        broken = json.loads(json.dumps(payload))
        broken["nodes"]["/"] = {"period": broken["nodes"]["/"]["period"]}
        names = []
        for label, content in (("ours", payload), ("theirs", theirs),
                               ("broken", broken)):
            name = work / f"{label}.json"
            name.write_text(json.dumps(content), encoding="utf-8")
            names.append(str(name))
        done = subprocess.run(
            [sys.executable, "-I", "-S",
             str(Path(__file__).with_name("release_before_reader.py")),
             str(work / "src"), (self.wall + timedelta(minutes=5)).isoformat(),
             *names],
            capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        held = json.loads(done.stdout)
        ours, theirs_held, broken_held = (held[name] for name in names)
        self.assertNotIn("refused", ours, f"{before} refused the file")
        # it holds what it holds of the same file without the periods ...
        self.assertEqual(ours["payload"], theirs_held["payload"])
        for path in sorted(ours["history"].keys() | theirs_held["history"].keys()):
            with self.subTest(path=path):
                self.assertEqual(ours["history"].get(path, []),
                                 theirs_held["history"].get(path, []))
        # ... and does read the entries: one without its two codes is refused
        self.assertIn("refused", broken_held)

