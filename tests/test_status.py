import unittest
from unittest import TestCase

from little_sister.status import (
    Status,
    StatusCode,
    join_path,
    leaf_name,
    parent_path,
    split_path,
)


class PathHelperTests(TestCase):
    def test_split_path_ignores_separators(self):
        self.assertEqual(split_path("/system/alpha"), ["system", "alpha"])
        self.assertEqual(split_path("system/alpha"), ["system", "alpha"])
        self.assertEqual(split_path("/"), [])
        self.assertEqual(split_path(""), [])

    def test_join_path_is_absolute(self):
        self.assertEqual(join_path("system", "alpha"), "/system/alpha")
        self.assertEqual(join_path("/system/alpha", "disk"), "/system/alpha/disk")
        self.assertEqual(join_path(), "/")             # the root
        self.assertEqual(join_path(""), "/")

    def test_leaf_name_and_parent(self):
        self.assertEqual(leaf_name("/system/alpha"), "alpha")
        self.assertEqual(leaf_name("/example.org"), "example.org")   # dots allowed
        self.assertEqual(leaf_name("/"), "")
        self.assertEqual(parent_path("/system/alpha"), "/system")
        self.assertEqual(parent_path("/alpha"), "/")


class StatusTests(TestCase):
    def test_valid_status_initialization(self):
        status = Status("/src/status", code=StatusCode.OK)
        self.assertEqual(status.code, StatusCode.OK)

    def test_invalid_status_code_raises_value_error(self):
        with self.assertRaises(ValueError):
            Status("/src/status", code="invalid")

    def test_invalid_status_type_raises_type_error(self):
        with self.assertRaises(TypeError):
            Status("/src/status", code=123)

    def test_status_code_string_conversion(self):
        status = Status("/src/status", code="OK")
        self.assertEqual(status.code, StatusCode.OK)

    def test_name_is_the_last_path_segment(self):
        self.assertEqual(Status("/src/status").name, "status")
        self.assertEqual(Status("/example.org").name, "example.org")

    def test_single_reason_converted_to_list(self):
        status = Status("/src/status", code=StatusCode.OK, reason="Single reason")
        self.assertEqual(status.reason, ["Single reason"])

    def test_multiple_reasons_stay_as_list(self):
        reasons = ["First reason", "Second reason"]
        status = Status("/src/status", code=StatusCode.OK, reason=reasons)
        self.assertEqual(status.reason, reasons)

    def test_status_code_propagation(self):
        parent = Status("/src", code=StatusCode.OK)
        parent.add_child(Status("/src/status", code=StatusCode.ERROR))
        self.assertEqual(parent.get_status_code(), StatusCode.ERROR)

    # --- ADR-0004 roll-up semantics ---

    def test_warn_child_rolls_up_as_status_code(self):
        parent = Status("/app", code=StatusCode.OK)
        parent.add_child(Status("/app/db", code=StatusCode.WARN))
        result = parent.get_status_code()
        self.assertEqual(result, StatusCode.WARN)
        # Must be a StatusCode, never the string "warn".
        self.assertIsInstance(result, StatusCode)

    def test_error_is_not_downgraded_by_warn_child(self):
        parent = Status("/app", code=StatusCode.ERROR)
        parent.add_child(Status("/app/db", code=StatusCode.WARN))
        self.assertEqual(parent.get_status_code(), StatusCode.ERROR)

    def test_worst_child_wins(self):
        parent = Status("/app", code=StatusCode.OK)
        parent.add_child(Status("/app/a", code=StatusCode.WARN))
        parent.add_child(Status("/app/b", code=StatusCode.ERROR))
        parent.add_child(Status("/app/c", code=StatusCode.OK))
        self.assertEqual(parent.get_status_code(), StatusCode.ERROR)

    def test_maintenance_cancels_subtree(self):
        # A node in maintenance reports MAINTENANCE even with a failing child.
        maint = Status("/app/db", code=StatusCode.MAINTENANCE)
        maint.add_child(Status("/app/db/disk", code=StatusCode.ERROR))
        self.assertEqual(maint.get_status_code(), StatusCode.MAINTENANCE)

    def test_maintenance_child_is_ignored_by_parent(self):
        parent = Status("/app", code=StatusCode.OK)
        maint = Status("/app/db", code=StatusCode.MAINTENANCE)
        maint.add_child(Status("/app/db/disk", code=StatusCode.ERROR))
        parent.add_child(maint)
        # The maintenance subtree must not redden the parent.
        self.assertEqual(parent.get_status_code(), StatusCode.OK)

    def test_undefined_leaf_is_ignored_by_parent(self):
        parent = Status("/app", code=StatusCode.OK)
        parent.add_child(Status("/app/cache", code=StatusCode.UNDEFINED))
        self.assertEqual(parent.get_status_code(), StatusCode.OK)

    def test_undefined_leaf_stays_undefined(self):
        leaf = Status("/app/cache", code=StatusCode.UNDEFINED)
        self.assertEqual(leaf.get_status_code(), StatusCode.UNDEFINED)

    def test_all_ignored_children_yield_undefined(self):
        parent = Status("/app", code=StatusCode.UNDEFINED)
        parent.add_child(Status("/app/db", code=StatusCode.MAINTENANCE))
        parent.add_child(Status("/app/cache", code=StatusCode.UNDEFINED))
        self.assertEqual(parent.get_status_code(), StatusCode.UNDEFINED)

    def test_update_changes_code_reason_and_timestamp(self):
        status = Status("/app/db", code=StatusCode.OK)
        before = status.timestamp
        status.update(StatusCode.ERROR, "connection refused")
        self.assertEqual(status.code, StatusCode.ERROR)
        self.assertEqual(status.reason, ["connection refused"])
        self.assertGreaterEqual(status.timestamp, before)

    def test_update_accepts_string_code(self):
        status = Status("/app/db", code=StatusCode.OK)
        status.update("warn")
        self.assertEqual(status.code, StatusCode.WARN)


if __name__ == '__main__':
    unittest.main()
