import unittest
from unittest import TestCase

from little_sister.status import Status, StatusCode


class StatusTests(TestCase):
    def test_valid_status_initialization(self):
        status = Status("src.little-sister", "status", StatusCode.OK)
        self.assertEqual(status.code, StatusCode.OK)

    def test_invalid_status_code_raises_value_error(self):
        with self.assertRaises(ValueError):
            Status("src.little-sister", "status", "invalid")

    def test_invalid_status_type_raises_type_error(self):
        with self.assertRaises(TypeError):
            Status("src.little-sister", "status", 123)

    def test_status_code_string_conversion(self):
        status = Status("src.little-sister", "status", "OK")
        self.assertEqual(status.code, StatusCode.OK)

    def test_single_reason_converted_to_list(self):
        status = Status("src.little-sister", "status", StatusCode.OK, "Single reason")
        self.assertEqual(status.reason, ["Single reason"])

    def test_multiple_reasons_stay_as_list(self):
        reasons = ["First reason", "Second reason"]
        status = Status("src.little-sister", "status", StatusCode.OK, reasons)
        self.assertEqual(status.reason, reasons)

    def test_status_code_propagation(self):
        parent_status = Status("src.little-sister", "status", StatusCode.OK)
        child_status = Status("src.little-sister.status", "child_status", StatusCode.ERROR)
        parent_status.add_child(child_status)
        self.assertEqual(parent_status.get_status_code(), StatusCode.ERROR)


if __name__ == '__main__':
    unittest.main()
