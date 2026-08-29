"""Secret references (ADR-0023): resolution and the resolver registry, the
``scheme://address``-always grammar that keeps a pasted secret out of the lookup,
the ``secrets:`` config block, the check base's resolve-at-construction split
(malformed = loud ``CheckError``, unresolvable = recorded), and the engine's
pinned-ERROR path.

The registry is also a **registration seam** held to the seam rules (ADR-0064):
a claim records the package that made it, a second claim from another package
refuses, and replacing somebody else's scheme is said out loud.
"""
from __future__ import annotations

import os
import unittest
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from types import FunctionType
from typing import Any
from unittest import TestCase, mock

from little_sister import secrets
from little_sister.checks import CheckError, CheckResult, load_checks
from little_sister.checks.base import CHECK_TYPES, Check, parse_secret_refs
from little_sister.engine import Engine
from little_sister.secrets import register_resolver, same_secret
from little_sister.status import StatusCode
from little_sister.tree import StatusTree

TOKEN_ENV = "LS_TEST_SECRET"
TOKEN_REF = f"env://{TOKEN_ENV}"


def _claim(scheme: str, resolver: secrets.Resolver, **kwargs: Any) -> None:
    """The one line an installed package's registration module runs.

    Only its **globals** travel: :func:`_from_package` rebinds this body to a
    namespace named after some other package, which is exactly what the registry
    reads — the calling frame's ``__name__``. Faking the module rather than the
    answer keeps the inference itself under test; a test that patched
    ``calling_package`` would pass against a registry that never called it.
    """
    register_resolver(scheme, resolver, **kwargs)


def _from_module(module: str) -> Callable[..., None]:
    """:func:`_claim` as a module of that exact name would call it."""
    return FunctionType(_claim.__code__,
                        {"__name__": module,
                         "register_resolver": register_resolver})


def _from_package(package: str) -> Callable[..., None]:
    """:func:`_claim` as *package*'s own registration **submodule** would call it —
    a package registers from somewhere inside itself, and what is recorded is the
    installation, not the file."""
    return _from_module(f"{package}.registrations")


#: This test module's own package, which is what the registry infers for a bare
#: ``secrets.register_resolver(...)`` call below — the deployment-registers-its-own
#: case, spelled the way the registry spells it.
HERE = "tests"


class _SecretCheck(Check):
    """A check type that resolves one secret reference at construction."""

    def __init__(self, *, token: str = TOKEN_REF, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.token = self.resolve_secret(token)
        self.ran = False

    @classmethod
    def _extra_from_config(cls, config: dict[str, Any],
                           base_dir: Path) -> dict[str, Any]:
        return {"token": str(config.get("token", TOKEN_REF))}

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
    def test_env_scheme_reads_the_environment(self):
        os.environ[TOKEN_ENV] = "s3cr3t"
        self.assertEqual(secrets.resolve(TOKEN_REF), "s3cr3t")

    def test_env_value_is_stripped(self):
        os.environ[TOKEN_ENV] = "  s3cr3t \n"
        self.assertEqual(secrets.resolve(TOKEN_REF), "s3cr3t")

    def test_env_scheme_is_registered_like_any_other(self):
        self.assertIn("env", secrets._resolvers)

    def test_missing_environment_variable_fails_resolution(self):
        with self.assertRaises(secrets.SecretError) as caught:
            secrets.resolve(TOKEN_REF)
        self.assertIn(TOKEN_ENV, str(caught.exception))

    def test_blank_environment_variable_fails_resolution(self):
        os.environ[TOKEN_ENV] = "   "
        with self.assertRaises(secrets.SecretError):
            secrets.resolve(TOKEN_REF)

    def test_env_name_may_be_lower_case(self):
        os.environ["ls_test_lower"] = "v"      # the scheme, not the shape, decides
        self.assertEqual(secrets.resolve("env://ls_test_lower"), "v")

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

    def test_the_same_package_registering_again_replaces_the_resolver(self):
        # Not last-wins any more (ADR-0064) — last-wins *within one package*,
        # which is the reloading server re-running its own registrations.
        secrets.register_resolver("fake", lambda address: "first")
        secrets.register_resolver("fake", lambda address: "second")
        self.assertEqual(secrets.resolve("fake://x"), "second")


class RegistrySeamTests(_IsolatedCase):
    """A scheme is claimed once, by a package that is named (ADR-0064).

    The claim rules are the `type:` rules (little-sister ADR-0051) for the same
    reason: a scheme decides which store a credential is read from, so a silent
    last-wins would let import order hand one package's checks another package's
    secrets.
    """

    def test_a_registration_names_the_package_that_made_it(self):
        _from_package("other_package")("fake", lambda address: "v")
        claimed = secrets._resolvers["fake"]
        self.assertEqual(claimed.package, "other_package")
        self.assertEqual(claimed.owner, "other_package")
        self.assertFalse(claimed.builtin)
        self.assertEqual(claimed.replaced, "")

    def test_a_bare_call_names_the_calling_module_s_package(self):
        secrets.register_resolver("fake", lambda address: "v")
        self.assertEqual(secrets._resolvers["fake"].package, HERE)

    def test_the_built_in_env_scheme_is_the_library_s(self):
        claimed = secrets._resolvers["env"]
        self.assertEqual(claimed.package, "little_sister")
        self.assertTrue(claimed.builtin)

    def test_registered_resolvers_are_listed_by_scheme(self):
        _from_package("other_package")("zeta", lambda address: "v")
        secrets.register_resolver("alpha", lambda address: "v")
        listed = secrets.registered_resolvers()
        self.assertEqual([row.scheme for row in listed],
                         sorted(row.scheme for row in listed))
        self.assertEqual({row.scheme for row in listed},
                         {"alpha", "env", "zeta"})

    def test_another_package_claiming_a_scheme_refuses(self):
        _from_package("first_package")("fake", lambda address: "first")
        with self.assertRaises(secrets.SchemeConflictError):
            _from_package("second_package")("fake", lambda address: "second")

    def test_the_refusal_names_both_packages_and_the_scheme(self):
        _from_package("first_package")("fake", lambda address: "first")
        with self.assertRaises(secrets.SchemeConflictError) as caught:
            _from_package("second_package")("fake", lambda address: "second")
        message = str(caught.exception)
        self.assertIn("first_package", message)
        self.assertIn("second_package", message)
        self.assertIn("fake://", message)

    def test_a_refused_claim_leaves_the_first_resolver_answering(self):
        _from_package("first_package")("fake", lambda address: "first")
        with self.assertRaises(secrets.SchemeConflictError):
            _from_package("second_package")("fake", lambda address: "second")
        self.assertEqual(secrets.resolve("fake://x"), "first")
        self.assertEqual(secrets._resolvers["fake"].package, "first_package")

    def test_case_and_padding_do_not_dodge_the_claim(self):
        _from_package("first_package")("fake", lambda address: "first")
        with self.assertRaises(secrets.SchemeConflictError):
            _from_package("second_package")("  FaKe  ", lambda address: "second")

    def test_a_deliberate_replacement_wins(self):
        _from_package("first_package")("fake", lambda address: "first")
        _from_package("second_package")("fake", lambda address: "second",
                                        replace=True)
        self.assertEqual(secrets.resolve("fake://x"), "second")

    def test_a_replacement_records_whom_it_displaced(self):
        _from_package("first_package")("fake", lambda address: "first")
        _from_package("second_package")("fake", lambda address: "second",
                                        replace=True)
        claimed = secrets._resolvers["fake"]
        self.assertEqual(claimed.package, "second_package")
        self.assertEqual(claimed.replaced, "first_package")

    def test_reloading_the_replacing_package_keeps_the_replacement(self):
        # Re-importing the module that overrode a scheme must not quietly un-say
        # that it overrode anything — the page would then show a plain claim.
        _from_package("first_package")("fake", lambda address: "first")
        second = _from_package("second_package")
        second("fake", lambda address: "second", replace=True)
        second("fake", lambda address: "again")
        self.assertEqual(secrets.resolve("fake://x"), "again")
        self.assertEqual(secrets._resolvers["fake"].replaced, "first_package")

    def test_a_first_claim_replaces_nobody(self):
        _from_package("first_package")("fake", lambda address: "v",
                                       replace=True)
        self.assertEqual(secrets._resolvers["fake"].replaced, "")

    def test_a_deployment_may_still_replace_the_built_in_env(self):
        # ADR-0023's promise, kept — now said out loud rather than by accident.
        secrets.register_resolver("env", lambda name: "from-the-store",
                                  replace=True)
        self.assertEqual(secrets.resolve(TOKEN_REF), "from-the-store")
        claimed = secrets._resolvers["env"]
        self.assertEqual(claimed.package, HERE)
        self.assertEqual(claimed.replaced, "little_sister")
        self.assertFalse(claimed.builtin)

    def test_replacing_env_by_accident_no_longer_happens(self):
        with self.assertRaises(secrets.SchemeConflictError) as caught:
            secrets.register_resolver("env", lambda name: "oops")
        self.assertIn("little_sister", str(caught.exception))
        self.assertIn(HERE, str(caught.exception))

    def test_an_unidentified_caller_is_named_rather_than_left_blank(self):
        # `__main__` is what *any* script is called when it is run directly, so it
        # identifies no installation and the registry keeps nothing (origins.py).
        # The page and the refusal still have to call it something.
        claim = _from_module("__main__")
        with self.assertRaises(secrets.SchemeConflictError) as caught:
            claim("env", lambda name: "oops")
        self.assertIn(secrets.UNIDENTIFIED, str(caught.exception))
        claim("fake", lambda address: "v")
        self.assertEqual(secrets._resolvers["fake"].package, "")
        self.assertEqual(secrets._resolvers["fake"].owner, secrets.UNIDENTIFIED)


class MissingSchemeTests(_IsolatedCase):
    """Every reference carries a scheme, so a string without one is malformed by
    construction — which is exactly the shape of a credential pasted where its
    reference belongs (ADR-0023, 2026-07-27 update). No shape guessing."""

    def _malformed(self, reference: str) -> str:
        with self.assertRaises(secrets.UnknownSchemeError) as caught:
            secrets.resolve(reference)
        return str(caught.exception)

    def test_a_bare_name_is_no_longer_a_reference(self):
        os.environ[TOKEN_ENV] = "s3cr3t"
        self._malformed(TOKEN_ENV)      # would have resolved before the update

    def test_pasted_github_token_is_rejected(self):
        self._malformed("ghp_16C7e42F292c6912E7710c838347Ae178B4a")

    def test_pasted_fine_grained_token_is_rejected(self):
        self._malformed("github_pat_11ABCDEFG0abcdefghijklm")

    def test_pasted_jwt_is_rejected(self):
        self._malformed("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.abc")

    def test_message_never_quotes_the_value(self):
        pasted = "ghp_16C7e42F292c6912E7710c838347Ae178B4a"
        message = self._malformed(pasted)
        self.assertNotIn(pasted, message)
        self.assertIn("env://", message)     # ...but does say what was expected

    def test_a_rejected_string_is_never_looked_up(self):
        os.environ["ghp_secret"] = "would-have-resolved"
        self._malformed("ghp_secret")

    def test_scheme_without_an_address_is_malformed(self):
        self.assertIn("address", self._malformed("env://"))


class ParseSecretRefsTests(TestCase):
    """The ``secrets:`` config block (ADR-0023 update note)."""

    def test_returns_each_named_reference(self):
        config = {"secrets": {"client_id": "env://WIZ_CLIENT_ID",
                              "client_secret": "aws-sm://wiz/secret"}}
        self.assertEqual(
            parse_secret_refs(config, "client_id", "client_secret"),
            {"client_id": "env://WIZ_CLIENT_ID",
             "client_secret": "aws-sm://wiz/secret"})

    def test_reference_is_stripped(self):
        config = {"secrets": {"token": "  env://GITHUB_TOKEN\n"}}
        self.assertEqual(parse_secret_refs(config, "token"),
                         {"token": "env://GITHUB_TOKEN"})

    def test_missing_block_names_what_is_required(self):
        with self.assertRaises(CheckError) as caught:
            parse_secret_refs({}, "token")
        self.assertIn("token", str(caught.exception))

    def test_block_must_be_a_mapping(self):
        with self.assertRaises(CheckError):
            parse_secret_refs({"secrets": "env://GITHUB_TOKEN"}, "token")

    def test_missing_name_is_an_error(self):
        with self.assertRaises(CheckError):
            parse_secret_refs({"secrets": {"client_id": "env://WIZ_CLIENT_ID"}},
                              "client_id", "client_secret")

    def test_unknown_key_is_a_typo_not_a_silent_extra(self):
        with self.assertRaises(CheckError) as caught:
            parse_secret_refs({"secrets": {"token": "env://GITHUB_TOKEN",
                                           "toekn": "env://GITHUB_TOKEN"}},
                              "token")
        self.assertIn("toekn", str(caught.exception))

    def test_empty_reference_is_an_error(self):
        with self.assertRaises(CheckError):
            parse_secret_refs({"secrets": {"token": "  "}}, "token")

    def test_non_string_reference_is_an_error(self):
        with self.assertRaises(CheckError):
            parse_secret_refs({"secrets": {"token": 42}}, "token")

    def test_error_names_the_key_but_never_quotes_the_value(self):
        pasted = "ghp_16C7e42F292c6912E7710c838347Ae178B4a"
        with self.assertRaises(CheckError) as caught:
            parse_secret_refs({"secrets": {"toekn": pasted}}, "token")
        message = str(caught.exception)
        self.assertIn("toekn", message)      # the mistyped key, so it is findable
        self.assertNotIn(pasted, message)    # never what it held


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
            checks = Path(tmp, "checks")
            checks.mkdir()
            (checks / "check.yaml").write_text(yaml_text, encoding="utf-8")
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


class SameSecretTests(TestCase):
    """Comparing a credential — and the standard library trap this wraps.

    `secrets.compare_digest` takes `str` **only while both sides are ASCII** and
    raises `TypeError` otherwise. Written the obvious way, a password check passes
    every test anybody writes and then answers a 500 the first time somebody types
    an umlaut into it — an anonymous visitor at the emergency door, on the morning
    that door exists for.
    """

    def test_it_matches_and_refuses_like_an_equality(self):
        self.assertTrue(same_secret("hunter2", "hunter2"))
        self.assertFalse(same_secret("hunter2", "hunter3"))
        self.assertFalse(same_secret("", "hunter2"))
        self.assertFalse(same_secret("hunter2", ""))

    def test_a_non_ascii_presented_credential_is_refused_not_raised(self):
        # The bug: this is what a German keyboard produces at a login form.
        self.assertFalse(same_secret("pässword", "hunter2"))

    def test_a_non_ascii_stored_credential_still_compares(self):
        # And this is a `.env` somebody hand-edited, where *every* attempt raised.
        self.assertTrue(same_secret("gänseblümchen", "gänseblümchen"))
        self.assertFalse(same_secret("gänseblumchen", "gänseblümchen"))

    def test_the_stdlib_call_it_replaces_would_have_raised(self):
        # Pinning the reason this function exists rather than only its behaviour: if
        # the standard library ever stops raising here, this is the test that says
        # the wrapper may go.
        import secrets as stdlib
        with self.assertRaises(TypeError):
            stdlib.compare_digest("pässword", "pässword")


if __name__ == "__main__":
    unittest.main()
