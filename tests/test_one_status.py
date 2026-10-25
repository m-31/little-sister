"""A node says one status wherever it is read (ADR-0123), read against the record's
sentences.

The estate is one check that reads an account's pipelines, in the shape
`little-sister-aws` hands them back in: a root that declares nothing and says its
scope, an account that declares `OK`, an aspect whose one line is its scope, coded
`OK`, and beneath it a node for every pipeline, named by the run. Every pipeline
passes on the first run and one fails on the second, so the aspect and the account
are each a node whose check passes over a node beneath it that fails. The engine runs
the check, so what a surface reads is what two runs leave.

Every surface that draws the aspect is read: its own page at each depth and in the
part its refresh asks for, the pages above it, and the API's read of its path. The
pages are read as trees (`tests/page_tree.py`), since which element says a word is
the claim.

A node's periods stay those of its own status, and no row is written for a node
when one beneath it changes (decision 4). So the second half reads the surfaces that
state a period — the Time card, History and the node's Copy document — for whose
they say it is (decision 3), and the line on a branch's Time card that names the node
beneath it that makes what it shows, with that node's own *since*: for that, nodes
are written beside the estate on a clock the test moves by hand.
"""
from __future__ import annotations

import os
import re
import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest import TestCase, mock

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister import instants
from little_sister.checks.base import Check, CheckResult, Measurement
from little_sister.engine import Engine
from little_sister.reasons import Entry
from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from tests.page_tree import Element, parse

TOKEN = "one-status-token"
INSTANT = r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d"
#: What History says under the table of a node above others.
OWN_PERIODS = ("The periods of its own status: its page heads with what it rolls up "
               "to, the nodes beneath it included.")
#: What it says under the table above that one, of what the node shows (ADR-0132
#: decision 6).
SHOWN_PERIODS = ("The periods of what it shows: what it rolls up to, the nodes "
                 "beneath it included.")
JSON = {"Accept": "application/json", "Authorization": f"Bearer {TOKEN}"}

ACCOUNT = "/cloud/aws/staging"
ASPECT = f"{ACCOUNT}/codepipeline"
PIPELINES = ("build-site", "deploy-site", "load-fixtures")
FAILS = "load-fixtures"
SCOPE = "3 pipelines in scope (eu-central-1)"


class _Pipelines(Check):
    """Reads one account's pipelines. The first run finds them all succeeded, and
    every later one finds ``FAILS`` failed — until ``mended`` says otherwise."""

    type_name = "pipelines"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.runs = 0
        self.mended = False

    def measure(self) -> Sequence[Measurement]:
        self.runs += 1
        failed = self.runs > 1 and not self.mended
        return [Measurement(record={
            "name": name,
            "status": "Failed" if failed and name == FAILS else "Succeeded"})
            for name in PIPELINES]

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        def pipeline(reading: Measurement) -> CheckResult:
            status = str(reading.record["status"])
            return CheckResult(
                name=str(reading.record["name"]), dynamic=True,
                reason=[Entry("pipeline", f"last execution {status}",
                              code=(StatusCode.ERROR if status == "Failed"
                                    else StatusCode.OK))])

        aspect = CheckResult(
            name="codepipeline",
            reason=[Entry("scope", SCOPE, code=StatusCode.OK)],
            children=tuple(pipeline(reading) for reading in measurements),
            children_complete=True)
        account = CheckResult(StatusCode.OK, [], name="staging",
                              children=(aspect,), dynamic=True)
        return CheckResult(StatusCode.UNDEFINED,
                           ["1 account, 1 account/region pair in scope"],
                           children=(account,))


def _branch(path: str) -> str:
    return path.lstrip("/")


def _drawn(page: Element, path: str) -> Element:
    """The card, the box or the head a page draws for the node at ``path``: the
    element that carries the node's color, around the line that names it."""
    named = [element for element in page.walk()
             if element.attrs.get("data-path") == path
             and (element.has("status-card__head") or element.has("status-node__self"))]
    assert len(named) == 1, f"{len(named)} elements draw {path}, wanted one"
    box = named[0].parent
    assert box is not None and (box.has("status-card") or box.has("status-node"))
    return box


def _color(box: Element) -> str:
    """The status a card, a box or a head is colored by: its one `s-` class."""
    colors = [name[2:] for name in box.attrs["class"].split()
              if name.startswith("s-")]
    assert len(colors) == 1, box.attrs["class"]
    return colors[0]


def _word(box: Element) -> str:
    """The status word a card, a box or a head says beside its name, in its state
    cluster: the cluster's own text — a card's in the part that holds its cue and
    word, `.status-word` — without the time and the marks it also holds."""
    line = box.first()
    states = [element for element in line.walk()
              if element.has("status-card__state") or element.has("status-node__state")
              or element.has("viewed-head__state")]
    assert len(states) == 1, f"{len(states)} state clusters in {box!r}"
    holders = [states[0], *(child for child in states[0].children
                            if isinstance(child, Element) and child.has("status-word"))]
    said = [child.strip() for holder in holders for child in holder.children
            if isinstance(child, str) and child.strip()]
    assert len(said) == 1, said
    return said[0]


def _cue(box: Element) -> str:
    """The shape cue beside the name: the first in the line that names the node."""
    cues = [element for element in box.first().walk() if element.has("status-cue")]
    assert cues, f"no cue in {box!r}"
    kinds = [name.removeprefix("status-cue--")
             for name in cues[0].attrs["class"].split()
             if name.startswith("status-cue--")]
    assert len(kinds) == 1, cues[0].attrs["class"]
    return kinds[0]


class _Estate(TestCase):
    """The estate after two runs, read by an admin."""

    def setUp(self) -> None:
        self._saved = (app_module.status_tree, app_module.engine,
                       app_module.api_tokens)
        self.addCleanup(self._restore)
        app_module.app.config["TESTING"] = True
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        app_module.api_tokens = {"tester": TOKEN}
        self.check = _Pipelines(path="/cloud/aws")
        app_module.engine = Engine([self.check], self.tree)
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})
        app_module.engine.run_once()
        app_module.engine.run_once()

    def _restore(self) -> None:
        (app_module.status_tree, app_module.engine,
         app_module.api_tokens) = self._saved

    def _get(self, url: str, **headers: str) -> str:
        response = self.client.get(url, headers=headers)
        self.assertEqual(response.status_code, 200, url)
        return response.get_data(as_text=True)

    def _page(self, url: str) -> Element:
        return parse(self._get(url))

    def _head(self, path: str, query: str = "depth=1") -> Element:
        return self._page(f"/status/{_branch(path)}?{query}").one("viewed-head")


    def _time_card_body(self, path: str, query: str = "depth=1") -> Element:
        """The node's Time card."""
        page = self._page(f"/status/{_branch(path)}?{query}")
        cards = [card for card in page.all("card-body")
                 if card.all(tag="h3") and card.all(tag="h3")[0].text() == "Time"]
        self.assertEqual(len(cards), 1, f"{len(cards)} Time cards on {path}")
        return cards[0]

    def _time_card(self, path: str, query: str = "depth=1") -> list[str]:
        """The sentences of the node's Time card, in the card's order."""
        return [line.text() for line in self._time_card_body(path, query).all(tag="p")]

    def _period_said(self, path: str) -> str:
        """The period of its own status its Time card states of a node, in the
        card's words and without whose it is: *error since …*, and what kind of
        beginning it had. On a node above others that is the line *Its own status
        …*, beneath the period of what it shows (ADR-0132 decision 5); on a leaf, and
        on a node whose pin cancels what is beneath it, its one line."""
        lines = self._time_card(path)
        own = [match.group(1) for line in lines
               if (match := re.match(r"Its own status ([a-z]+ since .+)$", line))]
        said = own or [match.group(1) for line in lines
                       if (match := re.match(r"Status ([a-z]+ since .+)$", line))]
        self.assertEqual(len(said), 1, said)
        return said[0]

    def _copy(self, path: str) -> list[str]:
        """The node's Copy document, as its page hands it over: its lines."""
        page = self._page(f"/copy/{_branch(path)}")
        return page.all(tag="textarea")[0].source().splitlines()

    def _history_says(self, path: str) -> list[str]:
        """What the node's History page says in sentences beneath its tables."""
        page = self._page(f"/history/{_branch(path)}")
        return [line.text() for line in page.all("text-muted", tag="p")]


class OneStatusTests(_Estate):
    """What a node rolls up to is the status every surface says of it."""

    def test_the_check_passes_over_a_node_that_fails(self) -> None:
        # the premise: of its own each node is well, and the tree rolls it up red
        for path in (ASPECT, ACCOUNT):
            with self.subTest(path=path):
                shot = self.tree.snapshot(path)
                assert shot is not None
                self.assertIs(shot.own_code, StatusCode.OK)
                self.assertIs(shot.code, StatusCode.ERROR)
        failing = self.tree.snapshot(f"{ASPECT}/{FAILS}")
        assert failing is not None
        self.assertIs(failing.code, StatusCode.ERROR)

    def test_the_head_of_its_page_says_what_it_rolls_up_to(self) -> None:
        # from depth 1 the node heads its page, and in the part the refresh asks for
        for path in (ASPECT, ACCOUNT):
            for query in ("depth=1", "depth=2", "depth=1&fragment=1"):
                with self.subTest(path=path, query=query):
                    head = self._head(path, query)
                    self.assertEqual(
                        (_color(head), _cue(head), _word(head)),
                        ("error", "error", "error"))

    def test_its_one_card_at_depth_zero_says_it(self) -> None:
        card = _drawn(self._page(f"/status/{_branch(ASPECT)}?depth=0"), ASPECT)
        self.assertTrue(card.has("status-card"))
        self.assertEqual((_color(card), _word(card)), ("error", "error"))

    def test_its_box_on_the_pages_above_says_it(self) -> None:
        # a card on its parent's page, a box inside a card one page further up
        for url, kind in ((f"/status/{_branch(ACCOUNT)}?depth=1", "status-card"),
                          ("/status/cloud/aws?depth=2", "status-node")):
            with self.subTest(url=url):
                box = _drawn(self._page(url), ASPECT)
                self.assertTrue(box.has(kind))
                self.assertEqual((_color(box), _word(box)), ("error", "error"))

    def test_the_api_says_it_and_names_the_two_beside_it(self) -> None:
        answer = self.client.get(f"/status/{_branch(ASPECT)}", headers=JSON)
        self.assertEqual(answer.status_code, 200)
        status = answer.get_json()["status"]
        self.assertEqual(
            {key: status[key] for key in ("code", "own", "reported")},
            {"code": "ERROR", "own": "OK", "reported": "OK"})

    def test_every_surface_says_one_status(self) -> None:
        # decision 1 as one sentence: the node's page, the API's read of its path
        # and its box on the pages above say one status, the worst of what stands
        # beneath it
        branch = _branch(ASPECT)
        said = {
            "the head of its page": _word(self._head(ASPECT)),
            "the head in the refresh": _word(self._head(ASPECT, "depth=1&fragment=1")),
            "its card at depth 0": _word(_drawn(
                self._page(f"/status/{branch}?depth=0"), ASPECT)),
            "its card on the page above": _word(_drawn(
                self._page(f"/status/{_branch(ACCOUNT)}?depth=1"), ASPECT)),
            "its box two pages up": _word(_drawn(
                self._page("/status/cloud/aws?depth=2"), ASPECT)),
            "the API": self.client.get(
                f"/status/{branch}", headers=JSON).get_json()["status"]["code"].lower(),
            # and wherever a surface says *Status* beside a period, it is that one
            "its Time card": self._status_said(self._time_card(ASPECT)),
            "its Time card in the refresh": self._status_said(
                self._time_card(ASPECT, "depth=1&fragment=1")),
            "its Time card at depth 0": self._status_said(
                self._time_card(ASPECT, "depth=0")),
            "its Copy document": self._status_said(
                [line.removeprefix("- ").replace("**", "")
                 for line in self._copy(ASPECT)
                 if line.startswith(("- **Status", "- **Shown as:"))]),
        }
        self.assertEqual(set(said.values()), {"error"}, said)

    def _status_said(self, sentences: Sequence[str]) -> str:
        """The one status a surface states as the node's, in the sentences that
        say *Status …* or *Shown as: …*."""
        said = {match.group(1) for sentence in sentences
                if (match := re.match(r"(?:Status|Shown as:) ([a-z]+)\b", sentence))}
        self.assertEqual(len(said), 1, sentences)
        return said.pop()


class WhoseStatusTests(_Estate):
    """A node is drawn pale where what it shows comes from beneath it, and vivid
    where it is the node's own — on its head as on its card."""

    def test_the_head_is_pale_where_the_status_comes_from_beneath_it(self) -> None:
        for path in (ASPECT, ACCOUNT):
            with self.subTest(path=path):
                self.assertTrue(self._head(path).has("dim"))

    def test_the_node_that_fails_is_vivid_beneath_it(self) -> None:
        culprit = _drawn(self._page(f"/status/{_branch(ASPECT)}?depth=1"),
                         f"{ASPECT}/{FAILS}")
        self.assertEqual(_color(culprit), "error")
        self.assertFalse(culprit.has("dim"))

    def test_a_status_of_its_own_heads_vivid(self) -> None:
        # the node itself reports the failure, above nodes that are well
        self.tree.upsert("/shop/gateway", StatusCode.ERROR, "503 from /health")
        self.tree.upsert("/shop/gateway/backend", StatusCode.OK)
        head = self._head("/shop/gateway")
        self.assertEqual((_color(head), _word(head)), ("error", "error"))
        self.assertFalse(head.has("dim"))

    def test_a_node_that_is_well_above_nodes_that_are_well_heads_vivid(self) -> None:
        # as it did: the status is what the node says of itself as well
        self.check.mended = True
        app_module.engine.run_once()
        head = self._head(ASPECT)
        self.assertEqual((_color(head), _word(head)), ("ok", "ok"))
        self.assertFalse(head.has("dim"))

    def test_a_stale_reading_of_its_own_is_its_own_status(self) -> None:
        # its check stopped, above a node that is well: the tree counts the node's
        # own reading degraded (ADR-0005), so the warning is the node's and not
        # from beneath it — on its head, and on its card one page up
        self.tree.upsert("/shop/gateway", StatusCode.OK, "answers",
                         stale_after=0.01)
        self.tree.upsert("/shop/gateway/backend", StatusCode.OK)
        time.sleep(0.05)
        head = self._head("/shop/gateway")
        self.assertEqual((_color(head), _word(head)), ("warn", "warn"))
        self.assertFalse(head.has("dim"))
        card = _drawn(self._page("/status/shop?depth=2"), "/shop/gateway")
        self.assertTrue(card.has("status-card"))
        self.assertEqual(_color(card), "warn")
        self.assertFalse(card.has("dim"))
        # and on its box inside a card, two pages up
        box = _drawn(self._page("/status?depth=3"), "/shop/gateway")
        self.assertTrue(box.has("status-node"))
        self.assertEqual(_color(box), "warn")
        self.assertFalse(box.has("dim"))


class OwnPeriodTests(_Estate):
    """A node's periods are those of its own status, and a surface that states one
    of a node above others names it so (decision 3)."""

    def test_the_time_card_says_what_it_shows_and_names_the_period_its_own(
            self) -> None:
        made = self._period_said(f"{ASPECT}/{FAILS}")
        for query in ("depth=1", "depth=1&fragment=1", "depth=0"):
            with self.subTest(query=query):
                card = self._time_card(ASPECT, query)
                # the node beneath made the whole period: the instant is said once
                # (ADR-0132 decision 5)
                self.assertEqual(card[0], f"Status {made}, from {FAILS} beneath it")
                self.assertRegex(
                    card[1], rf"^Its own status ok since before {INSTANT}$")
                self.assertRegex(card[2], rf"^Last observed {INSTANT}$")

    def test_a_node_that_is_well_again_names_its_period_its_own_too(self) -> None:
        # *Status ok since before* its first reading was said of a node whose box
        # stood red in between: that period is its own status's, and what it shows
        # has been ok since the run that mended it (ADR-0132 decision 5)
        self.check.mended = True
        app_module.engine.run_once()
        shot = self.tree.snapshot(ASPECT)
        assert shot is not None and shot.period is not None
        self.assertIs(shot.code, StatusCode.OK)
        card = self._time_card(ASPECT)
        self.assertEqual(card[0], f"Status ok since {_shown(shot.period.began.at)}")
        self.assertRegex(card[1], rf"^Its own status ok since before {INSTANT}$")

    def test_a_failure_of_its_own_is_named_its_own_and_is_what_it_shows(
            self) -> None:
        # nothing comes from beneath it, so no line says so
        self.tree.upsert("/shop/gateway", StatusCode.OK, "answers")
        self.tree.upsert("/shop/gateway/backend", StatusCode.OK)
        self.tree.upsert("/shop/gateway", StatusCode.ERROR, "503 from /health")
        card = self._time_card("/shop/gateway")
        self.assertRegex(card[0], rf"^Status error since {INSTANT}$")
        self.assertRegex(card[1], rf"^Its own status error since {INSTANT}$")
        self.assertEqual(card[0].split(" since ")[1], card[1].split(" since ")[1])

    def test_a_node_in_maintenance_keeps_its_status(self) -> None:
        # a pin cancels what is beneath the node: the period is the node's
        self.client.post("/pins/maintenance", data={
            "path": _branch(ASPECT), "note": "cutover", "expires": "1d",
            "action": "set"})
        shot = self.tree.snapshot(ASPECT)
        assert shot is not None and shot.maintenance
        card = self._time_card(ASPECT)
        self.assertRegex(card[0], rf"^Status maintenance since {INSTANT}$")
        self.assertEqual([line for line in card if "own status" in line], [])

    def test_a_node_with_nothing_beneath_it_keeps_its_status(self) -> None:
        card = self._time_card(f"{ASPECT}/{FAILS}")
        self.assertRegex(card[0], rf"^Status error since {INSTANT}$")
        self.assertEqual([line for line in card if "own status" in line], [])

    def test_a_node_that_declares_nothing_states_no_period_of_its_own(self) -> None:
        # it says the period of what it shows and where that comes from, as a node
        # above others does (ADR-0132 decision 5), and its observation where a
        # period of its own would stand
        made = self._period_said(f"{ASPECT}/{FAILS}")
        card = self._time_card("/cloud/aws")
        self.assertEqual(card[0], f"Status {made}, from staging/codepipeline/{FAILS} "
                                  f"beneath it")
        self.assertRegex(card[1], rf"^Observed {INSTANT}\.$")
        self.assertEqual([line for line in card[1:] if "tatus" in line], [])

    def test_a_node_that_declares_nothing_and_shows_ok_names_no_node(self) -> None:
        # no one node makes it well, so the line names none
        self.check.mended = True
        app_module.engine.run_once()
        card = self._time_card("/cloud/aws")
        self.assertRegex(card[0],
                         rf"^Status ok since {INSTANT}, from the nodes beneath it$")
        self.assertRegex(card[1], rf"^Observed {INSTANT}\.$")

    def test_its_changes_are_counted_as_its_own_status_s(self) -> None:
        self.tree.upsert("/shop/gateway", StatusCode.OK, "answers")
        self.tree.upsert("/shop/gateway/backend", StatusCode.OK, "answers")
        self.tree.upsert("/shop/gateway", StatusCode.WARN, "slow")
        self.tree.upsert("/shop/gateway/backend", StatusCode.WARN, "slow")
        self.assertIn("1 change of its own status in the last hour",
                      self._time_card("/shop/gateway"))
        self.assertIn("1 status change in the last hour",
                      self._time_card("/shop/gateway/backend"))
        self.tree.upsert("/shop/gateway", StatusCode.OK, "answers")
        self.assertIn("2 changes of its own status in the last hour",
                      self._time_card("/shop/gateway"))

    def test_history_says_whose_periods_it_lists(self) -> None:
        # first those of what it shows, then those of its own status (ADR-0132
        # decision 6)
        for path in (ASPECT, ACCOUNT):
            with self.subTest(path=path):
                said = self._history_says(path)
                self.assertEqual(said, [SHOWN_PERIODS, OWN_PERIODS])

    def test_history_says_it_of_no_other_node(self) -> None:
        # a node with nothing beneath it has one table, of its own status; one that
        # declares nothing lists what it shows, and has no status of its own
        self.assertEqual(self._history_says(f"{ASPECT}/{FAILS}"), [])
        said = self._history_says("/cloud/aws")
        self.assertIn(SHOWN_PERIODS, said)
        self.assertNotIn(OWN_PERIODS, said)

    def test_a_node_that_stopped_declaring_has_its_own_sentence(self) -> None:
        # its table ends where it stopped, and says so (ADR-0094 decision 5):
        # the rows it keeps were its own status's, and one sentence says it
        self.tree.upsert("/estate/account", StatusCode.OK, "scope: 1 account")
        self.tree.upsert("/estate/account/eu", StatusCode.OK)
        self.tree.upsert("/estate/account", StatusCode.UNDEFINED, "scope: 1 account")
        said = self._history_says("/estate/account")
        self.assertEqual(len(said), 2, said)
        # beneath what it shows, which it still has (ADR-0132 decision 6)
        self.assertEqual(said[0], SHOWN_PERIODS)
        self.assertRegex(said[1], r"^Declares nothing of its own since ")

    def test_its_copy_document_names_the_period_its_own(self) -> None:
        # beneath the period of what it shows, which says what began it (ADR-0132
        # decision 6)
        document = self._copy(ASPECT)
        shown = document.index(
            "- **Shown as:** error ⛔ — rolled up from its own reading and the 3 "
            "nodes beneath it.")
        self.assertRegex(document[shown + 1],
                         rf"^- \*\*Status error\*\* since {INSTANT} \S+, begun by a "
                         rf"reading of {FAILS} beneath it$")
        self.assertRegex(document[shown + 2],
                         rf"^- \*\*Its own status ok\*\* since before {INSTANT} ")
        self.assertEqual(
            [line for line in document if line.startswith("- **Status")],
            [document[shown + 1]])

    def test_a_leaf_s_copy_document_keeps_its_status(self) -> None:
        document = self._copy(f"{ASPECT}/{FAILS}")
        self.assertEqual(
            len([line for line in document
                 if re.match(rf"- \*\*Status error\*\* since {INSTANT} ", line)]), 1)
        self.assertEqual([line for line in document if "own status" in line], [])


def _shown(instant: datetime) -> str:
    """An instant as a page writes it."""
    return str(app_module.app.jinja_env.filters["localtime"](instant))


class _Clock:
    """The clock the tree and the pages read (`instants.now`), moved by hand: which
    node began to show a code first, and when one went stale, are the test's to say
    and not the machine's speed. It starts after every reading the estate took."""

    def __init__(self) -> None:
        self.at = (datetime.now(UTC) + timedelta(seconds=1)).replace(microsecond=0)

    def __call__(self) -> datetime:
        return self.at

    def go(self, seconds: float) -> None:
        self.at += timedelta(seconds=seconds)


class MadeByTests(_Estate):
    """A branch's Time card names the node beneath it that makes what it shows
    (decision 3): one that counts the branch's code for itself, never one that only
    passes it on, and of several the one that has shown it the longest — a stale one
    from when it went stale. The line states the period of what the branch shows,
    and the named node's own *since* only where that began later (ADR-0132 decision
    5)."""

    def setUp(self) -> None:
        super().setUp()
        self.clock = _Clock()
        held = mock.patch.object(instants, "now", self.clock)
        held.start()
        self.addCleanup(held.stop)

    def _shop(self, *paths: str) -> None:
        """A branch that is well of its own above nodes that are well."""
        self.tree.upsert("/shop", StatusCode.OK, "answers")
        for path in paths:
            self.tree.upsert(f"/shop/{path}", StatusCode.OK, "answers")

    def test_every_branch_above_the_node_names_it(self) -> None:
        # by its path beneath the branch: the aspect and the account pass the code
        # on, and the root declares nothing — on the page, in its refresh and at
        # depth 0
        made = self._period_said(f"{ASPECT}/{FAILS}")
        for path, name in ((ASPECT, FAILS), (ACCOUNT, f"codepipeline/{FAILS}"),
                           ("/cloud/aws", f"staging/codepipeline/{FAILS}")):
            for query in ("depth=1", "depth=1&fragment=1", "depth=0"):
                with self.subTest(path=path, query=query):
                    self.assertEqual(
                        self._time_card(path, query)[0],
                        f"Status {made}, from {name} beneath it")

    def test_its_name_is_a_link_to_its_page(self) -> None:
        line = self._time_card_body(ACCOUNT).all(tag="p")[0]
        self.assertEqual(
            [(link.text(), link.attrs.get("href")) for link in line.all(tag="a")],
            [(f"codepipeline/{FAILS}", f"/status/{_branch(ASPECT)}/{FAILS}")])

    def test_a_node_that_only_passes_the_code_on_is_never_named(self) -> None:
        # *mid* has counted *ok* for itself since before the leaf failed, and shows
        # *error* only because the leaf does
        self._shop("mid", "mid/leaf")
        self.clock.go(10)
        self.tree.upsert("/shop/mid/leaf", StatusCode.ERROR, "down")
        made = self._period_said("/shop/mid/leaf")
        self.assertEqual(self._time_card("/shop")[0],
                         f"Status {made}, from mid/leaf beneath it")
        self.assertEqual(self._time_card("/shop/mid")[0],
                         f"Status {made}, from leaf beneath it")

    def test_of_several_it_names_the_one_that_has_shown_it_the_longest(
            self) -> None:
        # not the first on the page; and the warning that began before either
        # failure is not the branch's code, so it is neither named nor counted
        self._shop("a-late", "b-early", "c-warn")
        self.clock.go(5)
        self.tree.upsert("/shop/c-warn", StatusCode.WARN, "slow")
        self.clock.go(5)
        self.tree.upsert("/shop/b-early", StatusCode.ERROR, "down")
        self.clock.go(10)
        self.tree.upsert("/shop/a-late", StatusCode.ERROR, "down")
        made = self._period_said("/shop/b-early")
        self.assertEqual(self._time_card("/shop")[0],
                         f"Status {made}, from b-early beneath it, and 1 more")

    def test_a_branch_that_counts_it_for_itself_is_named_as_any_node(self) -> None:
        # the gateway's own check failed first and its backend after it: both
        # count the code for themselves, and the gateway's period is the older
        self._shop("gw", "gw/backend")
        self.clock.go(10)
        self.tree.upsert("/shop/gw", StatusCode.ERROR, "503 from /health")
        self.clock.go(10)
        self.tree.upsert("/shop/gw/backend", StatusCode.ERROR, "down")
        made = self._period_said("/shop/gw")
        self.assertTrue(made.startswith("error since "), made)
        self.assertEqual(self._time_card("/shop")[0],
                         f"Status {made}, from gw beneath it, and 1 more")

    def test_its_own_since_stands_where_it_began_after_the_branch_s(self) -> None:
        # the branch turned red from one node, which has recovered, and another has
        # kept it red since: the branch's instant first, then the named node's own
        # (ADR-0132 decision 5)
        self._shop("a", "b")
        self.clock.go(10)
        first = self.clock.at
        self.tree.upsert("/shop/a", StatusCode.ERROR, "down")
        self.clock.go(10)
        self.tree.upsert("/shop/b", StatusCode.ERROR, "down")
        self.clock.go(10)
        self.tree.upsert("/shop/a", StatusCode.OK, "answers")
        made = self._period_said("/shop/b")
        self.assertEqual(self._time_card("/shop")[0],
                         f"Status error since {_shown(first)}, from b beneath it, "
                         f"{made}")

    def test_a_period_that_began_before_a_bound_says_so(self) -> None:
        # its first reading found it failing, so the tree vouches for no beginning
        # (ADR-0099 decision 9): the line says *before*, as the node's own card does
        # — beside the branch's instant, which another node began earlier
        self._shop("web")
        self.clock.go(5)
        first = self.clock.at
        self.tree.upsert("/shop/web", StatusCode.ERROR, "down")
        self.clock.go(5)
        self.tree.upsert("/shop/db", StatusCode.ERROR, "down")
        self.clock.go(5)
        self.tree.upsert("/shop/web", StatusCode.OK, "answers")
        made = self._period_said("/shop/db")
        self.assertTrue(made.startswith("error since before "), made)
        self.assertEqual(self._time_card("/shop")[0],
                         f"Status error since {_shown(first)}, from db beneath it, "
                         f"{made}")

    def test_a_period_that_a_pin_s_end_began_says_so(self) -> None:
        # it failed under a pin and has shown the failure since the pin ended, which
        # the line says as the node's own card does (ADR-0099 decision 8) — beside
        # the branch's instant, which another node began earlier
        self._shop("db", "web")
        self.tree.set_maintenance("/shop/db", "cutover",
                                  expires_at=self.clock.at + timedelta(days=1),
                                  set_by="pan")
        self.clock.go(5)
        first = self.clock.at
        self.tree.upsert("/shop/web", StatusCode.ERROR, "down")
        self.clock.go(5)
        self.tree.upsert("/shop/db", StatusCode.ERROR, "down")
        self.clock.go(10)
        self.tree.clear_maintenance("/shop/db")
        self.clock.go(5)
        self.tree.upsert("/shop/web", StatusCode.OK, "answers")
        made = self._period_said("/shop/db")
        self.assertTrue(made.endswith(", when its maintenance ended"), made)
        self.assertEqual(self._time_card("/shop")[0],
                         f"Status error since {_shown(first)}, from db beneath it, "
                         f"{made}")

    def test_a_node_beneath_a_pin_is_never_named(self) -> None:
        # the pin cancels what is beneath it: the older failure does not reach the
        # branch, and is neither named nor counted
        self._shop("svc", "svc/db", "web")
        self.clock.go(10)
        self.tree.upsert("/shop/svc/db", StatusCode.ERROR, "down")
        self.client.post("/pins/maintenance", data={
            "path": "shop/svc", "note": "cutover", "expires": "1d",
            "action": "set"})
        self.clock.go(10)
        self.tree.upsert("/shop/web", StatusCode.ERROR, "down")
        made = self._period_said("/shop/web")
        self.assertEqual(self._time_card("/shop")[0],
                         f"Status {made}, from web beneath it")

    def test_a_stale_node_that_read_the_code_keeps_its_period(self) -> None:
        # its last reading was the failure, and it counts the code by that reading:
        # the line states the period its own page states
        self._shop()
        self.tree.upsert("/shop/x", StatusCode.OK, "answers", stale_after=5)
        self.clock.go(1)
        self.tree.upsert("/shop/x", StatusCode.ERROR, "down", stale_after=5)
        self.clock.go(10)
        made = self._period_said("/shop/x")
        self.assertTrue(made.startswith("error since "), made)
        self.assertEqual(self._time_card("/shop")[0],
                         f"Status {made}, from x beneath it")

    def test_a_stale_node_is_named_as_stale_with_its_last_observation(self) -> None:
        # it counts the warning only because its reading went stale, and its period
        # is of *ok*: the line says when it was last observed — and it went stale
        # before the other node began to warn, which is when the branch's period
        # began, its last observation and its tolerance after it (ADR-0132
        # decision 2)
        self._shop("new")
        observed = self.clock.at
        self.tree.upsert("/shop/old", StatusCode.OK, "answers", stale_after=5)
        self.clock.go(10)
        self.tree.upsert("/shop/new", StatusCode.WARN, "slow")
        self.assertEqual(self._time_card("/shop")[0],
                         f"Status warn since {_shown(observed + timedelta(seconds=5))}"
                         f", from old beneath it, stale, last observed "
                         f"{_shown(observed)}, and 1 more")

    def test_a_stale_node_is_weighed_from_when_it_went_stale(self) -> None:
        # last observed before the other node began to warn, and stale only after
        # it: it has counted the warning since it went stale, not since then
        self._shop("new")
        self.tree.upsert("/shop/old", StatusCode.OK, "answers", stale_after=60)
        self.clock.go(10)
        self.tree.upsert("/shop/new", StatusCode.WARN, "slow")
        self.clock.go(60)
        made = self._period_said("/shop/new")
        self.assertEqual(self._time_card("/shop")[0],
                         f"Status {made}, from new beneath it, and 1 more")


class NoRowForAParentTests(_Estate):
    """The log stays what it is (decision 4): a change beneath a node writes no row
    of that node, and the rows beneath it are what the Events page lists under it."""

    def test_a_change_beneath_a_node_is_no_row_of_the_node(self) -> None:
        rows = {path: [(event.old, event.new)
                       for event in self.tree.recent_events() if event.path == path]
                for path in (ASPECT, ACCOUNT, f"{ASPECT}/{FAILS}")}
        first = [(StatusCode.UNDEFINED, StatusCode.OK)]
        self.assertEqual(rows[ASPECT], first)
        self.assertEqual(rows[ACCOUNT], first)
        self.assertEqual(rows[f"{ASPECT}/{FAILS}"],
                         [*first, (StatusCode.OK, StatusCode.ERROR)])

    def test_its_history_lists_the_periods_of_its_own_status(self) -> None:
        periods = self.tree.history(ASPECT)
        self.assertEqual([period.code for period in periods], [StatusCode.OK])
