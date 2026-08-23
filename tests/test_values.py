"""Reading values out of a decoded bag (ADR-0026)."""
from unittest import TestCase

from little_sister import values
from little_sister.errors import CheckError

# A GitHub-shaped payload: nested, mixed types, an explicit null.
_PAYLOAD = {
    "number": 42,
    "title": "fix *everything*",
    "draft": False,
    "merged_at": None,
    "user": {"login": "ada", "id": "7"},
    "security_advisory": {"severity": "HIGH", "score": 8.8},
    "labels": [{"name": "bug"}, {"name": "urgent"}],
}


class TextTests(TestCase):
    def test_reads_and_stringifies(self):
        self.assertEqual(values.text(_PAYLOAD, "title"), "fix *everything*")
        self.assertEqual(values.text(_PAYLOAD, "number"), "42")

    def test_walks_nested_keys(self):
        self.assertEqual(values.text(_PAYLOAD, "user", "login"), "ada")
        self.assertEqual(
            values.text(_PAYLOAD, "security_advisory", "severity"), "HIGH")

    def test_absent_yields_the_default(self):
        # missing key, explicit null, a non-mapping on the way, and a bag that is
        # not a mapping at all all count as absent
        for args in (("nope",), ("merged_at",), ("title", "deeper"),
                     ("user", "login", "deeper")):
            self.assertEqual(values.text(_PAYLOAD, *args, default="d"), "d")
        self.assertEqual(values.text(None, "x", default="d"), "d")

    def test_required_absent_raises(self):
        with self.assertRaises(CheckError) as caught:
            values.text(_PAYLOAD, "user", "email", required=True)
        self.assertIn("user.email", str(caught.exception))

    def test_where_prefixes_the_message(self):
        with self.assertRaises(CheckError) as caught:
            values.text({}, "warn", required=True, where="thresholds.disk")
        self.assertIn("thresholds.disk.warn", str(caught.exception))

    def test_does_not_escape_markdown(self):
        # escaping is a render-time step (plain()); a stored escaped value could no
        # longer go into a URL
        self.assertEqual(values.text(_PAYLOAD, "title"), "fix *everything*")


class NumberTests(TestCase):
    def test_reads_int_and_numeric_string(self):
        self.assertEqual(values.number(_PAYLOAD, "number"), 42)
        self.assertEqual(values.number(_PAYLOAD, "user", "id"), 7)

    def test_absent_yields_the_default(self):
        self.assertEqual(values.number(_PAYLOAD, "nope", default=5), 5)
        self.assertEqual(values.number(_PAYLOAD, "nope"), 0)

    def test_present_but_uncoercible_always_raises(self):
        # a typo must not fall back to a plausible-looking default
        with self.assertRaises(CheckError):
            values.number({"n": "abc"}, "n", default=5)
        with self.assertRaises(CheckError):
            values.number({"n": {"a": 1}}, "n", default=5)

    def test_required_absent_raises(self):
        with self.assertRaises(CheckError):
            values.number({}, "number", required=True)


class RealTests(TestCase):
    def test_reads_float_int_and_string(self):
        self.assertEqual(values.real(_PAYLOAD, "security_advisory", "score"), 8.8)
        self.assertEqual(values.real({"w": 80}, "w"), 80.0)
        self.assertEqual(values.real({"w": "12.5"}, "w"), 12.5)

    def test_absent_yields_the_default(self):
        self.assertEqual(values.real({}, "w", default=90.0), 90.0)

    def test_present_but_uncoercible_raises_with_the_path(self):
        with self.assertRaises(CheckError) as caught:
            values.real({"warn": "abc"}, "warn", default=1.0, where="thresholds.disk")
        self.assertIn("thresholds.disk.warn", str(caught.exception))


class FlagTests(TestCase):
    def test_reads_bools(self):
        self.assertIs(values.flag(_PAYLOAD, "draft"), False)
        self.assertIs(values.flag({"archived": True}, "archived"), True)

    def test_absent_yields_the_default(self):
        self.assertIs(values.flag({}, "archived"), False)
        self.assertIs(values.flag({}, "archived", default=True), True)


class StrictFlagTests(TestCase):
    """A switch in a configuration file, as against `flag`'s truthiness read."""

    def test_reads_bools(self):
        self.assertIs(values.strict_flag({"enabled": True}, "enabled"), True)
        self.assertIs(values.strict_flag({"enabled": False}, "enabled"), False)

    def test_absent_yields_the_default(self):
        self.assertIs(values.strict_flag({}, "enabled"), False)
        self.assertIs(values.strict_flag({}, "enabled", default=True), True)

    def test_a_quoted_yaml_boolean_is_refused_rather_than_inverted(self):
        # The whole reason this exists beside `flag`: `bool("false")` is True, so
        # the lenient read switches the thing **on** while the config says off.
        self.assertIs(values.flag({"enabled": "false"}, "enabled"), True)
        with self.assertRaises(CheckError) as caught:
            values.strict_flag({"enabled": "false"}, "enabled", where="aspect")
        self.assertIn("aspect.enabled", str(caught.exception))
        self.assertIn("true or false", str(caught.exception))

    def test_a_number_is_refused_too(self):
        for stated in (1, 0, 1.0, [], {}):
            with self.subTest(stated=stated), self.assertRaises(CheckError):
                values.strict_flag({"enabled": stated}, "enabled")

    def test_walks_a_path_like_its_neighbours(self):
        bag = {"subnodes": {"ec2": {"show_when_quiet": True}}}
        self.assertIs(
            values.strict_flag(bag, "subnodes", "ec2", "show_when_quiet"), True)


class RowsTests(TestCase):
    def test_reads_a_list_of_bags(self):
        labels = values.rows(_PAYLOAD, "labels")
        self.assertEqual([values.text(row, "name") for row in labels],
                         ["bug", "urgent"])

    def test_walks_to_a_nested_list(self):
        body = {"data": {"issues": {"nodes": [{"id": "a"}]}}}
        self.assertEqual(values.rows(body, "data", "issues", "nodes"),
                         [{"id": "a"}])

    def test_absent_yields_an_empty_list(self):
        self.assertEqual(values.rows(_PAYLOAD, "nope"), [])
        self.assertEqual(values.rows(None, "a", "b"), [])

    def test_a_present_non_list_raises(self):
        with self.assertRaises(CheckError) as caught:
            values.rows({"nodes": "oops"}, "nodes", where="data")
        self.assertIn("data.nodes", str(caught.exception))
