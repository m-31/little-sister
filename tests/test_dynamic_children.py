"""A child a run names takes nothing declared for its name (ADR-0118).

A type declares the labels of the children it always emits by their names, a
deployment's `subnodes:` block retunes them by the same names, and the engine applies
both to every node of that name, at any depth (ADR-0025, ADR-0063). A subject's node is
named by its source (ADR-0106), and a source may call a thing by a name its type
declares: a function called `batch`, an account called `ec2`, a volume called `memory`.

* A child of a result says that a run names it, and one that says nothing is read as
  before: by its name, at any depth.
* Nothing declared for its name reaches such a child — not the type's label or flag,
  and not the deployment's block.
* Its labels are the ones its result carries, each field for itself, and `nodes.yaml`
  still beats them.
* It is said of that node alone: a child beneath it that says nothing is read by its
  name.
* The root ignores it.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from unittest import TestCase

from little_sister.checks.base import Check, CheckError, CheckResult, Measurement
from little_sister.engine import Engine
from little_sister.status import StatusCode
from little_sister.tree import StatusTree

OK = StatusCode.OK

#: What a type declares for the children it always emits, as `aws` does for its
#: aspects: a label for each, and the flag for the one that is a roster.
DECLARED: dict[str, dict[str, object]] = {
    "batch": {"title": "Batch", "about": "The queues."},
    "ec2": {"title": "EC2", "about": "The instances.", "show_when_quiet": True},
}


class _Handed(Check):
    """A check that hands back the tree its test wrote."""

    type_name = "handed"

    def __init__(self, *, result: CheckResult, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._result = result

    def measure(self) -> Sequence[Measurement]:
        return ()

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        return self._result


def _stored(result: CheckResult, *, tree: StatusTree | None = None,
            **declared: Any) -> StatusTree:
    """The tree after one run of a check at `/aws` that returns *result*, with what
    its type declared and its deployment configured."""
    tree = tree if tree is not None else StatusTree()
    Engine([_Handed(path="/aws", result=result, **declared)], tree).run_once()
    return tree


def _beside_its_aspect(**function: Any) -> CheckResult:
    """`/aws/batch`, the aspect a type always emits, and `/aws/lambda/batch`, a
    function its account happens to call so."""
    return CheckResult(OK, children=(
        CheckResult(OK, name="batch"),
        CheckResult(OK, name="lambda", children=(
            CheckResult(OK, name="batch", **function),)),))


class SeamTests(TestCase):
    """A child of a result says that a run names it (decision 1)."""

    def test_a_result_says_nothing_unless_it_is_told_to(self) -> None:
        self.assertIs(CheckResult(OK).dynamic, False)

    def test_a_child_says_that_a_run_names_it(self) -> None:
        self.assertIs(CheckResult(OK, name="batch", dynamic=True).dynamic, True)

    def test_the_statement_is_true_or_false_and_nothing_else(self) -> None:
        # On a child and on a root alike: a root ignores the word, and is still not
        # handed one that only reads as true.
        for name in ("batch", ""):
            for said in ("false", 1, None):
                with self.subTest(name=name, said=said), self.assertRaisesRegex(
                        CheckError, "dynamic"):
                    CheckResult(OK, name=name,
                                dynamic=said)  # type: ignore[arg-type]


class DeclaredForANameTests(TestCase):
    """Nothing declared for its name reaches a child a run names (decision 2)."""

    def test_a_child_that_says_nothing_wears_what_its_name_declares(self) -> None:
        # What is declared for a name reaches every node of that name, which is how
        # one entry serves each account's aspect — and how a function called `batch`
        # came to be shown as the aspect.
        tree = _stored(_beside_its_aspect(), subnode_defaults=DECLARED)
        self.assertEqual(tree.snapshot("/aws/batch").title, "Batch")
        self.assertEqual(tree.snapshot("/aws/lambda/batch").title, "Batch")

    def test_a_declared_label_does_not_reach_a_child_a_run_names(self) -> None:
        tree = _stored(_beside_its_aspect(dynamic=True), subnode_defaults=DECLARED)
        aspect = tree.snapshot("/aws/batch")
        function = tree.snapshot("/aws/lambda/batch")
        self.assertEqual((aspect.title, aspect.about), ("Batch", "The queues."))
        self.assertEqual((function.title, function.about), ("", ""))

    def test_a_declared_flag_does_not_reach_it(self) -> None:
        result = CheckResult(OK, children=(
            CheckResult(OK, name="ec2"),
            CheckResult(OK, name="lambda", children=(
                CheckResult(OK, name="ec2", dynamic=True),)),))
        tree = _stored(result, subnode_defaults=DECLARED)
        self.assertIs(tree.snapshot("/aws/ec2").show_when_quiet, True)
        self.assertIsNone(tree.snapshot("/aws/lambda/ec2").show_when_quiet)

    def test_the_deployment_s_block_does_not_reach_it_either(self) -> None:
        # `subnodes: {batch: …}` in a check's file retunes the aspect, and is keyed
        # by the same name: it means the child the type always emits under it.
        tree = _stored(_beside_its_aspect(dynamic=True), subnode_defaults=DECLARED,
                       subnode_labels={"batch": {"title": "Our queues"}},
                       subnode_show_when_quiet={"batch": True})
        aspect = tree.snapshot("/aws/batch")
        function = tree.snapshot("/aws/lambda/batch")
        self.assertEqual((aspect.title, aspect.about), ("Our queues", "The queues."))
        self.assertIs(aspect.show_when_quiet, True)
        self.assertEqual((function.title, function.about), ("", ""))
        self.assertIsNone(function.show_when_quiet)


class ItsOwnLabelsTests(TestCase):
    """Its labels are the ones its result carries (decision 3)."""

    def test_what_its_result_carries_is_what_it_shows(self) -> None:
        # Where a declaration and a result both speak for a name, the declaration
        # wins (ADR-0063 decision 3) — for the child the declaration is about.
        tree = _stored(
            _beside_its_aspect(title="nightly", about="A function.",
                               show_when_quiet=False, dynamic=True),
            subnode_defaults={"batch": {"title": "Batch", "about": "The queues.",
                                        "show_when_quiet": True}})
        function = tree.snapshot("/aws/lambda/batch")
        self.assertEqual((function.title, function.about),
                         ("nightly", "A function."))
        self.assertIs(function.show_when_quiet, False)

    def test_each_field_for_itself(self) -> None:
        # A title and nothing else: the declared `about` does not fill the gap.
        tree = _stored(_beside_its_aspect(title="nightly", dynamic=True),
                       subnode_defaults=DECLARED)
        function = tree.snapshot("/aws/lambda/batch")
        self.assertEqual((function.title, function.about), ("nightly", ""))

    def test_nodes_yaml_still_beats_what_its_result_carries(self) -> None:
        # Seeded by path before the first run, and a run fills an empty field only.
        tree = StatusTree()
        tree.set_title("/aws/lambda/batch", "declared in nodes.yaml")
        tree.set_show_when_quiet("/aws/lambda/batch", True)
        _stored(_beside_its_aspect(title="nightly", about="A function.",
                                   show_when_quiet=False, dynamic=True),
                tree=tree, subnode_defaults=DECLARED)
        function = tree.snapshot("/aws/lambda/batch")
        self.assertEqual((function.title, function.about),
                         ("declared in nodes.yaml", "A function."))
        self.assertIs(function.show_when_quiet, True)


class OfThatNodeAloneTests(TestCase):
    """It is said of one node, and of none beneath it (decision 4)."""

    def test_an_aspect_beneath_an_account_of_its_name_is_still_the_aspect(
            self) -> None:
        # `/aws/ec2` is an account somebody named so, and `/aws/ec2/ec2` its aspect.
        result = CheckResult(OK, children=(
            CheckResult(OK, name="ec2", title="The ec2 account", dynamic=True,
                        children=(CheckResult(OK, name="ec2"),)),))
        tree = _stored(result, subnode_defaults=DECLARED)
        account, aspect = tree.snapshot("/aws/ec2"), tree.snapshot("/aws/ec2/ec2")
        self.assertEqual((account.title, account.about), ("The ec2 account", ""))
        self.assertIsNone(account.show_when_quiet)
        self.assertEqual((aspect.title, aspect.about), ("EC2", "The instances."))
        self.assertIs(aspect.show_when_quiet, True)

    def test_the_root_ignores_it(self) -> None:
        # A root is named by its check's `path:`, and its labels keep their own
        # sources; what it hands back beneath it is read as ever.
        tree = _stored(
            CheckResult(OK, title="stamped", about="stamped",
                        show_when_quiet=True, dynamic=True,
                        children=(CheckResult(OK, name="batch"),)),
            subnode_defaults=DECLARED)
        root = tree.snapshot("/aws")
        self.assertEqual((root.title, root.about), ("", ""))
        self.assertIsNone(root.show_when_quiet)
        self.assertEqual(tree.snapshot("/aws/batch").title, "Batch")
