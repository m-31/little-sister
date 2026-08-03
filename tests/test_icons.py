import importlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import TestCase

import yaml

from little_sister import icons
from little_sister.icons import (
    BUILTIN_NAMES,
    BUILTIN_PACKAGE,
    Icon,
    IconFile,
    forget_packs,
    is_known,
    known_names,
    read_icon,
    register_pack,
    resolve,
)

PACK_DIR = Path(icons.__file__).parent / "icon_pack"


def make_package(directory, name, files):
    """Build an importable package with data files in it, the way a dependent
    package registering an icon pack really is, and put it on the path."""
    root = Path(directory) / name
    root.mkdir(parents=True)
    (root / "__init__.py").write_text('"""a test icon pack"""\n')
    for filename, body in files.items():
        (root / filename).write_text(body)
    if directory not in sys.path:
        sys.path.insert(0, directory)
    importlib.invalidate_caches()
    return name


class BuiltinPackTests(TestCase):
    def test_every_roster_name_resolves_to_a_pair(self):
        for name in BUILTIN_NAMES:
            with self.subTest(name=name):
                icon = resolve(name)
                self.assertIsNotNone(icon)
                assert icon is not None
                self.assertTrue(icon.paired)
                self.assertEqual(icon.on_light.package, BUILTIN_PACKAGE)
                self.assertEqual(icon.on_light.member, f"{name}-on-light.svg")
                self.assertEqual(icon.on_dark.member, f"{name}-on-dark.svg")

    def test_every_file_is_there_and_is_svg(self):
        for name in BUILTIN_NAMES:
            for variant in ("on-light", "on-dark"):
                with self.subTest(name=name, variant=variant):
                    payload, content_type = read_icon(
                        IconFile(package=BUILTIN_PACKAGE,
                                 member=f"{name}-{variant}.svg"))
                    self.assertEqual(content_type, "image/svg+xml")
                    self.assertIn(b"<svg", payload)

    def test_the_pair_differs_only_in_ink(self):
        # The two files are the same drawing; if they ever diverge, the dark theme
        # is quietly showing a different glyph from the light one.
        for name in BUILTIN_NAMES:
            with self.subTest(name=name):
                light = (PACK_DIR / f"{name}-on-light.svg").read_text()
                dark = (PACK_DIR / f"{name}-on-dark.svg").read_text()
                self.assertEqual(light.replace("#212529", "INK"),
                                 dark.replace("#e9edf1", "INK"))

    def test_the_manifest_lists_exactly_the_roster(self):
        # The manifest is the pack's provenance record (ADR-0030 §3). It is not
        # load-bearing at runtime, so this is what keeps it honest.
        manifest = yaml.safe_load((PACK_DIR / "manifest.yaml").read_text())
        self.assertEqual(sorted(manifest["icons"]), sorted(BUILTIN_NAMES))
        self.assertTrue(all(manifest["icons"].values()))
        self.assertIn("drawn for little-sister", manifest["source"])

    def test_an_undefined_name_is_an_ordinary_none(self):
        self.assertIsNone(resolve("nothing-defines-this"))
        self.assertFalse(is_known("nothing-defines-this"))

    def test_known_names_are_sorted(self):
        self.assertEqual(list(known_names()), sorted(BUILTIN_NAMES))


class RegistrationTests(TestCase):
    def setUp(self):
        self.addCleanup(forget_packs)

    def test_a_pack_adds_a_name(self):
        with tempfile.TemporaryDirectory() as directory:
            package = make_package(directory, "ls_test_pack_add",
                                   {"phoenix.svg": "<svg/>"})
            register_pack(package, {"phoenix": "phoenix.svg"})
            icon = resolve("phoenix")
            self.assertIsNotNone(icon)
            assert icon is not None
            self.assertFalse(icon.paired)        # one file → the chip
            self.assertEqual(icon.on_light, icon.on_dark)
            self.assertEqual(read_icon(icon.on_light)[0], b"<svg/>")

    def test_a_pack_may_declare_a_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            package = make_package(directory, "ls_test_pack_pair",
                                   {"a.svg": "<svg/>", "b.svg": "<svg/>"})
            register_pack(package, {"house": {"on_light": "a.svg",
                                              "on_dark": "b.svg"}})
            icon = resolve("house")
            assert icon is not None
            self.assertTrue(icon.paired)
            self.assertEqual(icon.on_dark.member, "b.svg")

    def test_a_pack_shadows_one_built_in_and_leaves_the_rest(self):
        # Per name, never wholesale (ADR-0030 §3): a house pack defining only `aws`
        # leaves the other sixteen standing.
        with tempfile.TemporaryDirectory() as directory:
            package = make_package(directory, "ls_test_pack_shadow",
                                   {"cloud.png": "not really a png"})
            with self.assertLogs("little_sister", level="INFO") as logged:
                register_pack(package, {"aws": "cloud.png"})
            self.assertTrue(any("aws" in line and BUILTIN_PACKAGE in line
                                for line in logged.output))
            aws = resolve("aws")
            assert aws is not None
            self.assertEqual(aws.on_light.package, package)
            grafana = resolve("grafana")
            assert grafana is not None
            self.assertEqual(grafana.on_light.package, BUILTIN_PACKAGE)

    def test_a_member_may_not_be_a_path(self):
        # The whole sandbox: a pack names a bare file inside its own package data,
        # so it cannot reach out of it.
        with tempfile.TemporaryDirectory() as directory:
            package = make_package(directory, "ls_test_pack_escape",
                                   {"ok.svg": "<svg/>"})
            for member in ("../ok.svg", "sub/ok.svg", "/etc/passwd", ".."):
                with self.subTest(member=member):
                    with self.assertLogs("little_sister", level="WARNING"):
                        register_pack(package, {"escape": member})
                    self.assertIsNone(resolve("escape"))

    def test_a_type_we_will_not_serve_is_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            package = make_package(directory, "ls_test_pack_type",
                                   {"notes.txt": "hello"})
            with self.assertLogs("little_sister", level="WARNING"):
                register_pack(package, {"notes": "notes.txt"})
            self.assertIsNone(resolve("notes"))

    def test_a_missing_file_is_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            package = make_package(directory, "ls_test_pack_missing", {})
            with self.assertLogs("little_sister", level="WARNING"):
                register_pack(package, {"ghost": "ghost.svg"})
            self.assertIsNone(resolve("ghost"))

    def test_an_entry_with_no_usable_file_is_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            package = make_package(directory, "ls_test_pack_empty", {})
            with self.assertLogs("little_sister", level="WARNING"):
                register_pack(package, {"hollow": {}})
            self.assertIsNone(resolve("hollow"))

    def test_an_unnamed_entry_is_skipped(self):
        with self.assertLogs("little_sister", level="WARNING"):
            register_pack(BUILTIN_PACKAGE, {"  ": "aws-on-light.svg"})
        self.assertNotIn("", known_names())

    def test_forgetting_packs_puts_the_built_ins_back(self):
        with tempfile.TemporaryDirectory() as directory:
            package = make_package(directory, "ls_test_pack_forget",
                                   {"x.svg": "<svg/>"})
            register_pack(package, {"phoenix": "x.svg"})
            forget_packs()
            self.assertIsNone(resolve("phoenix"))
            self.assertTrue(is_known("grafana"))


class ReadIconTests(TestCase):
    def test_a_deployment_file_is_read_from_its_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mark.png"
            path.write_bytes(b"\x89PNG...")
            payload, content_type = read_icon(IconFile(path=path))
            self.assertEqual(payload, b"\x89PNG...")
            self.assertEqual(content_type, "image/png")

    def test_a_remote_icon_is_never_read_here(self):
        # It is emitted as its own URL; reading it would make this instance fetch
        # whatever a config file names.
        with self.assertRaises(ValueError):
            read_icon(IconFile(url="https://example.org/mark.svg"))

    def test_a_type_we_will_not_serve_raises(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "script.py"
            path.write_text("print()")
            with self.assertRaises(ValueError):
                read_icon(IconFile(path=path))

    def test_a_missing_file_raises_an_os_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(OSError):
                read_icon(IconFile(path=Path(directory) / "gone.svg"))

    def test_file_for_picks_the_variant(self):
        icon = Icon(name="x", on_light=IconFile(url="light"),
                    on_dark=IconFile(url="dark"))
        self.assertEqual(icon.file_for("on-light").url, "light")
        self.assertEqual(icon.file_for("on-dark").url, "dark")


if __name__ == "__main__":
    unittest.main()
