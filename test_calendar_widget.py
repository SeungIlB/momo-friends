"""Momo calendar changes appear immediately without scheduled network polling."""

import unittest

from calendar_widget import CalendarWidget


class CalendarWidgetChangeTest(unittest.TestCase):
    def test_add_then_remove_updates_visible_rows(self):
        widget = CalendarWidget.__new__(CalendarWidget)
        widget.rows = []
        widget.local_changes = []
        widget._render = lambda: None
        change = {"action": "add", "title": "회의", "day": "2026-11-02", "start": "17:30"}
        widget.apply_change(change)
        self.assertEqual([(row["day"], row["title"]) for row in widget.rows],
                         [("2026-11-02", "회의")])
        widget.apply_change({**change, "action": "remove"})
        self.assertEqual(widget.rows, [])


if __name__ == "__main__":
    unittest.main()
