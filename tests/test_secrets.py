"""Secret references (ADR-0023): resolution and the resolver registry, the
check base's resolve-at-construction split (malformed = loud ``CheckError``,
unresolvable = recorded), and the engine's pinned-ERROR path."""
from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest import TestCase, mock

from little_sister import secrets
from little_sister.checks import CheckError, CheckResult, load_checks
from little_sister.checks.base import CHECK_TYPES, Check
from little_sister.engine import Engine
from little_sister.status import StatusCode
from little_sister.tree import StatusTree

TOKEN_ENV = "LS_TEST_SECRET"


class _SecretCheck(Check):
    """A check type that resolves one secret reference at construction."""

    def __init__(self, *, token: str = TOKEN_ENV, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.token = self.resolve_secret(token)
        self.ran = False

    @classmethod
    def _extra_from_config(cls, config: dict[str, Any],
                           base_dir: Path) -> dict[str, Any]:
        return {"token": str(config.get("token", TOKEN_ENV))}

    def run(self) -> CheckResult:
        self.ran = True
        return CheckResult(StatusCode.OK)


class _IsolatedCase(TestCase):
    """Restore the resolver registry and the environment after each test."""

    def setUp(self) -> None:
        for patcher in (mock.patch.dict(secrets._resolvers),
                        mock.patch.dict(os.environ)):
            patcher.start()
            self.addCleanup(patcher.stop)
        os.environ.pop(TOKEN_ENV, None)


class ResolveTests(_IsolatedCase):
    def test_bare_name_reads_the_environment(self):
        os.environ[TOKEN_ENV] = "s3cr3t"
        self.assertEqual(secrets.resolve(TOKEN_ENV), "s3cr3t")

    def test_bare_name_value_is_stripped(self):
        os.environ[TOKEN_ENV] = "  s3cr3t \n"
        self.assertEqual(secrets.resolve(TOKEN_ENV), "s3cr3t")

    def test_missing_environment_variable_fails_resolution(self):
        with self.assertRaises(secrets.SecretError) as caught:
            secrets.resolve(TOKEN_ENV)
        self.assertIn(TOKEN_ENV, str(caught.exception))

    def test_blank_environment_variable_fails_resolution(self):
        os.environ[TOKEN_ENV] = "   "
        with self.assertRaises(secrets.SecretError):
            secrets.resolve(TOKEN_ENV)

    def test_registered_scheme_resolves_by_address(self):
        secrets.register_resolver("fake", lambda address: f"value:{address}")
        self.assertEqual(secrets.resolve("fake://team/token"),
                         "value:team/token")

    def test_scheme_is_case_insensitive(self):
        secrets.register_resolver("FaKe", lambda address: "v")
        self.assertEqual(secrets.resolve("FAKE://x"), "v")

    def test_address_may_itself_contain_the_separator(self):
        secrets.register_resolver("fake", lambda address: address)
        self.assertEqual(secrets.resolve("fake://a://b"), "a://b")

    def test_unknown_scheme_is_a_malformed_reference(self):
        secrets.register_resolver("fake", lambda address: "v")
        with self.assertRaises(secrets.UnknownSchemeError) as caught:
            secrets.resolve("aws-sm://team/token")
        message = str(caught.exception)
        self.assertIn("aws-sm", message)
        self.assertIn("fake", message)   # names the registered schemes

    def test_empty_reference_is_malformed(self):
        with self.assertRaises(secrets.UnknownSchemeError):
            secrets.resolve("   ")

    def test_resolver_failure_becomes_a_secret_error(self):
        def failing(address: str) -> str:
            raise RuntimeError("store unreachable")
        secrets.register_resolver("fake", failing)
        with self.assertRaises(secrets.SecretError) as caught:
            secrets.resolve("fake://team/token")
        self.assertIn("store unreachable", str(caught.exception))

    def test_resolver_empty_value_is_a_failure(self):
        secrets.register_resolver("fake", lambda address: "")
        with self.assertRaises(secrets.SecretError):
            secrets.resolve("fake://team/token")

    def test_register_requires_a_scheme(self):
        with self.assertRaises(ValueError):
            secrets.register_resolver("  ", lambda address: "v")

    def test_reregistering_replaces_the_resolver(self):
        secrets.register_resolver("fake", lambda address: "first")
        secrets.register_resolver("fake", lambda address: "second")
        self.assertEqual(secrets.resolve("fake://x"), "second")


class ResolveSettingTests(_IsolatedCase):
    def test_literal_value_passes_through(self):
        self.assertEqual(secrets.resolve_setting("s3cret"), "s3cret")
        self.assertEqual(secrets.resolve_setting("  s3cret "), "s3cret")

    def test_empty_value_stays_empty(self):
        self.assertEqual(secrets.resolve_setting(""), "")
        self.assertEqual(secrets.resolve_setting("   "), "")

    def test_reference_value_is_resolved(self):
        secrets.register_resolver("fake", lambda address: f"value:{address}")
        self.assertEqual(secrets.resolve_setting("fake://app/key"),
                         "value:app/key")

    def test_failing_reference_raises_secret_error(self):
        def failing(address: str) -> str:
            raise RuntimeError("store unreachable")
        secrets.register_resolver("fake", failing)
        with self.assertRaises(secrets.SecretError):
            secrets.resolve_setting("fake://app/key")

    def test_unknown_scheme_raises_reference_error(self):
        with self.assertRaises(secrets.UnknownSchemeError):
            secrets.resolve_setting("nope://app/key")


class CheckBaseTests(_IsolatedCase):
    def test_successful_resolution_holds_the_value(self):
        os.environ[TOKEN_ENV] = "s3cr3t"
        check = _SecretCheck(path="/svc")
        self.assertEqual(check.token, "s3cr3t")
        self.assertEqual(check.secret_errors, [])

    def test_resolution_failure_is_recorded_not_raised(self):
        check = _SecretCheck(path="/svc")
        self.assertEqual(check.token, "")
        self.assertEqual(len(check.secret_errors), 1)
        self.assertIn(TOKEN_ENV, check.secret_errors[0])

    def test_malformed_reference_raises_check_error(self):
        with self.assertRaises(CheckError):
            _SecretCheck(path="/svc", token="nope://x")


class EnginePinTests(_IsolatedCase):
    def test_pinned_check_reports_error_and_never_runs(self):
        check = _SecretCheck(path="/svc")   # TOKEN_ENV is unset → recorded
        tree = StatusTree()
        engine = Engine([check], tree)
        engine.run_once()
        engine.run_once()   # pinned: no retry either
        node = tree.snapshot("/svc")
        assert node is not None
        self.assertEqual(node.own_code, StatusCode.ERROR)
        self.assertTrue(node.reason[0].startswith("secret unresolvable: "))
        self.assertIn(TOKEN_ENV, node.reason[0])
        self.assertFalse(check.ran)

    def test_resolved_check_runs_normally(self):
        os.environ[TOKEN_ENV] = "s3cr3t"
        check = _SecretCheck(path="/svc")
        tree = StatusTree()
        Engine([check], tree).run_once()
        node = tree.snapshot("/svc")
        assert node is not None
        self.assertEqual(node.own_code, StatusCode.OK)
        self.assertTrue(check.ran)


class LoaderTests(_IsolatedCase):
    def setUp(self) -> None:
        super().setUp()
        patcher = mock.patch.dict(CHECK_TYPES, {"secret-dummy": _SecretCheck})
        patcher.start()
        self.addCleanup(patcher.stop)

    def _load(self, yaml_text: str) -> list[Check]:
        with TemporaryDirectory() as tmp:
            Path(tmp, "check.yaml").write_text(yaml_text, encoding="utf-8")
            return load_checks(Path(tmp))

    def test_malformed_reference_fails_the_load(self):
        with self.assertRaises(CheckError) as caught:
            self._load("type: secret-dummy\npath: /svc\ntoken: nope://x\n")
        message = str(caught.exception)
        self.assertIn("check.yaml", message)         # loader names the file
        self.assertIn("no secret resolver", message)

    def test_unresolvable_reference_loads_and_is_recorded(self):
        checks = self._load("type: secret-dummy\npath: /svc\n")
        self.assertEqual(len(checks), 1)
        self.assertTrue(checks[0].secret_errors)     # pinned later, not fatal


if __name__ == "__main__":
    unittest.main()
