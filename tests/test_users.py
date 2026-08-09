"""The users aspect's two forms and per-user avatar resolution (ADR-0045)."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import TestCase

from little_sister.errors import ConfigError
from little_sister.users import load_users, read_avatar

_REPO = Path(__file__).resolve().parents[1]
_FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "config"


def _write_users(path: Path, avatar: str | None = None) -> None:
    avatar_line = f"  avatar: {avatar}\n" if avatar is not None else ""
    path.write_text(
        "pan:\n"
        "  firstname: Peter\n"
        "  lastname: Pan\n"
        "  password: 12345678\n"
        f"{avatar_line}",
        encoding="utf-8",
    )


class UsersAspectTests(TestCase):
    def test_the_flat_form_keeps_working_with_the_default_avatar(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "users.yaml"
            _write_users(document)

            config = load_users(config_dir=root)

            self.assertEqual(config.document, document)
            self.assertEqual(config.users["pan"]["firstname"], "Peter")
            self.assertEqual(config.avatars, {})

    def test_the_directory_form_resolves_an_extensionless_avatar(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            aspect = root / "users"
            avatars = aspect / "avatars"
            avatars.mkdir(parents=True)
            document = aspect / "users.yaml"
            _write_users(document, "pan")
            picture = avatars / "pan.svg"
            picture.write_text("<svg/>", encoding="utf-8")

            config = load_users(config_dir=root)

            avatar = config.avatars["pan"]
            self.assertEqual(avatar.path, picture.resolve())
            self.assertEqual(avatar.content_type, "image/svg+xml")
            self.assertEqual(read_avatar(avatar), b"<svg/>")

    def test_an_explicit_extension_selects_that_exact_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            aspect = root / "users"
            avatars = aspect / "avatars"
            avatars.mkdir(parents=True)
            _write_users(aspect / "users.yaml", "pan.webp")
            (avatars / "pan.png").write_bytes(b"png")
            chosen = avatars / "pan.webp"
            chosen.write_bytes(b"webp")

            avatar = load_users(config_dir=root).avatars["pan"]

            self.assertEqual(avatar.path, chosen.resolve())
            self.assertEqual(avatar.content_type, "image/webp")

    def test_a_users_only_root_named_first_pins_one_exact_file(self):
        """What the retired single-file override spelled, said in the path-list."""
        with (tempfile.TemporaryDirectory() as first_directory,
              tempfile.TemporaryDirectory() as second_directory):
            first = Path(first_directory)
            aspect = first / "users"
            avatars = aspect / "avatars"
            avatars.mkdir(parents=True)
            document = aspect / "users.yaml"
            _write_users(document, "captain.png")
            picture = avatars / "captain.png"
            picture.write_bytes(b"picture")
            second = Path(second_directory)
            _write_users(second / "users.yaml")

            with self.assertLogs(level="WARNING") as logs:
                config = load_users(
                    os.pathsep.join((str(first), str(second))))

            self.assertEqual(config.document, document)
            self.assertEqual(config.avatars["pan"].path, picture.resolve())
            self.assertTrue(any("the first wins whole" in line
                                for line in logs.output))

    def test_an_avatar_on_the_flat_aspect_warns_and_uses_the_default(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_users(root / "users.yaml", "pan")

            with self.assertLogs(level="WARNING") as logs:
                config = load_users(config_dir=root)

            self.assertEqual(config.avatars, {})
            self.assertTrue(any("directory form" in line for line in logs.output))

    def test_a_missing_or_unsupported_avatar_warns_and_uses_the_default(self):
        for name, phrase in (("missing", "found no supported image"),
                             ("pan.txt", "not a supported image type")):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                aspect = root / "users"
                (aspect / "avatars").mkdir(parents=True)
                _write_users(aspect / "users.yaml", name)

                with self.assertLogs(level="WARNING") as logs:
                    config = load_users(config_dir=root)

                self.assertEqual(config.avatars, {})
                self.assertTrue(any(phrase in line for line in logs.output))

    def test_an_ambiguous_stem_needs_its_extension(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            aspect = root / "users"
            avatars = aspect / "avatars"
            avatars.mkdir(parents=True)
            _write_users(aspect / "users.yaml", "pan")
            (avatars / "pan.png").write_bytes(b"png")
            (avatars / "pan.svg").write_text("<svg/>", encoding="utf-8")

            with self.assertLogs(level="WARNING") as logs:
                config = load_users(config_dir=root)

            self.assertEqual(config.avatars, {})
            self.assertTrue(any("ambiguous" in line and "add the extension" in line
                                for line in logs.output))

    def test_an_avatar_reference_cannot_walk_out_of_its_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            aspect = root / "users"
            (aspect / "avatars").mkdir(parents=True)
            _write_users(aspect / "users.yaml", "../secret.png")
            (aspect / "secret.png").write_bytes(b"secret")

            with self.assertLogs(level="WARNING") as logs:
                config = load_users(config_dir=root)

            self.assertEqual(config.avatars, {})
            self.assertTrue(any("not a bare file name" in line
                                for line in logs.output))

    def test_the_directory_form_needs_exactly_one_users_document(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            aspect = root / "users"
            aspect.mkdir()
            with self.assertRaises(FileNotFoundError):
                load_users(config_dir=root)

            _write_users(aspect / "users.yaml")
            _write_users(aspect / "users.yml")
            with self.assertRaises(ConfigError):
                load_users(config_dir=root)

    def test_the_user_document_must_be_a_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "users.yaml").write_text("- pan\n", encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_users(config_dir=root)


class RetiredOverrideTests(TestCase):
    """`LITTLE_SISTER_USERS` is refused at startup, never ignored (ADR-0046).

    In a subprocess because the refusal is part of importing the app: what has to be
    pinned is that a deployment which upgrades with the variable still set **stops**,
    not merely that a function would have raised if something called it.
    """

    def test_importing_the_app_refuses_while_the_variable_is_set(self):
        environment = os.environ.copy()
        environment["LITTLE_SISTER_CONFIG_DIR"] = os.pathsep.join(
            (str(_FIXTURE_ROOT), str(_REPO / "config")))
        environment["LITTLE_SISTER_ENGINE"] = "0"
        environment["SECRET_KEY"] = "retired-override"
        # Deliberately a *usable* file: the refusal is not "that path is broken", it
        # is "this name no longer decides anything and must not look as if it does".
        environment["LITTLE_SISTER_USERS"] = str(
            _FIXTURE_ROOT / "users" / "users.yaml")

        completed = subprocess.run(
            [sys.executable, "-c", "import little_sister.app"],
            cwd=_REPO, env=environment, capture_output=True, text=True, timeout=60)

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("LITTLE_SISTER_USERS is set", completed.stderr)
        self.assertIn("LITTLE_SISTER_CONFIG_DIR", completed.stderr)
