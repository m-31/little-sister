import os
import tempfile
import unittest
from pathlib import Path
from unittest import TestCase

from little_sister.checks import CheckError
from little_sister.checks.http import HttpCheck
from little_sister.checks.ssh.host_metrics import DEFAULT_THRESHOLDS, HostMetricsCheck
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

    def test_unions_across_directories(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            (Path(d1) / "nodes.yaml").write_text("/a: {about: from base}\n")
            (Path(d2) / "nodes.yaml").write_text("/b: {title: from host}\n")
            meta = load_nodes(f"{d1}{os.pathsep}{d2}")
            self.assertEqual(meta["/a"].about, "from base")
            self.assertEqual(meta["/b"].title, "from host")

    def test_duplicate_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            (Path(d1) / "nodes.yaml").write_text("/a: {about: one}\n")
            (Path(d2) / "nodes.yaml").write_text("/a: {title: two}\n")
            with self.assertRaises(CheckError):
                load_nodes(f"{d1}{os.pathsep}{d2}")

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
        # strip and its hover card, #24) although no check covers the path.
        with self.assertNoLogs(level="WARNING"):
            run_consistency_pass(
                [self._http(path="/web")],
                {"/web": NodeMeta(about="ok"),
                 "/little-sister": NodeMeta(title="engine heartbeat")})


if __name__ == '__main__':
    unittest.main()
