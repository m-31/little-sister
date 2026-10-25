import os
import tempfile
import unittest
from pathlib import Path
from unittest import TestCase

from little_sister import self_report
from little_sister.checks.http import HttpCheck
from little_sister.checks.metadata import Stated
from little_sister.checks.ssh.host_metrics import HostMetricsCheck
from little_sister.errors import CheckError, ConfigError
from little_sister.nodes import (
    ABOUT_NOTED_PAST,
    DESCRIPTION_NOTED_PAST,
    NodeMeta,
    load_nodes,
    resolve_metadata,
    run_consistency_pass,
)

HERE = Path(".")


class LoadNodesTests(TestCase):
    def test_loads_about_title_nested_and_bare(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "nodes.yaml").write_text(
                "/system/alpha:\n"
                "  about: A NUC in the cupboard.\n"
                "  title: Living-room NUC\n"
                "/payments: just a bare about string\n")
            meta = load_nodes(base)
            self.assertEqual(meta["/system/alpha"],
                             NodeMeta(about="A NUC in the cupboard.",
                                      title="Living-room NUC"))
            self.assertEqual(meta["/payments"],
                             NodeMeta(about="just a bare about string"))

    def test_title_only_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "nodes.yaml").write_text("/nexus: {title: Nexus NAS}\n")
            self.assertEqual(load_nodes(Path(directory)),
                             {"/nexus": NodeMeta(title="Nexus NAS")})

    def test_order_is_read_and_a_stated_zero_survives(self):
        # `order: 0` is the deployment overruling a rank the check declared
        # (ADR-0055), so it must reach the tree — an absent key must not.
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "nodes.yaml").write_text(
                "/wiz/critical: {order: -2}\n"
                "/wiz/informational: {order: 0}\n"
                "/wiz/low: {about: nothing urgent}\n")
            meta = load_nodes(Path(directory))
            self.assertEqual(meta["/wiz/critical"].order, -2)
            self.assertEqual(meta["/wiz/informational"].order, 0)
            self.assertIsNone(meta["/wiz/low"].order)

    def test_order_only_entry_is_kept(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "nodes.yaml").write_text("/nexus: {order: 3}\n")
            self.assertEqual(load_nodes(Path(directory)),
                             {"/nexus": NodeMeta(order=3)})

    def test_a_non_numeric_order_is_refused(self):
        # Silently ignoring it would leave the row in an order nobody chose.
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "nodes.yaml").write_text("/nexus: {order: soon}\n")
            with self.assertRaises(CheckError) as caught:
                load_nodes(Path(directory))
            self.assertIn("order", str(caught.exception))
            self.assertIn("whole number", str(caught.exception))

    def test_show_when_quiet_is_read_and_a_stated_false_survives(self):
        # The tri-state (ADR-0063): a stated `false` is a deployment declining a
        # claim a check type ships, so it has to occupy the field; an absent key
        # must stay unstated, or every entry becomes a declaration.
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "nodes.yaml").write_text(
                "/aws/ec2: {show_when_quiet: true}\n"
                "/aws/cloudwatch: {show_when_quiet: false}\n"
                "/aws/batch: {about: nothing special}\n")
            meta = load_nodes(Path(directory))
            self.assertIs(meta["/aws/ec2"].show_when_quiet, True)
            self.assertIs(meta["/aws/cloudwatch"].show_when_quiet, False)
            self.assertIsNone(meta["/aws/batch"].show_when_quiet)

    def test_a_show_when_quiet_only_entry_is_kept(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "nodes.yaml").write_text(
                "/nexus: {show_when_quiet: false}\n")
            self.assertEqual(load_nodes(Path(directory)),
                             {"/nexus": NodeMeta(show_when_quiet=False)})

    def test_a_non_boolean_show_when_quiet_is_refused(self):
        # `bool("false")` is True, so coercing a quoted YAML boolean would switch
        # the node **on** while the file says off, and nothing could notice.
        for stated in ('"false"', "yes please", "1"):
            with self.subTest(stated=stated):
                with tempfile.TemporaryDirectory() as directory:
                    (Path(directory) / "nodes.yaml").write_text(
                        f"/nexus: {{show_when_quiet: {stated}}}\n")
                    with self.assertRaises(CheckError) as caught:
                        load_nodes(Path(directory))
                    self.assertIn("show_when_quiet", str(caught.exception))
                    self.assertIn("true or false", str(caught.exception))

    def test_a_later_root_may_state_show_when_quiet_false_over_a_declared_base(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            (Path(d1) / "nodes.yaml").write_text(
                "/a: {about: base, show_when_quiet: true}\n")
            (Path(d2) / "nodes.yaml").write_text("/a: {show_when_quiet: false}\n")
            meta = load_nodes(f"{d1}{os.pathsep}{d2}")
            self.assertEqual(meta["/a"],
                             NodeMeta(about="base", show_when_quiet=False))

    def test_a_later_root_silent_on_show_when_quiet_keeps_the_base(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            (Path(d1) / "nodes.yaml").write_text("/a: {show_when_quiet: true}\n")
            (Path(d2) / "nodes.yaml").write_text("/a: {title: site title}\n")
            meta = load_nodes(f"{d1}{os.pathsep}{d2}")
            self.assertEqual(meta["/a"],
                             NodeMeta(title="site title", show_when_quiet=True))

    def test_a_later_root_may_state_order_zero_over_a_ranked_base(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            (Path(d1) / "nodes.yaml").write_text("/a: {about: base, order: 4}\n")
            (Path(d2) / "nodes.yaml").write_text("/a: {order: 0}\n")
            meta = load_nodes(f"{d1}{os.pathsep}{d2}")
            self.assertEqual(meta["/a"], NodeMeta(about="base", order=0))

    def test_unions_across_roots(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            (Path(d1) / "nodes.yaml").write_text("/a: {about: from base}\n")
            (Path(d2) / "nodes.yaml").write_text("/b: {title: from host}\n")
            meta = load_nodes(f"{d1}{os.pathsep}{d2}")
            self.assertEqual(meta["/a"].about, "from base")
            self.assertEqual(meta["/b"].title, "from host")

    def test_later_root_wins_per_field(self):
        # Layering is the point (ADR-0031): a site root retitles a node the shared
        # base declares, and the fields it stays quiet about keep the base's values.
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            (Path(d1) / "nodes.yaml").write_text(
                "/a: {about: from base, title: base title}\n")
            (Path(d2) / "nodes.yaml").write_text("/a: {title: site title}\n")
            meta = load_nodes(f"{d1}{os.pathsep}{d2}")
            self.assertEqual(meta["/a"],
                             NodeMeta(about="from base", title="site title"))

    def test_missing_root_is_fatal(self):
        with self.assertRaises(ConfigError):
            load_nodes(Path(tempfile.gettempdir()) / "little-sister-no-such-root")

    def test_missing_nodes_file_is_fine(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(load_nodes(Path(directory)), {})

    # How a node first looks (ADR-0128): the same keys and `children:` per path,
    # read the same way, never seeded onto the tree.

    def test_the_first_looks_keys_and_children_are_read_per_path(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "nodes.yaml").write_text(
                "/network: {chips: true}\n"
                "/aws:\n"
                "  fold_ok: false\n"
                "  reason_cap: 3\n"
                "  children: {chips: true, show_when_quiet: true}\n")
            meta = load_nodes(Path(directory))
            self.assertEqual(meta["/network"], NodeMeta(look=Stated(chips=True)))
            self.assertEqual(meta["/aws"].look, Stated(
                fold_ok=False, reason_cap=3,
                children=Stated(chips=True, show_when_quiet=True)))

    def test_an_entry_that_says_only_how_it_looks_is_kept(self):
        # an entry with none of the keys is dropped as a stray; these are keys
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "nodes.yaml").write_text(
                "/a: {children: {fold_ok: false}}\n/b: {reason_cap: 0}\n")
            self.assertEqual(set(load_nodes(Path(directory))), {"/a", "/b"})

    def test_a_value_of_the_wrong_kind_refuses_the_file(self):
        for line, named in (("/a: {chips: 'yes'}", "/a.chips"),
                            ("/a: {fold_ok: 1}", "/a.fold_ok"),
                            ("/a: {reason_cap: -1}", "reason_cap must be >= 0"),
                            ("/a: {reason_cap: lots}", "/a.reason_cap"),
                            ("/a: {children: [chips]}", "/a.children must be"),
                            ("/a: {children: {show_when_quiet: 'no'}}",
                             "/a.children.show_when_quiet")):
            with self.subTest(line), tempfile.TemporaryDirectory() as directory:
                (Path(directory) / "nodes.yaml").write_text(line + "\n")
                with self.assertRaises(CheckError) as caught:
                    load_nodes(Path(directory))
                self.assertIn(named, str(caught.exception))
                self.assertIn("nodes.yaml", str(caught.exception))

    def test_a_later_root_layers_the_look_per_key_children_too(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            (Path(d1) / "nodes.yaml").write_text(
                "/a: {chips: true, children: {chips: true, fold_ok: true}}\n")
            (Path(d2) / "nodes.yaml").write_text(
                "/a: {fold_ok: true, children: {chips: false}}\n")
            meta = load_nodes(f"{d1}{os.pathsep}{d2}")
            self.assertEqual(meta["/a"].look, Stated(
                chips=True, fold_ok=True,
                children=Stated(chips=False, fold_ok=True)))

    def test_keys_no_entry_knows_are_named_in_one_line_for_the_file(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "nodes.yaml").write_text(
                "/a: {chip: true, about: kept}\n"
                "/b: {children: {flod_ok: true, children: {chips: true}}}\n"
                "/c: {title: quiet}\n")
            with self.assertLogs("little_sister.logger", "WARNING") as logged:
                meta = load_nodes(Path(directory))
            self.assertEqual(len(logged.records), 1)
            line = logged.records[0].getMessage()
            self.assertIn("nodes.yaml", line)
            self.assertIn("/a.chip, /b.children.flod_ok, /b.children.children",
                          line)
            # what the entries say that is known still loads, and an entry that
            # said only what nothing reads says nothing
            self.assertEqual(meta["/a"], NodeMeta(about="kept"))
            self.assertNotIn("/b", meta)

    def test_a_file_whose_keys_are_all_known_says_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "nodes.yaml").write_text(
                "/a: {about: x, title: y, order: 1, show_when_quiet: true, "
                "chips: true, fold_ok: false, reason_cap: 2, "
                "children: {chips: true, fold_ok: true, reason_cap: 1, "
                "show_when_quiet: false}}\n")
            with self.assertNoLogs("little_sister.logger", "WARNING"):
                load_nodes(Path(directory))


class ResolveMetadataTests(TestCase):
    def _http(self, **config):
        return HttpCheck.from_config({"type": "http", "url": "http://x", **config},
                                     HERE)

    def test_nodes_yaml_overrides_inline_per_field(self):
        check = self._http(path="/web", about="inline about", title="inline title")
        meta = resolve_metadata([check], {"/web": NodeMeta(title="declared title")})
        # title from nodes.yaml; about falls back to the inline value (per field)
        self.assertEqual(meta["/web"],
                         NodeMeta(about="inline about", title="declared title"))

    def test_an_inline_order_is_read_and_nodes_yaml_still_wins(self):
        # `order` sits beside the `title:`/`about:` a deployment writes for the same
        # node, with the same per-field precedence (ADR-0055). Before this it was
        # loaded and silently dropped.
        check = self._http(path="/web", title="inline title", order=2)
        self.assertEqual(resolve_metadata([check], {}),
                         {"/web": NodeMeta(title="inline title", order=2)})
        meta = resolve_metadata([check], {"/web": NodeMeta(order=7)})
        self.assertEqual(meta["/web"], NodeMeta(title="inline title", order=7))

    def test_an_inline_order_of_zero_is_a_declaration_not_silence(self):
        check = self._http(path="/web", order=0)
        self.assertEqual(resolve_metadata([check], {})["/web"].order, 0)

    def test_a_check_with_only_an_order_still_reaches_the_map(self):
        # The map used to be keyed on "has a label"; an order-only check would have
        # fallen out of it entirely.
        check = self._http(path="/web", order=-1)
        self.assertEqual(resolve_metadata([check], {}), {"/web": NodeMeta(order=-1)})

    def test_no_order_anywhere_stays_unstated(self):
        check = self._http(path="/web", title="inline title")
        self.assertIsNone(resolve_metadata([check], {})["/web"].order)

    def test_an_inline_show_when_quiet_is_read_and_nodes_yaml_still_wins(self):
        check = self._http(path="/aws/ec2", title="EC2", show_when_quiet=True)
        self.assertEqual(resolve_metadata([check], {}),
                         {"/aws/ec2": NodeMeta(title="EC2", show_when_quiet=True)})
        meta = resolve_metadata([check],
                                {"/aws/ec2": NodeMeta(show_when_quiet=False)})
        self.assertEqual(meta["/aws/ec2"],
                         NodeMeta(title="EC2", show_when_quiet=False))

    def test_a_declared_false_beats_an_inline_true(self):
        # The sentence the tri-state exists for: `false` is not "unstated", so a
        # deployment can take back what the check declared (ADR-0063).
        check = self._http(path="/aws/ec2", show_when_quiet=True)
        meta = resolve_metadata([check],
                                {"/aws/ec2": NodeMeta(show_when_quiet=False)})
        self.assertIs(meta["/aws/ec2"].show_when_quiet, False)

    def test_a_check_with_only_show_when_quiet_still_reaches_the_map(self):
        check = self._http(path="/aws/ec2", show_when_quiet=False)
        self.assertEqual(resolve_metadata([check], {}),
                         {"/aws/ec2": NodeMeta(show_when_quiet=False)})

    def test_no_show_when_quiet_anywhere_stays_unstated(self):
        check = self._http(path="/web", title="inline title")
        self.assertIsNone(resolve_metadata([check], {})["/web"].show_when_quiet)

    def test_inline_used_when_no_declaration(self):
        check = self._http(path="/web", title="inline title")
        self.assertEqual(resolve_metadata([check], {}),
                         {"/web": NodeMeta(title="inline title")})


class ConsistencyPassTests(TestCase):
    def _http(self, **config):
        return HttpCheck.from_config({"type": "http", "url": "http://x", **config},
                                     HERE)

    def test_warns_on_orphan_declaration(self):
        with self.assertLogs(level="WARNING") as logs:
            run_consistency_pass([self._http(path="/web")],
                                 {"/web": NodeMeta(about="ok"),
                                  "/ghost": NodeMeta(title="orphan")})
        joined = "\n".join(logs.output)
        self.assertIn("ghost", joined)
        self.assertNotIn("'/web'", joined)         # web is covered

    def test_a_show_when_quiet_only_orphan_still_warns(self):
        # An entry stating only this field is a declaration like any other, so the
        # startup pass must still say when no check covers its path (ADR-0063).
        with self.assertLogs(level="WARNING") as logs:
            run_consistency_pass([self._http(path="/web")],
                                 {"/ghost": NodeMeta(show_when_quiet=True)})
        self.assertIn("ghost", "\n".join(logs.output))

    def test_info_logs_container_without_about(self):
        with self.assertLogs(level="INFO") as logs:
            run_consistency_pass([self._http(path="/system/alpha")], {})
        self.assertIn("system", "\n".join(logs.output))

    def test_branch_root_counts_as_a_container(self):
        host = HostMetricsCheck(path="/nexus", host="h", script_path="x")
        with self.assertLogs(level="INFO") as logs:
            run_consistency_pass([host], {})
        self.assertIn("nexus", "\n".join(logs.output))

    def test_an_about_past_400_characters_is_noted(self):
        # A node's About card shows its about on its Status tab (ADR-0133
        # decision 1): a short account, a sentence or a few. One past about 400
        # characters, some four lines at a desk's width, is named at startup as an
        # orphan is — the node and its length, and where the rest can go.
        self_report.startup.forget()
        self.addCleanup(self_report.startup.forget)
        about = "word " * 80 + "w"                    # 401 characters
        self.assertEqual(len(about), 401)
        with self.assertLogs(level="WARNING") as logs:
            run_consistency_pass([self._http(path="/web")],
                                 {"/web": NodeMeta(about=about)})
        (line,) = self_report.startup.lines()
        self.assertEqual(line.slug, "nodes-long-about-web")
        for said in ("'/web'", "401 characters", "behind a link", "handbook"):
            self.assertIn(said, line.text)
        self.assertIn("'/web'", "\n".join(logs.output))

    def test_an_about_of_400_characters_is_not(self):
        self_report.startup.forget()
        self.addCleanup(self_report.startup.forget)
        self.assertEqual(ABOUT_NOTED_PAST, 400)
        with self.assertNoLogs(level="WARNING"):
            run_consistency_pass([self._http(path="/web")],
                                 {"/web": NodeMeta(about="w" * 400)})
        self.assertEqual(self_report.startup.lines(), ())

    def test_a_long_about_on_a_container_no_check_owns_is_noted_too(self):
        # nodes.yaml reaches the containers no check owns, which is where a
        # team's page stands: its about is said there as on any node
        self_report.startup.forget()
        self.addCleanup(self_report.startup.forget)
        with self.assertLogs(level="WARNING"):
            run_consistency_pass([self._http(path="/team/web")],
                                 {"/team": NodeMeta(about="x" * 612)})
        (line,) = self_report.startup.lines()
        self.assertIn("'/team'", line.text)
        self.assertIn("612 characters", line.text)

    def test_an_orphans_long_about_is_said_by_its_orphan_line_alone(self):
        # shown nowhere, it is no account of a node to keep short
        self_report.startup.forget()
        self.addCleanup(self_report.startup.forget)
        with self.assertLogs(level="WARNING"):
            run_consistency_pass([self._http(path="/web")],
                                 {"/ghost": NodeMeta(about="x" * 612)})
        self.assertEqual([line.slug for line in self_report.startup.lines()],
                         ["nodes-orphan-ghost"])

    def test_a_checks_description_past_160_characters_is_noted(self):
        # A description says what the check reads or checks, in a sentence, first
        # in the node's About card (ADR-0133 decision 2): one past about 160
        # characters is named as a long about is, with where the rest belongs.
        self_report.startup.forget()
        self.addCleanup(self_report.startup.forget)
        description = "word " * 32 + "w"            # 161 characters
        self.assertEqual(len(description), 161)
        with self.assertLogs(level="WARNING") as logs:
            run_consistency_pass([self._http(path="/web", description=description)],
                                 {})
        (line,) = self_report.startup.lines()
        self.assertEqual(line.slug, "nodes-long-description-web")
        for said in ("'/web'", "161 characters", "one sentence", "about",
                     "handbook"):
            self.assertIn(said, line.text)
        self.assertIn("'/web'", "\n".join(logs.output))

    def test_a_description_of_160_characters_is_not(self):
        self_report.startup.forget()
        self.addCleanup(self_report.startup.forget)
        self.assertEqual(DESCRIPTION_NOTED_PAST, 160)
        with self.assertNoLogs(level="WARNING"):
            run_consistency_pass([self._http(path="/web", description="w" * 160)],
                                 {})
        self.assertEqual(self_report.startup.lines(), ())

    def test_heartbeat_declaration_is_not_an_orphan(self):
        # Titling the engine's heartbeat is legitimate (it feeds the status
        # strip and its hover card, ADR-0056) although no check covers the path.
        with self.assertNoLogs(level="WARNING"):
            run_consistency_pass(
                [self._http(path="/web")],
                {"/web": NodeMeta(about="ok"),
                 "/little-sister": NodeMeta(title="engine heartbeat")})


if __name__ == '__main__':
    unittest.main()
