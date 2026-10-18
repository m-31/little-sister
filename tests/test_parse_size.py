"""`parse_size`: a size written with a unit, parsed once, into whole bytes (the plan's
*A size with a unit, parsed once*; little-sister-aws ADR-0022 §5 is its first user).

The decimal prefixes and the binary ones both, case as written, a bare number of bytes,
and a refusal naming the value where it is none of these — each a sentence of the plan,
tested with the values the sentence is about.
"""
from unittest import TestCase

from little_sister.checks import CheckError, parse_size


class ParseSizeTests(TestCase):
    def test_the_decimal_prefixes_are_powers_of_a_thousand(self):
        self.assertEqual(parse_size("500 GB", 0), 500_000_000_000)
        self.assertEqual(parse_size("1 kB", 0), 1_000)
        self.assertEqual(parse_size("1 KB", 0), 1_000)
        self.assertEqual(parse_size("3 MB", 0), 3_000_000)
        self.assertEqual(parse_size("2 TB", 0), 2_000_000_000_000)
        self.assertEqual(parse_size("1 PB", 0), 10 ** 15)

    def test_the_binary_prefixes_are_powers_of_1024(self):
        self.assertEqual(parse_size("64 KiB", 0), 65_536)
        self.assertEqual(parse_size("1 MiB", 0), 1_048_576)
        self.assertEqual(parse_size("1 GiB", 0), 1_073_741_824)
        self.assertEqual(parse_size("2 TiB", 0), 2 * 1024 ** 4)
        self.assertEqual(parse_size("1 PiB", 0), 1024 ** 5)

    def test_a_bare_number_is_bytes_and_so_is_b(self):
        self.assertEqual(parse_size(2048, 0), 2048)
        self.assertEqual(parse_size("2048", 0), 2048)
        self.assertEqual(parse_size("2048 B", 0), 2048)
        self.assertEqual(parse_size(0, 1), 0)

    def test_the_space_is_optional_and_a_fraction_is_whole_bytes(self):
        self.assertEqual(parse_size("500GB", 0), 500_000_000_000)
        self.assertEqual(parse_size("1.5 GB", 0), 1_500_000_000)
        self.assertEqual(parse_size("0.5 KiB", 0), 512)
        self.assertEqual(parse_size("  2 TiB  ", 0), 2 * 1024 ** 4)

    def test_a_missing_value_is_the_default(self):
        self.assertEqual(parse_size(None, 4096), 4096)
        self.assertEqual(parse_size("", 4096), 4096)

    def test_a_unit_is_read_as_written(self):
        """`gb` is not a unit, nor `Gb`, nor `GIB`: the prefixes mean something in the
        case they are written in, and a reader who typed `500 mb` gets a sentence,
        not five hundred megabytes."""
        for value in ("500 gb", "500 Gb", "2 GIB", "2 tib", "64 Kb"):
            with self.subTest(value=value), self.assertRaises(CheckError) as caught:
                parse_size(value, 0)
            self.assertIn(repr(value), str(caught.exception))

    def test_a_prefix_without_its_b_is_refused_with_the_spelling(self):
        with self.assertRaises(CheckError) as caught:
            parse_size("500G", 0)
        message = str(caught.exception)
        self.assertIn("'500G'", message)
        self.assertIn("500 GB", message)
        self.assertIn("500 GiB", message)

    def test_what_is_not_a_size_is_refused_naming_the_value(self):
        for value in ("abc", "GB", "-1 GB", "1e3 GB", "1,5 GB", True, -5, 1.5):
            with self.subTest(value=value), self.assertRaises(CheckError) as caught:
                parse_size(value, 0)
            self.assertIn(repr(value), str(caught.exception))
            self.assertIn("size", str(caught.exception))
