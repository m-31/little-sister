"""A node's details: named values whose keys its team chooses (ADR-0133 decision 6).

The type gives each node it writes the details of its object with each run, written
through; the deployment gives anything else — in the check's file for its own node,
under an aspect's name in its ``subnodes:`` block, and in ``nodes.yaml`` by path,
which wins key by key — and what the deployment gives a node holds for every node
beneath it, key by key, the nearest winning. The *About* card shows them as a table
beneath the about: the type's first, then what the deployment gives, the outermost
first, the node's own last, a key standing once where it is named highest with its
nearest value; a key given down names the node it is given on as its tooltip, and a
link it writes in the short form leads into that node's handbook. The Copy document
carries the card's table as a block, its links written out.
"""
from __future__ import annotations

import os
import tempfile
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from unittest import TestCase, mock

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister import details, handbooks, self_report
from little_sister.checks import Check, Measurement
from little_sister.checks.base import CheckResult
from little_sister.checks.http import HttpCheck
from little_sister.checks.loader import _load_one as load_check_file
from little_sister.checks.metadata import (
    STATED_SUBNODE_KEYS,
    SUBNODE_KEYS,
    parse_subnode_details,
    unknown_check_keys,
)
from little_sister.copy_status import Origin, TimeStyle, format_node_markdown
from little_sister.details import DEPLOYMENT, TYPE, Detail, Row
from little_sister.engine import Engine
from little_sister.errors import CheckError
from little_sister.nodes import NodeMeta, load_nodes, resolve_metadata
from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from tests.page_tree import Element, css_rule, parse

OK, ERROR, UNDEFINED = StatusCode.OK, StatusCode.ERROR, StatusCode.UNDEFINED


def _notes() -> dict[str, str]:
    """The startup record's handbook lines, by slug."""
    return {line.slug: line.text for line in self_report.startup.lines()
            if line.slug.startswith("handbook")}


class ReadTests(TestCase):
    """What a place of the configuration states, as written."""

    def test_a_mapping_in_the_order_written(self):
        self.assertEqual(details.read({"site": "Hall 2", "rack": "C-12",
                                       "contact": "[Ops](https://ops.example.org)"},
                                      "details"),
                         (("site", "Hall 2"), ("rack", "C-12"),
                          ("contact", "[Ops](https://ops.example.org)")))

    def test_absent_or_empty_states_none(self):
        self.assertEqual(details.read(None, "details"), ())
        self.assertEqual(details.read({}, "details"), ())

    def test_an_empty_value_is_a_statement(self):
        # it says the key has no value here, nor beneath
        self.assertEqual(details.read({"tickets": None, "docs": "", "x": "  "},
                                      "details"),
                         (("tickets", ""), ("docs", ""), ("x", "")))

    def test_a_value_over_several_lines_is_one_line(self):
        self.assertEqual(details.read({"login": "Through the bastion,\n  then\n\n"
                                                "`ssh admin@host`\n"}, "details"),
                         (("login", "Through the bastion, then `ssh admin@host`"),))

    def test_a_value_yaml_reads_as_anything_but_text_is_refused_naming_it(self):
        for value in (12, 3.1, False, 750, date(2026, 10, 24)):
            with self.subTest(value=value):
                with self.assertRaises(CheckError) as caught:
                    details.read({"slot": value}, "nodes.yaml: /dc.details")
                said = str(caught.exception)
                self.assertIn("nodes.yaml: /dc.details.slot", said)
                self.assertIn("quotes", said)

    def test_a_list_or_a_mapping_is_no_line(self):
        for value in (["a", "b"], {"a": "b"}):
            with self.subTest(value=value):
                with self.assertRaises(CheckError) as caught:
                    details.read({"contact": value}, "details")
                self.assertIn("one line of Markdown", str(caught.exception))

    def test_a_key_is_text_and_not_empty(self):
        for raw in ({12: "x"}, {True: "x"}, {" ": "x"}):
            with self.subTest(raw=raw), self.assertRaises(CheckError):
                details.read(raw, "details")

    def test_anything_but_a_mapping_is_refused(self):
        for raw in ("contact: x", ["contact"]):
            with self.subTest(raw=raw), self.assertRaises(CheckError):
                details.read(raw, "details")


class GivenTests(TestCase):
    """What a type hands over in code, on its result."""

    def test_a_mapping_or_pairs_each_text(self):
        self.assertEqual(details.given({"account": "123", "region": "eu-west-1"}, "x"),
                         (("account", "123"), ("region", "eu-west-1")))
        self.assertEqual(details.given([("host", "h1")], "x"), (("host", "h1"),))

    def test_an_empty_value_says_nothing(self):
        self.assertEqual(details.given({"a": "", "b": " \n ", "c": "x"}, "x"),
                         (("c", "x"),))

    def test_what_is_not_text_is_the_authors_error(self):
        for raw in ({"port": 22}, {"a": None}, [("a", "b", "c")], [("a", "x"),
                                                                ("a", "y")]):
            with self.subTest(raw=raw), self.assertRaises(CheckError):
                details.given(raw, "x")


class MergedTests(TestCase):
    def test_over_names_a_keys_value_and_under_keeps_its_place(self):
        self.assertEqual(details.merged((("a", "1"), ("b", "2")),
                                        (("c", "3"), ("a", "9"))),
                         (("a", "9"), ("b", "2"), ("c", "3")))

    def test_either_alone(self):
        self.assertEqual(details.merged((), (("a", "1"),)), (("a", "1"),))
        self.assertEqual(details.merged((("a", "1"),), ()), (("a", "1"),))


class OwnTests(TestCase):
    def test_the_types_first_then_the_deployments_each_as_given(self):
        # a key both name stands once for each, raw: the card resolves it, and so
        # can a client, to the type's place and the deployment's value
        self.assertEqual(
            details.own((("account", "123"), ("region", "eu-west-1")),
                        (("contact", "Ops"), ("region", "Frankfurt"))),
            (Detail("account", "123", TYPE),
             Detail("region", "eu-west-1", TYPE),
             Detail("contact", "Ops", DEPLOYMENT),
             Detail("region", "Frankfurt", DEPLOYMENT)))


class RowsTests(TestCase):
    """The card's order and the nearest value."""

    def test_the_type_first_then_from_above_outermost_first_then_its_own(self):
        rows = details.rows(
            "/aws/live/lambda/fn", (("function", "`fn`"),), (("login", "SSO"),),
            [("/", (("provider", "AWS"),)), ("/aws/live", (("tickets", "LIVE"),))])
        self.assertEqual(rows, (Row("function", "`fn`", "/aws/live/lambda/fn"),
                                Row("provider", "AWS", "/"),
                                Row("tickets", "LIVE", "/aws/live"),
                                Row("login", "SSO", "/aws/live/lambda/fn")))

    def test_a_contact_named_at_the_top_keeps_its_row_with_the_nearest_value(self):
        rows = details.rows(
            "/aws/live/ec2", (), (("docs", "D"),),
            [("/aws", (("contact", "Alice"), ("tickets", "T"))),
             ("/aws/live", (("contact", "Bob"),))])
        self.assertEqual(rows, (Row("contact", "Bob", "/aws/live"),
                                Row("tickets", "T", "/aws"),
                                Row("docs", "D", "/aws/live/ec2")))

    def test_a_place_told_level_by_level_composes_itself(self):
        rows = details.rows("/dc/hall/rack/slot", (), (("slot", "7"),),
                            [("/dc", (("site", "North"),)),
                             ("/dc/hall", (("room", "2"),)),
                             ("/dc/hall/rack", (("rack", "C-12"),))])
        self.assertEqual([(row.key, row.text) for row in rows],
                         [("site", "North"), ("room", "2"), ("rack", "C-12"),
                          ("slot", "7")])

    def test_the_type_on_the_node_is_nearer_than_anything_above(self):
        rows = details.rows("/a/b", (("region", "eu-west-1"),), (),
                            [("/a", (("region", "Frankfurt"),))])
        self.assertEqual(rows, (Row("region", "eu-west-1", "/a/b"),))

    def test_the_deployment_on_the_node_wins_over_the_type_in_its_place(self):
        rows = details.rows("/a/b", (("host", "h1"), ("os", "Linux")),
                            (("host", "web01"),), [])
        self.assertEqual(rows, (Row("host", "web01", "/a/b"), Row("os", "Linux",
                                                                    "/a/b")))

    def test_the_nearest_value_empty_is_the_row_not_standing(self):
        above = [("/a", (("tickets", "T"), ("contact", "C"))),
                 ("/a/b", (("tickets", ""),))]
        self.assertEqual(details.rows("/a/b/c", (), (), above),
                         (Row("contact", "C", "/a"),))
        # and on the node itself
        self.assertEqual(details.rows("/a/b/c", (), (("contact", ""),), above[:1]),
                         (Row("tickets", "T", "/a"),))
        # but what the type gives the node is nearer than an empty value above
        self.assertEqual(details.rows("/a/b/c", (("tickets", "own"),), (), above),
                         (Row("tickets", "own", "/a/b/c"), Row("contact", "C", "/a")))


class CheckFileTests(TestCase):
    """A check's file gives its own node's details and each aspect's under
    ``subnodes:``, read by the library for every type."""

    def _load(self, text: str) -> Check:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "check.yaml"
            path.write_text(text)
            return load_check_file(path)

    def test_its_own_nodes_and_an_aspects(self):
        check = self._load(
            "type: http\npath: /web\nurl: https://www.example.org\n"
            "details:\n  owner: Web team\n  docs: \"[Docs](https://d.example.org)\"\n"
            "subnodes:\n  response:\n    details:\n      tickets: WEB\n"
            "      contact:\n")
        self.assertEqual(check.details, (("owner", "Web team"),
                                         ("docs", "[Docs](https://d.example.org)")))
        self.assertEqual(check.subnode_details,
                         {"response": (("tickets", "WEB"), ("contact", ""))})

    def test_a_value_yaml_reads_otherwise_refuses_the_file_naming_it(self):
        with self.assertRaises(CheckError) as caught:
            self._load("type: http\npath: /web\nurl: https://www.example.org\n"
                       "details:\n  rack: 12\n")
        self.assertIn("check.yaml: details.rack", str(caught.exception))
        with self.assertRaises(CheckError) as caught:
            self._load("type: http\npath: /web\nurl: https://www.example.org\n"
                       "subnodes:\n  response:\n    details:\n      phone: 0123\n")
        self.assertIn("subnodes.response.details.phone", str(caught.exception))

    def test_an_aspects_details_are_a_key_the_library_knows(self):
        config = {"subnodes": {"response": {"details": {"a": "b"}, "detail": {}}}}
        self.assertEqual(unknown_check_keys(config), ["subnodes.response.detail"])
        self.assertIn("details", STATED_SUBNODE_KEYS)
        self.assertEqual(parse_subnode_details(config), {"response": (("a", "b"),)})

    def test_a_type_declares_none_for_a_name(self):
        # a type gives its details through its run, node by node; one in its
        # declarations is a key the library does not read, and the log says so
        self.assertNotIn("details", SUBNODE_KEYS)
        with self.assertLogs("little_sister", level="WARNING") as logged:
            HttpCheck(path="/web", url="https://www.example.org",
                      follow_redirects=False,
                      subnode_defaults={"response": {"details": {"a": "b"}}})
        self.assertIn("subnode_defaults.response.details", "\n".join(logged.output))

    def test_a_check_built_in_code_keeps_them_as_a_file_would(self):
        check = HttpCheck(path="/web", url="https://www.example.org",
                          follow_redirects=False, details={"owner": "Web"},
                          subnode_details={"response": [("contact", "")]})
        self.assertEqual(check.details, (("owner", "Web"),))
        self.assertEqual(check.subnode_details, {"response": (("contact", ""),)})


class NodesFileTests(TestCase):
    """``nodes.yaml`` gives a path's details, which win key by key."""

    def test_read_and_merged_key_by_key_over_an_earlier_root(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            (Path(d1) / "nodes.yaml").write_text(
                "/dc:\n  details: {site: North, contact: Alice}\n")
            (Path(d2) / "nodes.yaml").write_text(
                "/dc:\n  details: {contact: Bob, power: B-feed}\n")
            meta = load_nodes(f"{d1}{os.pathsep}{d2}")
        self.assertEqual(meta["/dc"], NodeMeta(details=(
            ("site", "North"), ("contact", "Bob"), ("power", "B-feed"))))

    def test_an_entry_of_details_alone_is_a_declaration(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "nodes.yaml").write_text(
                "/dc:\n  details: {site: North}\n/empty:\n  details: {}\n")
            meta = load_nodes(Path(directory))
        self.assertEqual(sorted(meta), ["/dc"])

    def test_a_value_yaml_reads_otherwise_refuses_the_file(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "nodes.yaml").write_text(
                "/dc:\n  details: {rack: 12}\n")
            with self.assertRaises(CheckError) as caught:
                load_nodes(Path(directory))
        self.assertIn("/dc.details.rack", str(caught.exception))

    def test_nodes_yaml_over_the_checks_file_and_two_checks_on_one_node(self):
        first = HttpCheck(path="/h", url="https://a.example.org",
                          follow_redirects=False, about="first",
                          details={"rack": "A1", "contact": "Alice"})
        second = HttpCheck(path="/h", url="https://b.example.org",
                           follow_redirects=False, title="second",
                           details={"contact": "Carol", "model": "X"})
        meta = resolve_metadata([first, second], {
            "/h": NodeMeta(details=(("model", "Y"), ("power", "B")))})
        self.assertEqual(meta["/h"].details, (("rack", "A1"), ("contact", "Carol"),
                                              ("model", "Y"), ("power", "B")))
        # the labels as before: the second check's replace the first's
        self.assertEqual((meta["/h"].about, meta["/h"].title), ("", "second"))


class TreeTests(TestCase):
    """The tree keeps the three parts apart and puts them together."""

    def test_the_snapshot_holds_a_nodes_own_and_the_rows_come_down(self):
        tree = StatusTree()
        tree.set_details("/aws", (("contact", "Alice"), ("tickets", "OPS")))
        tree.upsert("/aws/live", OK, type_details=(("account", "123"),))
        tree.upsert("/aws/live/lambda", OK, named_details=(("docs", "D"),))
        tree.upsert("/aws/live/lambda/fn", OK, type_details=(("function", "fn"),))
        tree.set_details("/aws/live", (("contact", "Bob"),))
        own = tree.snapshot("/aws/live")
        assert own is not None
        self.assertEqual(own.details, (Detail("account", "123", TYPE),
                                       Detail("contact", "Bob", DEPLOYMENT)))
        self.assertEqual(tree.details("/aws/live/lambda/fn"), (
            Row("function", "fn", "/aws/live/lambda/fn"),
            Row("contact", "Bob", "/aws/live"),
            Row("tickets", "OPS", "/aws"),
            Row("docs", "D", "/aws/live/lambda")))
        # the account's are its own and come down to none beneath it
        self.assertNotIn("account", [row.key for row in
                                     tree.details("/aws/live/lambda")])
        self.assertEqual(tree.details("/nowhere"), ())
        self.assertEqual(tree.own_details("/nowhere"), ())

    def test_what_a_run_gives_writes_through_and_a_seed_stays(self):
        tree = StatusTree()
        tree.set_details("/h", (("rack", "A1"),))
        tree.upsert("/h", OK, type_details=(("host", "h1"),),
                    named_details=(("docs", "D"),))
        tree.upsert("/h", OK, type_details=(), named_details=())
        self.assertEqual(tree.details("/h"), (Row("rack", "A1", "/h"),))
        # a write that says nothing of them leaves them
        tree.upsert("/h", OK, type_details=(("host", "h2"),))
        tree.upsert("/h", ERROR)
        self.assertEqual([row.text for row in tree.details("/h")], ["h2", "A1"])

    def test_the_types_are_withheld_on_a_node_two_checks_mount(self):
        tree = StatusTree()
        tree.set_check_mount("/nexus")
        tree.set_check_mount("/nexus")
        tree.set_details("/nexus", (("rack", "A1"),))
        tree.upsert("/nexus", OK, type_details=(("host", "nexus"),))
        snapshot = tree.snapshot("/nexus")
        assert snapshot is not None
        self.assertEqual(snapshot.details, (Detail("rack", "A1", DEPLOYMENT),))
        self.assertEqual(tree.details("/nexus"), (Row("rack", "A1", "/nexus"),))

    def test_a_node_that_leaves_and_returns_keeps_its_declared_details(self):
        tree = StatusTree()
        tree.set_details("/h/disk", (("bay", "3"),))
        tree.upsert("/h/disk", OK)
        tree.prune("/h", keep=())
        self.assertIsNone(tree.snapshot("/h/disk"))
        tree.upsert("/h/disk", OK)
        self.assertEqual(tree.details("/h/disk"), (Row("bay", "3", "/h/disk"),))


class _Branch(Check):
    """A check whose run hands its result over as it is told."""

    def __init__(self, *, result: CheckResult, **kwargs: object) -> None:
        super().__init__(**kwargs)                          # type: ignore[arg-type]
        self.result = result

    def measure(self) -> Measurement:
        return Measurement(record={})

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        return self.result


class EngineTests(TestCase):
    """The type's per node with each run; the deployment's by an aspect's name."""

    def setUp(self) -> None:
        handbooks.forget()
        self_report.startup.forget()
        self.addCleanup(handbooks.forget)
        self.addCleanup(self_report.startup.forget)

    def test_a_types_on_every_node_it_writes_the_root_too_written_through(self):
        tree = StatusTree()
        check = _Branch(path="/aws/live", result=CheckResult(
            OK, details={"account": "123"}, children=(
                CheckResult(OK, name="lambda", children=(
                    CheckResult(OK, name="fn", dynamic=True,
                                details={"function": "fn"}),)),)))
        engine = Engine([check], tree)
        engine.run_once()
        self.assertEqual(tree.details("/aws/live")[0], Row("account", "123",
                                                           "/aws/live"))
        self.assertEqual(tree.details("/aws/live/lambda/fn"),
                         (Row("function", "fn", "/aws/live/lambda/fn"),))
        # the next run's are what the node holds
        check.result = CheckResult(OK, children=(
            CheckResult(OK, name="lambda", children=(
                CheckResult(OK, name="fn", dynamic=True,
                            details={"function": "fn", "runtime": "py"}),)),))
        engine.run_once()
        self.assertEqual(tree.details("/aws/live"), ())
        self.assertEqual([row.key for row in tree.details("/aws/live/lambda/fn")],
                         ["function", "runtime"])

    def test_an_aspects_reach_every_node_a_run_names_beneath_it(self):
        tree = StatusTree()
        engine = Engine([_Branch(
            path="/aws/live",
            subnode_details={"lambda": {"tickets": "LAMBDA"},
                             "fn": {"owner": "never"}},
            result=CheckResult(OK, children=(
                CheckResult(OK, name="lambda", children=(
                    CheckResult(OK, name="fn", dynamic=True),)),)))], tree)
        engine.run_once()
        self.assertEqual(tree.details("/aws/live/lambda"),
                         (Row("tickets", "LAMBDA", "/aws/live/lambda"),))
        # a child a run names takes nothing declared for its name (ADR-0118), and
        # what is given down to it reaches it
        self.assertEqual(tree.details("/aws/live/lambda/fn"),
                         (Row("tickets", "LAMBDA", "/aws/live/lambda"),))

    def test_a_link_into_a_handbook_that_leads_nowhere_is_named_once(self):
        tree = StatusTree()
        tree.set_details("/aws", (("login", "[sign in](handbook#sign-in)"),))
        engine = Engine([_Branch(
            path="/aws/live", subnode_details={"s3": {"docs": "[it](handbook#no)"}},
            result=CheckResult(OK, details={"account": "[a](handbook#acct)"},
                               children=(CheckResult(OK, name="s3"),)))], tree)
        tree.set_handbook("/aws/live", "## Elsewhere\n")
        with mock.patch.object(handbooks, "note_links",
                               wraps=handbooks.note_links) as looked:
            for _ in range(3):
                engine.run_once()
        self.assertEqual(sorted(call.args[0] for call in looked.call_args_list),
                         ["/aws/live", "/aws/live/s3"])
        said = "\n".join(_notes().values())
        self.assertIn("the detail 'account' of '/aws/live' links handbook#acct, a "
                      "section its handbook does not have", said)
        self.assertIn("the detail 'docs' of '/aws/live/s3' links handbook#no, but no "
                      "handbook is written for the node", said)
        # a detail given down is the node's it is given on, which the start looks at
        self.assertNotIn("sign-in", said)


class StartupTests(TestCase):
    def setUp(self) -> None:
        handbooks.forget()
        self_report.startup.forget()
        self.addCleanup(handbooks.forget)
        self.addCleanup(self_report.startup.forget)

    def test_the_configurations_are_looked_at_for_the_node_they_are_given_on(self):
        from little_sister.nodes import run_consistency_pass
        check = HttpCheck(path="/web", url="https://www.example.org",
                          follow_redirects=False,
                          details={"runbook": "[it](handbook#when-it-fails)"})
        metadata = resolve_metadata([check], {
            "/": NodeMeta(details=(("login", "[sign in](handbook#sign-in)"),),
                          handbook="## Sign in\n")})
        run_consistency_pass([check], metadata)
        said = "\n".join(_notes().values())
        self.assertIn("the detail 'runbook' of '/web' links handbook#when-it-fails, "
                      "but no handbook is written for the node", said)
        self.assertNotIn("sign-in", said)


class _Pages(TestCase):
    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        self._original = app_module.status_tree
        self.addCleanup(setattr, app_module, "status_tree", self._original)
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})
        self.tree.upsert("/servers", UNDEFINED, None, frequency_seconds=120)
        self.tree.upsert("/servers/web01", OK, type_details=(("host",
                                                              "`web01.example.net`"),))
        self.tree.upsert("/servers/web01/disk", ERROR, "97 % used",
                         description="Disk use on the host",
                         type_details=(("array", "`/dev/md0`"),))
        self.tree.set_handbook("/servers", "## Sign in\n\nThrough the bastion.\n")
        self.tree.set_details("/servers", (
            ("login", "[sign in](handbook#sign-in)"), ("contact", "Ops {error}")))
        self.tree.set_details("/servers/web01/disk", (("bay", "3"),))

    def page(self, url: str) -> Element:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return parse(response.get_data(as_text=True))


class CardTests(_Pages):
    def test_the_table_after_the_texts_in_the_cards_order(self):
        card = self.page("/status/servers/web01/disk").one("ls-node-about")
        box = card.one("ls-node-about__details")
        # in a box that scrolls it, as every table of the page is
        self.assertTrue(box.has("table-responsive"))
        table = box.one(tag="table")
        self.assertLess(card.one("ls-node-about__description").order, table.order)
        rows = [(row.one(tag="th").text(), row.one(tag="td").text())
                for row in table.all(tag="tr")]
        self.assertEqual(rows, [("array", "/dev/md0"), ("login", "sign in"),
                                ("contact", "Ops error"), ("bay", "3")])
        keys = table.all(tag="th")
        self.assertTrue(all(key.has("text-muted") and key.attrs["scope"] == "row"
                            for key in keys))
        # a key given down names the node it comes from; its own do not
        self.assertEqual([key.attrs.get("title") for key in keys],
                         [None, "/servers", "/servers", None])

    def test_a_value_is_rendered_for_the_node_it_is_given_on(self):
        table = self.page("/status/servers/web01/disk").one("ls-node-about__details")
        link = table.one(tag="a")
        self.assertEqual(link.attrs["href"], "/handbook/servers#sign-in")
        self.assertEqual(len(table.all("ls-sign")), 1)
        self.assertEqual(table.all(tag="code")[0].text(), "/dev/md0")

    def test_a_node_with_details_alone_has_its_card(self):
        page = self.page("/status/servers/web01")
        card = page.one("ls-node-about")
        self.assertEqual(card.all("ls-node-about__description"), [])
        self.assertEqual([th.text() for th in card.all(tag="th")],
                         ["host", "login", "contact"])
        # a node with nothing of its own and nothing given down has none
        tree = StatusTree()
        tree.upsert("/plain", OK)
        app_module.status_tree = tree
        self.assertEqual(self.page("/status/plain").all("ls-node-about"), [])

    def test_the_stylesheet_rules_it_only_after_a_text(self):
        css = (Path(app_module.__file__).parent / "static" / "css"
               / "overview.css").read_text(encoding="utf-8")
        ruled = css_rule(css, ".ls-node-about .md-body + .ls-node-about__details")
        self.assertIn("border-top: 1px solid var(--ls-line)", ruled)
        self.assertIn("white-space: nowrap",
                      css_rule(css, ".ls-node-about__details th"))


class CopyDocumentTests(_Pages):
    def test_the_document_carries_the_cards_table_written_out(self):
        page = self.page("/copy/servers/web01/disk")
        document = page.with_id("ls-copy-source").source()
        block = document.split("**Details**\n\n", 1)[1].split("\n\n", 1)[0]
        self.assertEqual(block.splitlines(), [
            "- **array:** `/dev/md0`",
            "- **login:** [sign in](http://localhost/handbook/servers#sign-in)",
            "- **contact:** Ops error ⛔",
            "- **bay:** 3"])
        # after the facts, before the reasons
        self.assertLess(document.index("**As of:**"), document.index("**Details**"))
        self.assertLess(document.index("**Details**"), document.index("**Reasons**"))

    def test_a_branchs_too_and_none_without_any(self):
        document = self.page("/copy/servers/web01").with_id("ls-copy-source").source()
        self.assertIn("**Details**\n\n- **host:** `web01.example.net`", document)
        tree = StatusTree()
        tree.upsert("/plain", OK)
        app_module.status_tree = tree
        document = self.page("/copy/plain").with_id("ls-copy-source").source()
        self.assertNotIn("**Details**", document)

    def test_a_key_is_written_as_a_name(self):
        node = self.tree.snapshot("/servers/web01/disk")
        assert node is not None
        document = format_node_markdown(
            node, TimeStyle(zone=UTC), origin=Origin(
                "https://x.example.org/status/a", datetime(2026, 10, 24, tzinfo=UTC)),
            details=(Row("*odd* [key]", "v", "/servers"),))
        self.assertIn("- **\\*odd\\* \\[key\\]:** v", document)


class EnvelopeTests(_Pages):
    """The API carries each node's own details as given, each saying who gave it, and
    never the card's rows: a client resolves those from the nodes above."""

    def test_each_nodes_own_as_given_and_none_where_it_has_none(self):
        # a node whose card shows only what is given down to it carries none
        self.tree.upsert("/servers/web01/cpu", OK)
        app_module.api_tokens = {"tester": "secret-token"}
        self.addCleanup(setattr, app_module, "api_tokens", {})
        body = self.client.get("/status/servers", headers={
            "Accept": "application/json",
            "Authorization": "Bearer secret-token"}).get_json()
        servers = body["status"]
        self.assertEqual(servers["details"], [
            {"key": "login", "text": "[sign in](handbook#sign-in)",
             "by": "deployment"},
            {"key": "contact", "text": "Ops {error}", "by": "deployment"}])
        web01 = servers["children"][0]
        self.assertEqual(web01["details"], [
            {"key": "host", "text": "`web01.example.net`", "by": "type"}])
        disk = next(child for child in web01["children"] if child["name"] == "disk")
        self.assertEqual(disk["details"], [
            {"key": "array", "text": "`/dev/md0`", "by": "type"},
            {"key": "bay", "text": "3", "by": "deployment"}])
        cpu = next(child for child in web01["children"] if child["name"] == "cpu")
        self.assertNotIn("details", cpu)
        self.assertEqual([row.key for row in self.tree.details("/servers/web01/cpu")],
                         ["login", "contact"])
