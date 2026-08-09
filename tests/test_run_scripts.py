"""The run-script user-list preflight mirrors the users aspect contract."""

import os
import subprocess
import tempfile
from pathlib import Path
from unittest import TestCase

_REPO = Path(__file__).resolve().parents[1]


def _resolve(spec: str,
             retired: str | None = None) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["LITTLE_SISTER_CONFIG_DIR"] = spec
    environment.pop("LITTLE_SISTER_USERS", None)
    if retired is not None:
        environment["LITTLE_SISTER_USERS"] = retired
    return subprocess.run(
        ["bash", "-c", ". ./lib.sh; resolve_users_document"],
        cwd=_REPO,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
    )


class StartScriptUsersTests(TestCase):
    def test_accepts_the_flat_file_form(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "users.yaml"
            document.write_text("pan: {}\n", encoding="utf-8")

            completed = _resolve(str(root))

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), str(document))

    def test_accepts_the_directory_form(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            aspect = root / "users"
            aspect.mkdir()
            document = aspect / "users.yml"
            document.write_text("pan: {}\n", encoding="utf-8")

            completed = _resolve(str(root))

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), str(document))

    def test_the_first_root_declaring_users_wins(self):
        with (tempfile.TemporaryDirectory() as first_directory,
              tempfile.TemporaryDirectory() as second_directory):
            first = Path(first_directory)
            second = Path(second_directory)
            document = second / "users.yaml"
            document.write_text("pan: {}\n", encoding="utf-8")

            completed = _resolve(os.pathsep.join((str(first), str(second))))

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), str(document))

    def test_refuses_the_retired_override(self):
        """Even when it names the very file the roots would have chosen (ADR-0046)."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "users.yaml"
            document.write_text("pan: {}\n", encoding="utf-8")

            completed = _resolve(str(root), str(document))

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("no longer read", completed.stderr)

    def test_rejects_a_root_that_is_not_there(self):
        with tempfile.TemporaryDirectory() as directory:
            completed = _resolve(str(Path(directory) / "missing-config"))

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("not found", completed.stderr)

    def test_rejects_both_aspect_forms_in_one_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "users").mkdir()
            (root / "users" / "users.yaml").write_text(
                "pan: {}\n", encoding="utf-8")
            (root / "users.yaml").write_text("pan: {}\n", encoding="utf-8")

            completed = _resolve(str(root))

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("occurs more than once", completed.stderr)

    def test_rejects_a_directory_without_exactly_one_document(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            aspect = root / "users"
            aspect.mkdir()

            missing = _resolve(str(root))
            (aspect / "users.yaml").write_text("pan: {}\n", encoding="utf-8")
            (aspect / "users.yml").write_text("pan: {}\n", encoding="utf-8")
            duplicate = _resolve(str(root))

            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("needs users.yaml or users.yml", missing.stderr)
            self.assertNotEqual(duplicate.returncode, 0)
            self.assertIn("contains both", duplicate.stderr)
