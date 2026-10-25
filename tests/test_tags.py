"""A node's tags: the facts about it that do not follow the tree (ADR-0139).

A deployment writes a tag wherever it writes a node's details — in a check's file for
its own node, under an aspect's name in its ``subnodes:`` block, and in ``nodes.yaml``
by path — and a node carries every tag written for it or for a node above it: a union
everywhere, a later root adding to an earlier one's. ``tags.yaml`` names the known
tags, each with a line of what it means; a tag is a word, capitals read as lower case,
and one the file does not name applies and is named once on the startup record. A
node's *About* card shows its tags as a line of chips, the hover card names them, the
Copy document lists them with their lines, and the envelope carries every one.
"""
from __future__ import annotations

import os
import tempfile
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from unittest import TestCase, mock

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister import self_report, tags
from little_sister.checks import Check, Measurement
from little_sister.checks.base import CheckResult
from little_sister.checks.http import HttpCheck
from little_sister.checks.loader import _load_one as load_check_file
from little_sister.checks.metadata import (
    STATED_SUBNODE_KEYS,
    parse_subnode_tags,
    unknown_check_keys,
)
from little_sister.engine import Engine
from little_sister.nodes import NodeMeta, load_nodes, resolve_metadata, tag_places
from little_sister.status import StatusCode
from little_sister.tags import NO_VOCABULARY, Vocabulary
from little_sister.tree import StatusTree
from tests.page_tree import Element, css_rule, parse

OK, ERROR, UNDEFINED = StatusCode.OK, StatusCode.ERROR, StatusCode.UNDEFINED


def _notes() -> dict[str, str]:
    """The startup record's tag lines, by slug."""
    return {line.slug: line.text for line in self_report.startup.lines()
            if line.slug.startswith("tags")}


class _Startup(TestCase):
    """A test that reads what the startup record says, from a clean record."""

    def setUp(self) -> None:
        self_report.startup.forget()
        self.addCleanup(self_report.startup.forget)


class ReadTests(_Startup):
    """What one place of the configuration writes."""

    def test_a_list_of_words_in_the_order_written_each_once(self):
        self.assertEqual(tags.read(["production", "rack-4", "production"], "here"),
                         ("production", "rack-4"))
        self.assertEqual(_notes(), {})

    def test_one_word_alone_and_none(self):
        self.assertEqual(tags.read("production", "here"), ("production",))
        self.assertEqual(tags.read(None, "here"), ())
        self.assertEqual(tags.read([], "here"), ())

    def test_capitals_are_read_as_lower_case(self):
        self.assertEqual(tags.read(["Production", " EU-West-1 "], "here"),
                         ("production", "eu-west-1"))
        self.assertEqual(_notes(), {})

    def test_a_word_that_is_no_tag_is_not_read_and_named(self):
        written = tags.read(["prod live", "rack_4", "-edge", "a--b", "fine"],
                            "nodes.yaml: /dc.tags")
        self.assertEqual(written, ("fine",))
        said = "\n".join(_notes().values())
        for word in ("prod live", "rack_4", "-edge", "a--b"):
            self.assertIn(f"nodes.yaml: /dc.tags names '{word}', which is not read: "
                          f"a tag is lowercase letters and digits, with hyphens "
                          f"between them", said)
        self.assertEqual(len(_notes()), 4)

    def test_a_value_yaml_reads_as_no_text_is_not_read_and_named(self):
        self.assertEqual(tags.read([True, 12, "fine"], "here"), ("fine",))
        said = "\n".join(_notes().values())
        self.assertIn("here names True, which YAML reads as a bool; a tag is a word, "
                      "so it is not read — put it in quotes", said)
        self.assertIn("here names 12, which YAML reads as a int", said)

    def test_a_mapping_is_none_of_it(self):
        self.assertEqual(tags.read({"production": "yes"}, "here"), ())
        self.assertIn("here is a dict, where a tag or a list of tags is written; none "
                      "of it is read", "\n".join(_notes().values()))

    def test_spelled_is_the_one_rule(self):
        self.assertEqual(tags.spelled("Rack-4"), "rack-4")
        self.assertEqual(tags.spelled("rack 4"), "")
        self.assertEqual(tags.spelled(""), "")

    def test_union_adds_up_in_the_order_met(self):
        self.assertEqual(tags.union(("a", "b"), ("b", "c"), ("a",)), ("a", "b", "c"))


class VocabularyTests(_Startup):
    """``tags.yaml``: the known tags, each with what it means."""

    def test_every_roots_adds_up_the_later_line_winning_in_the_first_place(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            (Path(d1) / "tags.yaml").write_text(
                "production: Serves customers.\nstaging: The candidate.\n")
            (Path(d2) / "tags.yaml").write_text(
                "rack-4: In rack 4.\nproduction: |\n  Serves customers;\n"
                "  somebody's outage.\n")
            vocabulary = tags.load_vocabulary(f"{d1}{os.pathsep}{d2}")
        self.assertEqual(list(vocabulary.lines),
                         ["production", "staging", "rack-4"])
        self.assertEqual(vocabulary.line("production"),
                         "Serves customers; somebody's outage.")
        self.assertEqual(len(vocabulary.files), 2)
        self.assertTrue(vocabulary.knows("rack-4"))
        self.assertFalse(vocabulary.knows("dev"))
        self.assertEqual(vocabulary.line("dev"), "")

    def test_no_file_is_no_known_tag(self):
        with tempfile.TemporaryDirectory() as directory:
            vocabulary = tags.load_vocabulary(Path(directory))
        self.assertEqual(vocabulary, NO_VOCABULARY)

    def test_an_empty_line_and_capitals(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "tags.yaml").write_text("Production:\nedge: ''\n")
            vocabulary = tags.load_vocabulary(Path(directory))
        self.assertEqual(dict(vocabulary.lines), {"production": "", "edge": ""})
        self.assertEqual(_notes(), {})

    def test_what_is_not_read_is_named(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "tags.yaml"
            file.write_text("good: Fine.\nrack 4: Spaced.\n12: A number.\n"
                            "edge: 3.10\n")
            vocabulary = tags.load_vocabulary(Path(directory))
            said = "\n".join(_notes().values())
            self.assertIn(f"{file} names 'rack 4', which is not read", said)
            self.assertIn(f"{file} names 12, which is not read: a tag is lowercase "
                          f"letters and digits, with hyphens between them — YAML reads "
                          f"it as a int; put it in quotes", said)
            self.assertIn(f"{file} gives 'edge' the line 3.1, which YAML reads as a "
                          f"float; the tag is known and says nothing of what it means",
                          said)
        self.assertEqual(dict(vocabulary.lines), {"good": "Fine.", "edge": ""})

    def test_a_file_that_is_no_mapping_is_not_read(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "tags.yaml"
            file.write_text("- production\n- staging\n")
            vocabulary = tags.load_vocabulary(Path(directory))
            self.assertIn(f"{file} is not read: it maps each tag to a line that says "
                          f"what it means, and it is a list",
                          "\n".join(_notes().values()))
        self.assertEqual(dict(vocabulary.lines), {})
        # it was found, so the tags are unknown to a file that is there
        self.assertEqual(len(vocabulary.files), 1)

    def test_a_node_lists_the_known_in_their_order_then_the_rest_by_name(self):
        vocabulary = Vocabulary({"production": "", "rack-4": "", "berlin": ""})
        self.assertEqual(vocabulary.ordered({"zeta", "berlin", "alpha", "production"}),
                         ("production", "berlin", "alpha", "zeta"))
        self.assertEqual(NO_VOCABULARY.ordered(["b", "a", "b"]), ("a", "b"))


class UnknownTests(_Startup):
    """A tag no ``tags.yaml`` names applies, and is named once, with where."""

    def test_named_once_with_where_against_the_files(self):
        vocabulary = Vocabulary({"production": "Serves customers."},
                                (Path("/etc/ls/tags.yaml"),))
        tags.note_unknown(vocabulary, {
            "production": ["nodes.yaml for /aws/live"],
            "prod": ["nodes.yaml for /a", "the check file of /b", "nodes.yaml for /c",
                     "nodes.yaml for /d", "nodes.yaml for /e", "nodes.yaml for /a"]})
        notes = _notes()
        self.assertEqual(list(notes), ["tags-unknown-prod"])
        self.assertEqual(notes["tags-unknown-prod"],
                         "the tag 'prod', written in nodes.yaml for /a, the check file "
                         "of /b, nodes.yaml for /c and 2 more, is not among the known "
                         "tags of /etc/ls/tags.yaml; it applies, and the file is where "
                         "a tag says what it means")

    def test_every_tag_where_no_root_has_a_file(self):
        tags.note_unknown(NO_VOCABULARY, {"production": ["nodes.yaml for /aws"]})
        self.assertEqual(_notes(), {
            "tags-unknown-production":
                "the tag 'production' is written in nodes.yaml for /aws, and no "
                "configuration root has a tags.yaml to say what it means; it "
                "applies"})

    def test_it_is_a_warning(self):
        tags.note_unknown(NO_VOCABULARY, {"x": ["here"]})
        line = next(line for line in self_report.startup.lines()
                    if line.slug == "tags-unknown-x")
        self.assertIs(line.code, StatusCode.WARN)


class CheckFileTests(_Startup):
    """A check's file gives its own node's tags and each aspect's under
    ``subnodes:``, read by the library for every type."""

    def _load(self, text: str) -> Check:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "check.yaml"
            path.write_text(text)
            return load_check_file(path)

    def test_its_own_nodes_and_an_aspects(self):
        check = self._load(
            "type: http\npath: /web\nurl: https://www.example.org\n"
            "tags: [Production, customer-facing]\n"
            "subnodes:\n  response:\n    tags: edge\n  tls:\n    title: TLS\n")
        self.assertEqual(check.tags, ("production", "customer-facing"))
        self.assertEqual(check.subnode_tags, {"response": ("edge",)})

    def test_a_word_that_is_no_tag_is_named_and_the_file_loads(self):
        check = self._load(
            "type: http\npath: /web\nurl: https://www.example.org\n"
            "tags: [prod live, fine]\n"
            "subnodes:\n  response:\n    tags: [yes]\n")
        self.assertEqual(check.tags, ("fine",))
        self.assertEqual(check.subnode_tags, {})
        said = "\n".join(_notes().values())
        self.assertIn("the check /web's tags names 'prod live', which is not read",
                      said)
        self.assertIn("the check /web: subnodes.response.tags names True, which YAML "
                      "reads as a bool", said)

    def test_an_aspects_tags_are_a_key_the_library_knows(self):
        config = {"subnodes": {"response": {"tags": ["a"], "tag": "b"}}}
        self.assertEqual(unknown_check_keys(config), ["subnodes.response.tag"])
        self.assertIn("tags", STATED_SUBNODE_KEYS)
        self.assertEqual(parse_subnode_tags(config), {"response": ("a",)})

    def test_a_check_built_in_code_keeps_them_as_a_file_would(self):
        check = HttpCheck(path="/web", url="https://www.example.org",
                          follow_redirects=False, tags=["Edge"],
                          subnode_tags={"response": ("a", "a"), "tls": ()})
        self.assertEqual(check.tags, ("edge",))
        self.assertEqual(check.subnode_tags, {"response": ("a",)})


class NodesFileTests(_Startup):
    """``nodes.yaml`` writes a path's tags, which add up across the roots."""

    def test_read_and_added_to_an_earlier_roots(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            (Path(d1) / "nodes.yaml").write_text(
                "/dc:\n  tags: [production, berlin]\n")
            (Path(d2) / "nodes.yaml").write_text(
                "/dc:\n  tags: [staging, production]\n  title: DC\n")
            meta = load_nodes(f"{d1}{os.pathsep}{d2}")
        self.assertEqual(meta["/dc"], NodeMeta(
            title="DC", tags=("production", "berlin", "staging")))

    def test_an_entry_of_tags_alone_is_a_declaration(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "nodes.yaml").write_text(
                "/dc:\n  tags: production\n/empty:\n  tags: []\n")
            with self.assertNoLogs("little_sister", level="WARNING"):
                meta = load_nodes(Path(directory))
        self.assertEqual(sorted(meta), ["/dc"])
        self.assertEqual(meta["/dc"].tags, ("production",))

    def test_a_word_that_is_no_tag_is_named_and_the_file_loads(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "nodes.yaml").write_text(
                "/dc:\n  tags: [rack 4, berlin]\n")
            meta = load_nodes(Path(directory))
        self.assertEqual(meta["/dc"].tags, ("berlin",))
        self.assertIn("nodes.yaml: /dc.tags names 'rack 4', which is not read",
                      "\n".join(_notes().values()))

    def test_the_checks_files_and_nodes_yaml_add_up(self):
        first = HttpCheck(path="/h", url="https://a.example.org",
                          follow_redirects=False, tags=["production"])
        second = HttpCheck(path="/h", url="https://b.example.org",
                           follow_redirects=False, tags=["berlin", "production"])
        meta = resolve_metadata([first, second], {
            "/h": NodeMeta(tags=("rack-4",))})
        self.assertEqual(meta["/h"].tags, ("production", "berlin", "rack-4"))

    def test_the_places_every_tag_is_written(self):
        check = HttpCheck(path="/h", url="https://a.example.org",
                          follow_redirects=False, tags=["production"],
                          subnode_tags={"response": ["edge"]})
        self.assertEqual(
            tag_places([check], {"/": NodeMeta(tags=("production",))}),
            {"production": ["nodes.yaml for /", "the check file of /h"],
             "edge": ["the check file of /h, under subnodes: response"]})


class TreeTests(TestCase):
    """A node carries every tag written for it or for a node above it."""

    def setUp(self) -> None:
        self.tree = StatusTree()
        self.tree.upsert("/aws/live/ec2/i-1", OK)
        self.tree.upsert("/aws/develop/ec2", ERROR, "down")
        self.tree.use_tags(
            Vocabulary({"production": "Serves customers.", "aws": ""}),
            {"/aws": ("aws",), "/aws/live": ("production", "berlin"),
             "/aws/live/ec2/i-1": ("aws",)})

    def node(self, path: str):
        snapshot = self.tree.snapshot(path)
        assert snapshot is not None
        return snapshot

    def test_down_the_tree_as_a_union_in_the_known_order(self):
        self.assertEqual(self.node("/").tags, ())
        self.assertEqual(self.node("/aws").tags, ("aws",))
        self.assertEqual(self.node("/aws/live").tags, ("production", "aws", "berlin"))
        self.assertEqual(self.node("/aws/live/ec2/i-1").tags,
                         ("production", "aws", "berlin"))
        self.assertEqual(self.node("/aws/develop/ec2").tags, ("aws",))

    def test_never_up_the_tree(self):
        aws = self.node("/aws")
        self.assertNotIn("production", aws.tags)
        root = self.node("/")
        self.assertEqual(root.tags, ())
        # and the snapshot of the whole tree says of each what its own says
        whole = {child.path: child.tags for child in root.children[0].children}
        self.assertEqual(whole, {"/aws/develop": ("aws",),
                                 "/aws/live": ("production", "aws", "berlin")})

    def test_a_subtree_read_by_its_path_carries_what_is_written_above_it(self):
        self.assertEqual(self.node("/aws/live/ec2").tags,
                         ("production", "aws", "berlin"))

    def test_where_each_is_written_the_nearest(self):
        self.assertEqual(self.tree.tags_given("/aws/live/ec2/i-1"), (
            ("production", "/aws/live"), ("aws", "/aws/live/ec2/i-1"),
            ("berlin", "/aws/live")))
        self.assertEqual(self.tree.tags_given("/aws"), (("aws", "/aws"),))
        self.assertEqual(self.tree.tags_given("/nowhere"), ())

    def test_a_path_no_node_stands_at_carries_its_nearest_nodes(self):
        self.assertEqual(self.tree.tags_of("/aws/live/s3/bucket"),
                         ("production", "aws", "berlin"))
        self.assertEqual(self.tree.tags_of("/gone"), ())

    def test_a_path_written_before_its_node_stands(self):
        self.tree.use_tags(NO_VOCABULARY, {"/web": ("edge",)})
        self.tree.upsert("/web/api", OK)
        self.assertEqual(self.node("/web/api").tags, ("edge",))

    def test_a_name_given_under_subnodes_adds_up_with_its_paths(self):
        self.tree.upsert("/aws/develop", UNDEFINED, named_tags=("lab", "aws"))
        self.assertEqual(self.node("/aws/develop/ec2").tags, ("aws", "lab"))
        self.assertEqual(self.tree.tags_given("/aws/develop/ec2"),
                         (("aws", "/aws/develop"), ("lab", "/aws/develop")))


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
    """An aspect's tags are written on the child of its name, and come down."""

    def test_an_aspects_reach_every_node_beneath_it_never_one_a_run_names(self):
        tree = StatusTree()
        engine = Engine([_Branch(
            path="/aws/live",
            subnode_tags={"lambda": ["serverless"], "fn": ["never"]},
            result=CheckResult(OK, children=(
                CheckResult(OK, name="lambda", children=(
                    CheckResult(OK, name="fn", dynamic=True),)),)))], tree)
        engine.run_once()
        self.assertEqual(tree.snapshot("/aws/live").tags, ())        # type: ignore
        self.assertEqual(tree.snapshot("/aws/live/lambda").tags,     # type: ignore
                         ("serverless",))
        # a child a run names takes nothing declared for its name (ADR-0118), and
        # what is given down to it reaches it
        self.assertEqual(tree.snapshot("/aws/live/lambda/fn").tags,  # type: ignore
                         ("serverless",))


class StartupTests(_Startup):
    """The start reads the known tags and hands the tree the tags written by path,
    before the rules; a tag no file names is a line once."""

    def test_the_tree_is_handed_them_and_the_unknown_are_named(self):
        tree = StatusTree()
        original = app_module.status_tree
        app_module.status_tree = tree
        self.addCleanup(setattr, app_module, "status_tree", original)
        check = HttpCheck(path="/web", url="https://www.example.org",
                          follow_redirects=False, tags=["production", "edge"])
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "tags.yaml").write_text(
                "production: Serves customers.\n")
            (Path(directory) / "nodes.yaml").write_text("/web/api:\n  tags: [api]\n")
            os.environ["LITTLE_SISTER_CONFIG_DIR"] = directory
            self.addCleanup(os.environ.pop, "LITTLE_SISTER_CONFIG_DIR", None)

            engine = mock.Mock(checks=[check])
            app_module._seed_tags(engine, app_module._read_nodes())
        tree.upsert("/web/api", OK)
        self.assertEqual(tree.snapshot("/web/api").tags,             # type: ignore
                         ("production", "api", "edge"))
        self.assertEqual(tree.tag_vocabulary.line("production"), "Serves customers.")
        self.assertEqual(sorted(_notes()), ["tags-unknown-api", "tags-unknown-edge"])


class _Pages(TestCase):
    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        self._original = app_module.status_tree
        self.addCleanup(setattr, app_module, "status_tree", self._original)
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})
        self.tree.upsert("/servers/web01", OK)
        self.tree.upsert("/servers/web01/disk", ERROR, "97 % used",
                         description="Disk use on the host")
        self.tree.upsert("/plain", OK)
        self.tree.use_tags(
            Vocabulary({"production": "Serves customers.", "rack-4": ""}),
            {"/servers": ("production",), "/servers/web01": ("rack-4", "berlin")})

    def page(self, url: str) -> Element:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return parse(response.get_data(as_text=True))


class CardTests(_Pages):
    def test_one_line_of_chips_between_the_texts_and_the_details(self):
        card = self.page("/status/servers/web01/disk").one("ls-node-about")
        chips = card.one("ls-node-about__tags")
        self.assertEqual(chips.attrs.get("aria-label"), "Tags")
        self.assertEqual([chip.text() for chip in chips.all("ls-tag")],
                         ["production", "rack-4", "berlin"])
        self.assertLess(card.one("ls-node-about__description").order, chips.order)
        # the tooltip says what it means and where it comes down from
        self.assertEqual([chip.attrs.get("title") for chip in chips.all("ls-tag")],
                         ["Serves customers. · written on /servers",
                          "written on /servers/web01", "written on /servers/web01"])

    def test_its_own_say_what_they_mean_alone(self):
        chips = self.page("/status/servers/web01").one("ls-node-about__tags")
        self.assertEqual([chip.attrs.get("title") for chip in chips.all("ls-tag")],
                         ["Serves customers. · written on /servers", None, None])

    def test_a_node_with_tags_alone_has_its_card_and_one_without_none(self):
        page = self.page("/status/servers")
        card = page.one("ls-node-about")
        self.assertEqual([chip.text() for chip in card.all("ls-tag")], ["production"])
        self.assertEqual(self.page("/status/plain").all("ls-node-about"), [])

    def test_the_stylesheet_rules_the_details_after_the_chips(self):
        css = (Path(app_module.__file__).parent / "static" / "css"
               / "overview.css").read_text(encoding="utf-8")
        self.assertIn("border-top: 1px solid var(--ls-line)",
                      css_rule(css, ".ls-node-about__tags + .ls-node-about__details"))
        self.assertIn("flex-wrap: wrap", css_rule(css, ".ls-tags"))

    def test_the_hover_card_names_them_in_one_line(self):
        meta = app_module._node_meta_map(self.tree.snapshot("/servers"))
        self.assertEqual(meta["/servers/web01/disk"]["tags"],
                         "production rack-4 berlin")
        self.assertEqual(meta["/servers"]["tags"], "production")
        script = (Path(app_module.__file__).parent / "static" / "js"
                  / "inspect.js").read_text(encoding="utf-8")
        self.assertIn('tags.className = "ls-tags inspect-card__tags";', script)


class CopyDocumentTests(_Pages):
    def test_the_document_lists_them_with_their_lines(self):
        document = self.page("/copy/servers/web01/disk").with_id(
            "ls-copy-source").source()
        block = document.split("**Tags**\n\n", 1)[1].split("\n\n", 1)[0]
        self.assertEqual(block.splitlines(), [
            "- **production** — Serves customers.",
            "- **rack-4**",
            "- **berlin**"])
        self.assertLess(document.index("**As of:**"), document.index("**Tags**"))
        self.assertLess(document.index("**Tags**"), document.index("**Reasons**"))

    def test_a_branchs_too_and_none_without_any(self):
        document = self.page("/copy/servers").with_id("ls-copy-source").source()
        self.assertIn("**Tags**\n\n- **production** — Serves customers.", document)
        plain = self.page("/copy/plain").with_id("ls-copy-source").source()
        self.assertNotIn("**Tags**", plain)


class EnvelopeTests(_Pages):
    def test_every_tag_a_node_carries_and_none_where_it_carries_none(self):
        app_module.api_tokens = {"tester": "secret-token"}
        self.addCleanup(setattr, app_module, "api_tokens", {})
        headers = {"Accept": "application/json", "Authorization": "Bearer secret-token"}
        # a subtree read by its path says what is written above its root too
        body = self.client.get("/status/servers/web01/disk", headers=headers).get_json()
        self.assertEqual(body["status"]["tags"], ["production", "rack-4", "berlin"])
        plain = self.client.get("/status/plain", headers=headers).get_json()
        self.assertNotIn("tags", plain["status"])


class DemoTests(_Startup):
    """The demo deployment (Mode 2) tags its nodes with the tags its file names."""

    def test_every_tag_it_writes_is_known(self):
        from little_sister.checks.loader import load_checks
        from tests.demo_check import DemoCheck  # registers the demo's type
        self.assertTrue(DemoCheck.type_name)
        demo = Path(__file__).resolve().parent / "demo_config"
        checks = load_checks(demo)
        places = tag_places(checks, load_nodes(demo))
        vocabulary = tags.load_vocabulary(demo)
        self.assertEqual(sorted(places), sorted(vocabulary.lines))
        tags.note_unknown(vocabulary, places)
        self.assertEqual(_notes(), {})
