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

    # --- ADR-0039 roll-up semantics ---

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

    def test_all_ignored_children_read_maintenance_when_one_was_silenced(self):
        """The edge case ADR-0032 left open, now answered.

        This asserted ``UNDEFINED`` while it was open. The model already answers the
        same question one level down — a node whose *virtual* children (its reason
        entries) are all pinned reads ``MAINTENANCE`` — and real and virtual children
        may not read differently in one model. "Nothing under here is reporting
        because we silenced it" is a different fact from "nothing here has reported
        yet".
        """
        parent = Status("/app", code=StatusCode.UNDEFINED)
        parent.add_child(Status("/app/db", code=StatusCode.MAINTENANCE))
        parent.add_child(Status("/app/cache", code=StatusCode.UNDEFINED))
        self.assertEqual(parent.get_status_code(), StatusCode.MAINTENANCE)

    def test_children_that_never_reported_stay_undefined(self):
        # the other half of the same rule, and why it is not simply "nothing counted
        # means maintenance": an unreported subtree has not been silenced by anyone
        parent = Status("/app", code=StatusCode.UNDEFINED)
        parent.add_child(Status("/app/db", code=StatusCode.UNDEFINED))
        self.assertEqual(parent.get_status_code(), StatusCode.UNDEFINED)

    def test_construction_leaves_the_timestamp_unset(self):
        # Having a timestamp *means* a check has written the node (ADR-0027), so a
        # node the tree just built — a container on the way down to a check — has
        # none, whatever code it was constructed with.
        self.assertIsNone(Status("/app/db").timestamp)
        self.assertIsNone(Status("/app/db", code=StatusCode.OK).timestamp)

    def test_update_changes_code_reason_and_timestamp(self):
        status = Status("/app/db", code=StatusCode.OK)
        status.update(StatusCode.ERROR, "connection refused")
        self.assertEqual(status.code, StatusCode.ERROR)
        self.assertEqual(status.reason, ["connection refused"])
        before = status.timestamp
        self.assertIsNotNone(before)
        status.update(StatusCode.OK)
        self.assertGreaterEqual(status.timestamp, before)

    def test_touch_stamps_without_changing_code_or_reason(self):
        status = Status("/app/db", code=StatusCode.OK, reason="all good")
        status.touch()
        self.assertIsNotNone(status.timestamp)
        self.assertEqual(status.code, StatusCode.OK)
        self.assertEqual(status.reason, ["all good"])

    def test_update_accepts_string_code(self):
        status = Status("/app/db", code=StatusCode.OK)
        status.update("warn")
        self.assertEqual(status.code, StatusCode.WARN)


if __name__ == '__main__':
    unittest.main()
