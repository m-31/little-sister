"""A node's handbook (ADR-0133 decision 3): what states it, how a file it names is
read and against what, and what the startup record says of a statement that reads
nothing, of a file nothing names and of a link into it that leads nowhere (decision
4). Its tab, its page and its hover card's line are `test_web.py`'s; its anchors and
the short form's resolving `test_render.py`'s."""
import os
import tempfile
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import ClassVar
from unittest import TestCase, mock

from little_sister import handbooks, self_report
from little_sister.checks import Check, Measurement
from little_sister.checks.base import CheckResult
from little_sister.checks.http import HttpCheck
from little_sister.engine import Engine
from little_sister.nodes import (
    NodeMeta,
    load_nodes,
    resolve_metadata,
    run_consistency_pass,
)
from little_sister.status import StatusCode
from little_sister.tree import StatusTree

RUNBOOK = "## Sign in\n\nThrough the bastion, as yourself.\n"


def _notes() -> dict[str, str]:
    """The startup record's handbook lines, by slug."""
    return {line.slug: line.text for line in self_report.startup.lines()
            if line.slug.startswith("handbook")}


class _Recorded(TestCase):
    """Each case starts with nothing named and nothing on the startup record."""

    def setUp(self) -> None:
        handbooks.forget()
        self_report.startup.forget()
        self.addCleanup(handbooks.forget)
        self.addCleanup(self_report.startup.forget)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)


class ResolveTests(_Recorded):
    def test_a_single_line_ending_in_md_names_a_file_and_anything_else_is_text(self):
        for stated, named in (("handbook/ec2.md", True), ("  ec2.MD \n", True),
                              ("Read the runbook.md", True),
                              ("## Sign in\n\nsee ec2.md", False),
                              ("ec2.md is ours", False), ("", False),
                              ("Restart it.", False)):
            with self.subTest(stated=stated):
                self.assertIs(handbooks.names_a_file(stated), named)

    def test_text_is_the_handbook_as_written(self):
        self.assertEqual(handbooks.resolve(RUNBOOK, self.root, where="x"), RUNBOOK)
        self.assertEqual(handbooks.resolve("", self.root, where="x"), "")
        self.assertEqual(_notes(), {})

    def test_a_file_is_read_relative_to_the_directory_it_is_stated_against(self):
        (self.root / "handbook").mkdir()
        (self.root / "handbook" / "ec2.md").write_text(RUNBOOK, encoding="utf-8")
        self.assertEqual(
            handbooks.resolve("handbook/ec2.md", self.root, where="x"), RUNBOOK)
        self.assertEqual(_notes(), {})

    def test_a_missing_file_gives_no_handbook_and_a_line_that_names_it(self):
        self.assertEqual(handbooks.resolve(
            "handbook/ec2.md", self.root, where="the check /aws"), "")
        (text,) = _notes().values()
        for said in ("the check /aws", "'handbook/ec2.md'", "is not in",
                     "it gives no handbook"):
            self.assertIn(said, text)

    def test_a_file_outside_the_directory_is_not_read(self):
        # a statement names a file of its own configuration directory, or of its
        # own package, and nothing beyond it
        outside = self.root / "secret.md"
        outside.write_text("not a handbook")
        inner = self.root / "config"
        inner.mkdir()
        for stated in ("../secret.md", str(outside)):
            with self.subTest(stated=stated):
                self.assertEqual(handbooks.resolve(stated, inner, where="x"), "")
                self.assertIn("lies outside", "\n".join(_notes().values()))

    def test_a_file_that_cannot_be_read_gives_no_handbook(self):
        (self.root / "latin1.md").write_bytes(b"caf\xe9\n")
        (self.root / "folder.md").mkdir()
        for stated in ("latin1.md", "folder.md"):
            with self.subTest(stated=stated):
                self.assertEqual(handbooks.resolve(stated, self.root, where="x"), "")
        self.assertEqual(len(_notes()), 2)
        self.assertTrue(all("cannot be read" in text for text in _notes().values()))

    def test_the_directories_a_statement_is_read_against(self):
        # a check's file is in its root's checks/, and names a file of the root;
        # a type names one of the package it is defined in
        self.assertEqual(handbooks.configuration_directory(self.root / "checks"),
                         self.root)
        self.assertEqual(handbooks.package_directory(HttpCheck),
                         Path(handbooks.__file__).resolve().parent / "checks")


class UnnamedTests(_Recorded):
    def test_a_file_in_handbook_that_nothing_named_is_named(self):
        shelf = self.root / "handbook"
        (shelf / "aws").mkdir(parents=True)
        for name in ("ec2.md", "aws/lambda.md", "notes.txt"):
            (shelf / name).write_text(RUNBOOK)
        handbooks.resolve("handbook/ec2.md", self.root, where="x")
        handbooks.note_unnamed([self.root])
        (text,) = _notes().values()
        self.assertIn(str(Path("handbook") / "aws" / "lambda.md"), text)
        self.assertIn("a handbook nothing names", text)

    def test_a_root_without_handbook_says_nothing(self):
        handbooks.note_unnamed([self.root])
        self.assertEqual(_notes(), {})

    def test_a_handbook_yaml_is_named_and_does_not_stop_the_start(self):
        # a node's metadata must not stop monitoring, as a bad nodes.yaml does not
        (self.root / "handbook.yaml").write_text("/a: runbook\n")
        handbooks.note_unnamed([self.root])
        (text,) = _notes().values()
        self.assertIn("is a file, but the 'handbook' aspect is a directory", text)


class _Typed(Check):
    """A type that declares a handbook for one of its aspects, as a file its package
    ships, and one as text."""

    DEFAULTS: ClassVar[dict[str, dict[str, str]]] = {
        "ec2": {"about": "The instances.", "handbook": "ec2.md"},
        "batch": {"handbook": "Ask the batch team."}}

    def __init__(self, **kwargs: object) -> None:
        super().__init__(subnode_defaults=self.DEFAULTS,      # type: ignore[arg-type]
                         **kwargs)                            # type: ignore[arg-type]

    def measure(self) -> Measurement:
        return Measurement(record={})

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        return CheckResult(StatusCode.OK)


class CheckFileTests(_Recorded):
    def _check(self, **config: object) -> HttpCheck:
        return HttpCheck.from_config(
            {"type": "http", "path": "/web", "url": "http://x", **config},
            self.root / "checks")

    def test_its_own_nodes_handbook_is_text_or_a_file_of_its_root(self):
        (self.root / "handbook").mkdir()
        (self.root / "handbook" / "web.md").write_text(RUNBOOK)
        self.assertEqual(self._check(handbook="Restart it.").handbook, "Restart it.")
        self.assertEqual(self._check(handbook="handbook/web.md").handbook, RUNBOOK)
        self.assertEqual(self._check().handbook, "")

    def test_an_aspects_handbook_under_subnodes_is_read_the_same_way(self):
        (self.root / "handbook").mkdir()
        (self.root / "handbook" / "ec2.md").write_text(RUNBOOK)
        check = self._check(subnodes={"ec2": {"handbook": "handbook/ec2.md"},
                                      "s3": {"handbook": "Buckets: ask #storage."},
                                      "rds": {"title": "RDS"}})
        self.assertEqual(check.subnode_labels["ec2"], {"handbook": RUNBOOK})
        self.assertEqual(check.subnode_labels["s3"]["handbook"],
                         "Buckets: ask #storage.")
        self.assertNotIn("handbook", check.subnode_labels["rds"])

    def test_a_file_the_check_names_that_is_missing_is_on_the_startup_record(self):
        check = self._check(handbook="handbook/web.md",
                            subnodes={"ec2": {"handbook": "handbook/ec2.md"}})
        self.assertEqual(check.handbook, "")
        self.assertNotIn("ec2", check.subnode_labels)
        said = "\n".join(_notes().values())
        self.assertIn("the check /web names the handbook 'handbook/web.md'", said)
        self.assertIn("the check /web's subnodes.ec2 names the handbook", said)

    def test_a_type_names_a_file_of_its_package_and_default_places_it(self):
        package = self.root / "package"
        package.mkdir()
        (package / "ec2.md").write_text("The type's reference.\n")
        with mock.patch.object(handbooks, "package_directory", return_value=package):
            plain = _Typed.from_config({"type": "x", "path": "/aws"}, self.root)
            extended = _Typed.from_config(
                {"type": "x", "path": "/aws",
                 "subnodes": {"ec2": {"handbook": "## Ours\n\n{default}"},
                              "batch": {"handbook": "Replaced."}}}, self.root)
        self.assertEqual(plain.subnode_labels["ec2"]["handbook"],
                         "The type's reference.\n")
        self.assertEqual(plain.subnode_labels["batch"]["handbook"],
                         "Ask the batch team.")
        self.assertEqual(extended.subnode_labels["ec2"]["handbook"],
                         "## Ours\n\nThe type's reference.\n")
        self.assertEqual(extended.subnode_labels["batch"]["handbook"], "Replaced.")


class NodesFileTests(_Recorded):
    def test_a_handbook_is_text_or_a_file_of_the_root_the_file_is_in(self):
        (self.root / "handbook").mkdir()
        (self.root / "handbook" / "servers.md").write_text(RUNBOOK)
        (self.root / "nodes.yaml").write_text(
            "/servers: {handbook: handbook/servers.md}\n"
            "/db:\n  title: Database\n  handbook: Restart the primary first.\n")
        meta = load_nodes(self.root)
        self.assertEqual(meta["/servers"], NodeMeta(handbook=RUNBOOK))
        self.assertEqual(meta["/db"].handbook, "Restart the primary first.")

    def test_each_root_names_files_of_its_own_and_the_later_wins(self):
        site = self.root / "site"
        (site / "handbook").mkdir(parents=True)
        (site / "handbook" / "a.md").write_text("the site's")
        base = self.root / "base"
        (base / "handbook").mkdir(parents=True)
        (base / "handbook" / "a.md").write_text("the base's")
        (base / "nodes.yaml").write_text(
            "/a: {handbook: handbook/a.md, title: A}\n/b: {handbook: handbook/a.md}\n")
        (site / "nodes.yaml").write_text("/a: {handbook: handbook/a.md}\n")
        meta = load_nodes(f"{base}{os.pathsep}{site}")
        self.assertEqual(meta["/a"], NodeMeta(title="A", handbook="the site's"))
        self.assertEqual(meta["/b"].handbook, "the base's")

    def test_a_missing_file_is_named_with_the_nodes_file_and_the_path(self):
        (self.root / "nodes.yaml").write_text("/a: {handbook: handbook/a.md}\n")
        self.assertEqual(load_nodes(self.root), {})    # it states nothing else
        (text,) = _notes().values()
        self.assertIn(f"{self.root / 'nodes.yaml'} for '/a'", text)

    def test_nodes_yaml_beats_the_checks_own_handbook(self):
        def check(path: str, handbook: str) -> HttpCheck:
            return HttpCheck.from_config({"type": "http", "path": path,
                                          "url": "http://x", "handbook": handbook},
                                         self.root / "checks")

        meta = resolve_metadata([check("/web", "the check's"),
                                 check("/api", "the api's")],
                                {"/web": NodeMeta(handbook="nodes.yaml's"),
                                 "/api": NodeMeta(title="API")})
        self.assertEqual(meta["/web"].handbook, "nodes.yaml's")
        self.assertEqual(meta["/api"], NodeMeta(title="API", handbook="the api's"))


class _Branch(Check):
    """A check whose run hands its children over as it is told."""

    def __init__(self, *, result: CheckResult, **kwargs: object) -> None:
        super().__init__(**kwargs)                          # type: ignore[arg-type]
        self._result = result

    def measure(self) -> Measurement:
        return Measurement(record={})

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        return self._result


class RunTests(_Recorded):
    """What a run hands over fills a child once, beneath what is declared for its
    name and what nodes.yaml says."""

    def _run(self, result: CheckResult, tree: StatusTree | None = None,
             runs: int = 1, **kwargs: object) -> StatusTree:
        tree = tree or StatusTree()
        engine = Engine([_Branch(path="/aws", result=result, **kwargs)], tree)
        with mock.patch.object(handbooks, "package_directory",
                               return_value=self.root):
            for _ in range(runs):
                engine.run_once()
        return tree

    def test_a_childs_handbook_is_text_or_a_file_of_the_types_package(self):
        (self.root / "ec2.md").write_text(RUNBOOK)
        tree = self._run(CheckResult(StatusCode.OK, children=(
            CheckResult(StatusCode.OK, name="ec2", handbook="ec2.md"),
            CheckResult(StatusCode.OK, name="s3", handbook="Ask #storage."),
            CheckResult(StatusCode.OK, name="rds"))))
        self.assertEqual(tree.handbook("/aws/ec2"), RUNBOOK)
        self.assertEqual(tree.handbook("/aws/s3"), "Ask #storage.")
        self.assertEqual(tree.handbook("/aws/rds"), "")
        has = {child.name: child.has_handbook
               for child in tree.snapshot("/aws").children}
        self.assertEqual(has, {"ec2": True, "s3": True, "rds": False})

    def test_a_runs_file_is_read_once_and_fills_once(self):
        (self.root / "ec2.md").write_text("first")
        result = CheckResult(StatusCode.OK, children=(
            CheckResult(StatusCode.OK, name="ec2", handbook="ec2.md"),))
        with mock.patch.object(handbooks, "resolve",
                               wraps=handbooks.resolve) as read:
            tree = self._run(result, runs=3)
        self.assertEqual(read.call_count, 1)
        self.assertEqual(tree.handbook("/aws/ec2"), "first")

    def test_what_is_declared_for_the_name_and_nodes_yaml_come_first(self):
        tree = StatusTree()
        tree.set_handbook("/aws/s3", "nodes.yaml's")
        self._run(CheckResult(StatusCode.OK, children=(
            CheckResult(StatusCode.OK, name="ec2", handbook="the run's"),
            CheckResult(StatusCode.OK, name="s3", handbook="the run's"))),
            tree, subnode_labels={"ec2": {"handbook": "the file's"}})
        self.assertEqual(tree.handbook("/aws/ec2"), "the file's")
        self.assertEqual(tree.handbook("/aws/s3"), "nodes.yaml's")

    def test_a_root_takes_none_from_its_run_and_a_child_a_run_names_its_own(self):
        tree = self._run(
            CheckResult(StatusCode.OK, handbook="the root's", children=(
                CheckResult(StatusCode.OK, name="ec2", handbook="the function's",
                            dynamic=True),)),
            subnode_labels={"ec2": {"handbook": "the aspect's"}})
        self.assertEqual(tree.handbook("/aws"), "")
        self.assertEqual(tree.handbook("/aws/ec2"), "the function's")

    def test_the_types_tokens_expand_in_what_a_run_hands_a_child(self):
        # A run's labels are the type's text as much as what it declares (ADR-0133
        # decision 2), so a child no declaration can name — a severity the source
        # invents, a function a run finds — says what its declared siblings say: the
        # tokens expand in its title, its about and its handbook, a file's text too.
        # A status's sign is the page's, a name the type offers no value for stays as
        # written, and so does `{default}`, with no declared text beneath a run's.
        (self.root / "bands.md").write_text("# Bands\n\n{grading}\n\n{nobody}\n")
        tree = self._run(CheckResult(StatusCode.OK, children=(
            CheckResult(StatusCode.WARN, name="bizarre", title="{mark}",
                        about="{warn}: read {where}. {default}", handbook="bands.md"),
            CheckResult(StatusCode.OK, name="batch", handbook="Ask {where}.",
                        dynamic=True))),
            label_tokens={"grading": "Graded **WARN**.", "where": "the band",
                          "mark": "❓"})
        texts = tree.texts("/aws/bizarre")
        self.assertEqual((texts["title"], texts["about"]),
                         ("❓", "{warn}: read the band. {default}"))
        self.assertEqual(tree.handbook("/aws/bizarre"),
                         "# Bands\n\nGraded **WARN**.\n\n{nobody}\n")
        self.assertEqual(tree.handbook("/aws/batch"), "Ask the band.")

    def test_a_missing_file_a_run_names_is_on_the_startup_record(self):
        tree = self._run(CheckResult(StatusCode.OK, children=(
            CheckResult(StatusCode.OK, name="ec2", handbook="ec2.md"),)))
        self.assertEqual(tree.handbook("/aws/ec2"), "")
        (text,) = _notes().values()
        self.assertIn("the run of /aws for /aws/ec2 names the handbook 'ec2.md'",
                      text)


class StartTests(_Recorded):
    """The start seeds what the configuration states and then names what nothing
    named, once every statement has been read."""

    def _start(self, **patched: object) -> StatusTree:
        """The start's seeding over a tree of its own, its first look put back after
        it, as every other page's is."""
        from little_sister import app as app_module
        tree = StatusTree()
        engine = mock.Mock(checks=[])
        with mock.patch.object(app_module, "status_tree", tree), \
                mock.patch.object(app_module, "first_looks", None), \
                mock.patch.object(app_module, "config_roots",
                                  return_value=[self.root]), \
                mock.patch.object(app_module, "load_nodes", **patched):
            app_module._seed_node_metadata(engine)
        return tree

    def test_it_seeds_each_handbook_and_names_a_file_nothing_named(self):
        (self.root / "handbook").mkdir()
        (self.root / "handbook" / "named.md").write_text(RUNBOOK)
        (self.root / "handbook" / "orphan.md").write_text(RUNBOOK)
        handbooks.resolve("handbook/named.md", self.root, where="x")
        tree = self._start(return_value={"/a": NodeMeta(handbook=RUNBOOK)})
        self.assertEqual(tree.handbook("/a"), RUNBOOK)
        (text,) = _notes().values()
        self.assertIn("orphan.md", text)

    def test_a_nodes_yaml_that_was_not_read_names_none(self):
        # the files it names would be named as nobody's
        from little_sister.errors import CheckError
        (self.root / "handbook").mkdir()
        (self.root / "handbook" / "orphan.md").write_text(RUNBOOK)
        self._start(side_effect=CheckError("bad entry"))
        self.assertEqual(_notes(), {})


#: A handbook whose sections the links below lead to, or do not.
SECTIONED = ("## Sign in\n\nAs yourself.\n\n## When it fails\n\n"
             "### {error}: no answers\n\nRestart it.\n\n## Über uns\n")


class LinkTests(_Recorded):
    """A link a node's texts write in the short form that leads nowhere is on the
    startup record (ADR-0133 decision 4): to a section the node's handbook does not
    have, or on a node that has none — one line for each text and target."""

    def test_a_section_the_handbook_has_is_no_line_and_one_it_lacks_is(self):
        handbooks.note_links("/web", {
            "about": ("[Sign in](handbook#sign-in), [top](handbook), "
                      "[no answers](handbook#error-no-answers), "
                      "[ü](handbook#über-uns)"),
            "description": "Reads /health: [what to do](handbook#when-it-fail)."},
            SECTIONED)
        (text,) = _notes().values()
        for said in ("the description of '/web' links handbook#when-it-fail",
                     "a section its handbook does not have"):
            self.assertIn(said, text)

    def test_a_link_on_a_node_without_a_handbook_is_a_line(self):
        handbooks.note_links("/web", {"about": "See [the runbook](handbook).",
                                      "title": "Web"}, "")
        (text,) = _notes().values()
        self.assertIn("the about of '/web' links handbook, but no handbook is written "
                      "for the node", text)

    def test_a_handbook_that_links_a_section_it_lacks(self):
        text = SECTIONED + "\n[Back to signing in](handbook#sign-inn)\n"
        handbooks.note_links("/web", {"handbook": text}, text)
        (said,) = _notes().values()
        self.assertIn("the handbook of '/web' links handbook#sign-inn, a section it "
                      "does not have", said)

    def test_a_text_is_read_as_the_page_renders_it(self):
        # code, an escape and an indented block are no link on the page and none
        # here; a title is rendered on one line, where indentation makes no block
        handbooks.note_links("/web", {
            "about": "`[a](handbook#nowhere)` \\[b](handbook#nowhere)\n\n"
                     "    [c](handbook#nowhere)",
            "title": "    [d](handbook#nowhere)"}, SECTIONED)
        (said,) = _notes().values()
        self.assertIn("the title of '/web' links handbook#nowhere", said)

    def test_each_text_and_target_is_one_line(self):
        handbooks.note_links("/web", {
            "about": "[a](handbook#x) and [b](handbook#x), [c](handbook#y)",
            "description": "[d](handbook#x)"}, SECTIONED)
        self.assertEqual(len(_notes()), 3)

    def test_the_start_looks_at_a_checks_own_node_and_the_nodes_above_it(self):
        check = HttpCheck.from_config(
            {"type": "http", "path": "/svc/web", "url": "http://x",
             "description": "Reads /health: [what to do](handbook#sign-in).",
             "about": "[top](handbook) and [nowhere](handbook#nowhere)",
             "handbook": "## Sign in\n"}, self.root / "checks")
        metadata = resolve_metadata([check], {
            "/svc": NodeMeta(about="[Whom to call](handbook#who-to-call)"),
            "/svc/web/disk": NodeMeta(about="[x](handbook#nowhere)"),
            "/elsewhere": NodeMeta(about="[x](handbook#nowhere)")})
        run_consistency_pass([check], metadata)
        said = "\n".join(_notes().values())
        self.assertIn("the about of '/svc' links handbook#who-to-call, but no "
                      "handbook is written for the node", said)
        self.assertIn("the about of '/svc/web' links handbook#nowhere, a section",
                      said)
        # its description's section is there; a node beneath the check's own is
        # looked at when a run first fills it; an orphan's text is shown nowhere
        self.assertEqual(len(_notes()), 2)

    def test_a_node_beneath_a_check_is_looked_at_once_when_a_run_first_fills_it(self):
        tree = StatusTree()
        tree.set_about("/aws/s3", "Buckets: [what to do](handbook#when-it-fails).")
        engine = Engine([_Branch(
            path="/aws", result=CheckResult(StatusCode.OK, children=(
                CheckResult(StatusCode.OK, name="ec2"),
                CheckResult(StatusCode.OK, name="s3"),
                CheckResult(StatusCode.OK, name="rds", handbook="## Yes\n",
                            description="Reads [it](handbook#no)."))),
            subnode_labels={"ec2": {"handbook": SECTIONED,
                                    "about": "[Restart it](handbook#when-it-fails)"}})],
            tree)
        with mock.patch.object(handbooks, "note_links",
                               wraps=handbooks.note_links) as looked:
            for _ in range(3):
                engine.run_once()
        self.assertEqual(sorted(call.args[0] for call in looked.call_args_list),
                         ["/aws/ec2", "/aws/rds", "/aws/s3"])
        said = "\n".join(_notes().values())
        self.assertIn("the about of '/aws/s3' links handbook#when-it-fails, but no "
                      "handbook is written for the node", said)
        self.assertIn("the description of '/aws/rds' links handbook#no, a section",
                      said)
        self.assertEqual(len(_notes()), 2)
