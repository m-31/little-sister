import os
import tempfile
import unittest
from pathlib import Path
from unittest import TestCase

from little_sister.checks.http import HttpCheck
from little_sister.checks.ssh.host_metrics import DEFAULT_THRESHOLDS, HostMetricsCheck
from little_sister.errors import CheckError, ConfigError
from little_sister.nodes import (
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

    def test_info_logs_container_without_about(self):
        with self.assertLogs(level="INFO") as logs:
            run_consistency_pass([self._http(path="/system/alpha")], {})
        self.assertIn("system", "\n".join(logs.output))

    def test_branch_root_counts_as_a_container(self):
        host = HostMetricsCheck(path="/nexus", host="h",
                                script_path="x", thresholds=DEFAULT_THRESHOLDS)
        with self.assertLogs(level="INFO") as logs:
            run_consistency_pass([host], {})
        self.assertIn("nexus", "\n".join(logs.output))

    def test_heartbeat_declaration_is_not_an_orphan(self):
        # Titling the engine's heartbeat is legitimate (it feeds the status
        # strip and its hover card, ADR-0024) although no check covers the path.
        with self.assertNoLogs(level="WARNING"):
            run_consistency_pass(
                [self._http(path="/web")],
                {"/web": NodeMeta(about="ok"),
                 "/little-sister": NodeMeta(title="engine heartbeat")})


if __name__ == '__main__':
    unittest.main()
