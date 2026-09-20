"""Readiness, its latch, and the two lines beside it (ADR-0073).

Written from the claims the record and ``architecture.md`` §4.9 make, with the
values those claims are about. Three of them carry the design and each has a test
that fails without it: the answer **latches**, so no later failure withdraws a
serving instance; the words it publishes come from a **closed vocabulary**; and the
``all-erroring`` line makes a claim about a *pattern*, so it waits for a complete
first pass and stays silent where there is only one check to have a pattern about.

The trust store is measured against **real** verification paths, steered through
the two variables OpenSSL reads, never through a stubbed count: a stub returning
``{"x509_ca": 0}`` is what encoded the assumption a populated hash directory reads
as an empty store (ADR-0073), and a test built on it could not fail.

The route's own behavior is ``test_web_ready.py``; what the engine records for it
is ``test_engine.py``.
"""
from __future__ import annotations

import os
import ssl
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from little_sister import readiness as readiness_module
from little_sister.codes import StatusCode
from little_sister.readiness import (
    DOORS,
    FIRST_PASS,
    NOT_READY,
    READY,
    TRUST,
    WAITING_FOR,
    Outcomes,
    Readiness,
    TrustStore,
    measure_trust_store,
)

FULL = TrustStore(usable=True)
EMPTY = TrustStore(usable=False)
UNMEASURED = TrustStore(usable=None)

#: A real CA certificate, minted once for these tests and its key discarded:
#: ``openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -days
#: 36500 -subj "/CN=little-sister test CA" -addext
#: "basicConstraints=critical,CA:TRUE" -addext "keyUsage=critical,keyCertSign"``.
#: What matters about it is that it is one OpenSSL would find in a hash directory
#: under the name ``openssl x509 -noout -subject_hash`` gives it.
TEST_CA = """\
-----BEGIN CERTIFICATE-----
MIIBpzCCAU2gAwIBAgIUeT+djioZA3pMal1M3o83aXZnhnQwCgYIKoZIzj0EAwIw
IDEeMBwGA1UEAwwVbGl0dGxlLXNpc3RlciB0ZXN0IENBMCAXDTI2MDkxNjEwNDcx
OFoYDzIxMjYwODIzMTA0NzE4WjAgMR4wHAYDVQQDDBVsaXR0bGUtc2lzdGVyIHRl
c3QgQ0EwWTATBgcqhkjOPQIBBggqhkjOPQMBBwNCAAS0xoD5A2GUL2ef6Z5LV/4d
YrXLi2lk22DBpiRdgWSuPQyAXHdBNDWtJ0FycACYvN4rXKkVtQK0kzAEhHPjc0mq
o2MwYTAdBgNVHQ4EFgQUu17GP4G7uspO+g1D5cRlRAEhH1IwHwYDVR0jBBgwFoAU
u17GP4G7uspO+g1D5cRlRAEhH1IwDwYDVR0TAQH/BAUwAwEB/zAOBgNVHQ8BAf8E
BAMCAgQwCgYIKoZIzj0EAwIDSAAwRQIhANVZC86+nd5RhxQ+apF4695Y5XlXW8gy
Pv6+n9OSVE/5AiBakXegNe+KTGMap5utgb47mcgq6IBLKXSk17haFIA2BQ==
-----END CERTIFICATE-----
"""
TEST_CA_SUBJECT_HASH = "56f8c844"


def _readiness(*, doors: bool = True, trust: TrustStore = FULL,
               first_pass: bool = True,
               outcomes: Outcomes | None = None) -> Readiness:
    return Readiness(doors=lambda: doors, trust=lambda: trust,
                     first_pass=lambda: first_pass, outcomes=lambda: outcomes)


class VocabularyTests(TestCase):
    def test_the_three_words_are_the_whole_vocabulary(self):
        # `/ready` has no login gate, so a word added here is a word published to
        # whoever can reach the port. The whole tuple, not the presence of three.
        self.assertEqual(WAITING_FOR, ("doors", "trust", "first-pass"))

    def test_the_two_status_words_are_not_the_same_word(self):
        self.assertNotEqual(READY, NOT_READY)


class AnswerTests(TestCase):
    def test_all_three_conditions_met_is_ready(self):
        answer = _readiness().answer()
        self.assertTrue(answer.ready)
        self.assertEqual(answer.waiting_for, ())

    def test_no_door_holds_the_answer_back_and_names_doors(self):
        answer = _readiness(doors=False).answer()
        self.assertFalse(answer.ready)
        self.assertEqual(answer.waiting_for, (DOORS,))

    def test_an_empty_trust_store_holds_the_answer_back_and_names_trust(self):
        answer = _readiness(trust=EMPTY).answer()
        self.assertFalse(answer.ready)
        self.assertEqual(answer.waiting_for, (TRUST,))

    def test_an_unfinished_first_pass_holds_the_answer_back_and_names_it(self):
        answer = _readiness(first_pass=False).answer()
        self.assertFalse(answer.ready)
        self.assertEqual(answer.waiting_for, (FIRST_PASS,))

    def test_a_trust_store_that_could_not_be_measured_is_not_reported_empty(self):
        # Not the same fact as an empty store, and never reported as one: refusing
        # readiness over what we could not measure would be a guess with a load
        # balancer behind it.
        self.assertTrue(_readiness(trust=UNMEASURED).answer().ready)

    def test_several_unmet_conditions_are_named_in_the_vocabulary_order(self):
        answer = _readiness(doors=False, trust=EMPTY, first_pass=False).answer()
        self.assertEqual(answer.waiting_for, WAITING_FOR)

    def test_every_word_it_answers_with_comes_from_the_vocabulary(self):
        for doors in (True, False):
            for trust in (FULL, EMPTY):
                for first_pass in (True, False):
                    with self.subTest(doors=doors, trust=trust.usable,
                                      first_pass=first_pass):
                        answer = _readiness(doors=doors, trust=trust,
                                            first_pass=first_pass).answer()
                        self.assertLessEqual(set(answer.waiting_for),
                                             set(WAITING_FOR))


class LatchTests(TestCase):
    def test_once_ready_a_condition_going_false_does_not_take_it_back(self):
        # The whole reason `/ready` is not a second, sharper `/health`: a route
        # that could withdraw a serving instance would remove the very dashboard
        # whose banner explains what broke (ADR-0066 §1).
        doors = {"registered": True}
        answer = Readiness(doors=lambda: doors["registered"], trust=lambda: FULL,
                           first_pass=lambda: True, outcomes=lambda: None)
        self.assertTrue(answer.answer().ready)
        doors["registered"] = False
        self.assertTrue(answer.answer().ready)
        self.assertEqual(answer.answer().waiting_for, ())

    def test_it_does_not_latch_before_every_condition_holds(self):
        first_pass = {"done": False}
        answer = Readiness(doors=lambda: True, trust=lambda: FULL,
                           first_pass=lambda: first_pass["done"],
                           outcomes=lambda: None)
        self.assertFalse(answer.answer().ready)
        first_pass["done"] = True
        self.assertTrue(answer.answer().ready)

    def test_a_latched_answer_stops_asking_the_conditions(self):
        # Not a performance claim: it is what makes the latch a latch rather than
        # three conditions that happen to stay true.
        asked = []

        def doors() -> bool:
            asked.append("doors")
            return True

        answer = Readiness(doors=doors, trust=lambda: FULL,
                           first_pass=lambda: True, outcomes=lambda: None)
        answer.answer()
        answer.answer()
        answer.answer()
        self.assertEqual(asked, ["doors"])


class OutcomesTests(TestCase):
    def test_a_pass_is_complete_when_every_check_has_stored_a_result(self):
        self.assertFalse(Outcomes(configured=3, completed=2, erroring=0).first_pass)
        self.assertTrue(Outcomes(configured=3, completed=3, erroring=0).first_pass)

    def test_a_configuration_with_no_checks_has_completed_its_empty_pass(self):
        # The heartbeat already carries a WARN saying nothing is watched
        # (ADR-0005); keeping traffic away as well would answer a configuration
        # mistake by hiding the page that describes it.
        self.assertTrue(Outcomes(configured=0, completed=0, erroring=0).first_pass)

    def test_every_check_erroring_is_the_pattern(self):
        self.assertTrue(Outcomes(configured=4, completed=4, erroring=4).all_erroring)

    def test_one_healthy_check_is_not_the_pattern(self):
        self.assertFalse(Outcomes(configured=4, completed=4, erroring=3).all_erroring)

    def test_a_pass_still_running_is_not_the_pattern(self):
        # The first check to finish must not carry the line alone and say "every
        # check is erroring" about a pass that has barely started. No guard of its
        # own does this: a check counts as erroring only once it has stored
        # something, so `erroring == configured` cannot hold before the pass ends.
        self.assertFalse(Outcomes(configured=4, completed=1, erroring=1).all_erroring)

    def test_a_single_check_is_never_the_pattern(self):
        # "every check is erroring" would say nothing its own node does not
        # already say, and a line that adds nothing is one somebody learns to skip.
        self.assertFalse(Outcomes(configured=1, completed=1, erroring=1).all_erroring)


class TrustStoreTests(TestCase):
    def test_a_store_with_a_usable_source_is_not_empty(self):
        self.assertFalse(FULL.empty)

    def test_a_store_with_no_usable_source_is_empty(self):
        self.assertTrue(EMPTY.empty)

    def test_a_store_that_could_not_be_measured_is_not_empty(self):
        self.assertFalse(UNMEASURED.empty)


class MeasurementTests(TestCase):
    """``measure_trust_store()`` against real verification paths.

    Each case points ``SSL_CERT_FILE`` and ``SSL_CERT_DIR`` — the two variables
    OpenSSL reads, and the interpreter with it — at exactly the sources it is
    about, an absent one at a name that does not exist: a variable left unset
    would fall back to the interpreter's compiled-in defaults, and whatever this
    machine holds there would answer instead of the test.
    """

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def _paths(self, *, cafile: Path | None = None, capath: Path | None = None):
        return patch.dict(os.environ, {
            "SSL_CERT_FILE": str(cafile or self.root / "no-such-file.pem"),
            "SSL_CERT_DIR": str(capath or self.root / "no-such-directory"),
        })

    def _hash_directory(self) -> Path:
        """A hash directory as ``c_rehash`` lays one out: the certificate under
        its own name, and a link named by its subject hash pointing at it."""
        capath = self.root / "certs"
        capath.mkdir()
        (capath / "test-ca.pem").write_text(TEST_CA)
        (capath / f"{TEST_CA_SUBJECT_HASH}.0").symlink_to("test-ca.pem")
        return capath

    def test_a_hash_directory_alone_is_a_usable_trust_source(self):
        # The defect. OpenSSL consults a capath by subject hash when it verifies a
        # chain and never loads it, so `cert_store_stats()` counted zero here on an
        # instance that verified every connection — a Debian base with a
        # uv-installed interpreter is exactly this layout, a populated
        # /etc/ssl/certs beside a compiled-in cafile the distribution never creates.
        # Failed against the counting measurement before it was replaced.
        with self._paths(capath=self._hash_directory()):
            paths = ssl.get_default_verify_paths()
            self.assertIsNone(paths.cafile)
            self.assertEqual(paths.capath, str(self.root / "certs"))
            measured = measure_trust_store()
        self.assertFalse(measured.empty)

    def test_a_cafile_alone_is_a_usable_trust_source(self):
        cafile = self.root / "ca-certificates.crt"
        cafile.write_text(TEST_CA)
        with self._paths(cafile=cafile):
            self.assertFalse(measure_trust_store().empty)

    def test_no_source_at_all_is_an_empty_store(self):
        # The rollout failure the record was written for: an image built without
        # its distribution's CA certificates, still reported.
        with self._paths():
            self.assertTrue(measure_trust_store().empty)

    def test_an_empty_cafile_is_not_a_source(self):
        cafile = self.root / "ca-certificates.crt"
        cafile.touch()
        with self._paths(cafile=cafile):
            self.assertTrue(measure_trust_store().empty)

    def test_a_directory_without_a_hashed_entry_is_not_a_source(self):
        # The certificate is there under its own name, and OpenSSL, which looks a
        # directory up by hash, would never find it.
        capath = self.root / "certs"
        capath.mkdir()
        (capath / "test-ca.pem").write_text(TEST_CA)
        with self._paths(capath=capath):
            self.assertTrue(measure_trust_store().empty)

    def test_a_dangling_hashed_link_is_not_a_source(self):
        capath = self.root / "certs"
        capath.mkdir()
        (capath / f"{TEST_CA_SUBJECT_HASH}.0").symlink_to("gone.pem")
        with self._paths(capath=capath):
            self.assertTrue(measure_trust_store().empty)

    def test_a_revocation_list_entry_is_not_a_source(self):
        # `<hash>.r0` is how a hash directory names a CRL; it revokes and anchors
        # nothing.
        capath = self.root / "certs"
        capath.mkdir()
        (capath / f"{TEST_CA_SUBJECT_HASH}.r0").write_text(TEST_CA)
        with self._paths(capath=capath):
            self.assertTrue(measure_trust_store().empty)

    def test_a_measurement_that_raises_answers_unknown_rather_than_empty(self):
        def boom():
            raise OSError("no such file")

        with patch.object(readiness_module.ssl, "get_default_verify_paths", boom):
            measured = measure_trust_store()
        self.assertIsNone(measured.usable)
        self.assertFalse(measured.empty)


class LineTests(TestCase):
    def test_a_healthy_instance_says_nothing(self):
        self.assertEqual(_readiness(outcomes=Outcomes(3, 3, 0)).lines(), ())

    def test_an_empty_trust_store_is_one_error_line(self):
        lines = _readiness(trust=EMPTY).lines()
        self.assertEqual([line.slug for line in lines], ["trust"])
        self.assertEqual(lines[0].code, StatusCode.ERROR)
        self.assertIn("trust store", lines[0].text)

    def test_the_trust_line_clears_when_the_store_does(self):
        self.assertEqual(_readiness(trust=FULL).lines(), ())

    def test_a_trust_store_that_could_not_be_measured_says_nothing(self):
        self.assertEqual(_readiness(trust=UNMEASURED).lines(), ())

    def test_every_check_erroring_is_one_warn_line_naming_the_count(self):
        lines = _readiness(outcomes=Outcomes(12, 12, 12)).lines()
        self.assertEqual([line.slug for line in lines], ["all-erroring"])
        self.assertEqual(lines[0].code, StatusCode.WARN)
        self.assertIn("12", lines[0].text)

    def test_the_erroring_line_clears_when_one_check_recovers(self):
        self.assertEqual(_readiness(outcomes=Outcomes(12, 12, 11)).lines(), ())

    def test_an_instance_with_no_engine_makes_no_claim_about_checks(self):
        self.assertEqual(_readiness(outcomes=None).lines(), ())

    def test_the_two_lines_stand_together_when_both_conditions_hold(self):
        # The empty trust store is the cause and the erroring checks are the
        # symptom, and the instance says both: one at ERROR because it is a defect
        # here, one at WARN because it is a reading of the pattern.
        lines = _readiness(trust=EMPTY, outcomes=Outcomes(12, 12, 12)).lines()
        self.assertEqual([line.slug for line in lines], ["trust", "all-erroring"])
        self.assertEqual([line.code for line in lines],
                         [StatusCode.ERROR, StatusCode.WARN])

    def test_the_lines_are_not_the_readiness_answer(self):
        # An unready instance whose reason is a missing door says nothing here:
        # the reasons live in the startup log and on `/system`, where a reader has
        # said who they are.
        self.assertEqual(_readiness(doors=False, first_pass=False).lines(), ())
