"""Reminders persist, fire once, and stop after confirmed deletion."""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from calendar_alerts import CalendarAlerts


class CalendarAlertsTest(unittest.TestCase):
    def test_alert_fires_once_and_survives_restart(self):
        tz = timezone(timedelta(hours=9))
        day = "2030-10-29"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "alerts.json"
            alerts = CalendarAlerts(path)
            self.assertTrue(alerts.add("약속", day, "10:00", datetime(2030, 10, 29, 9, 40, tzinfo=tz)))
            self.assertEqual(alerts.due(10, datetime(2030, 10, 29, 9, 49, tzinfo=tz)), [])
            self.assertEqual([item["title"] for item in alerts.due(10, datetime(2030, 10, 29, 9, 50, tzinfo=tz))],
                             ["약속"])
            restarted = CalendarAlerts(path)
            self.assertEqual(restarted.due(10, datetime(2030, 10, 29, 9, 55, tzinfo=tz)), [])

    def test_deleted_and_past_events_do_not_alert(self):
        tz = timezone(timedelta(hours=9))
        now = datetime(2030, 10, 29, 9, 40, tzinfo=tz)
        with tempfile.TemporaryDirectory() as folder:
            alerts = CalendarAlerts(Path(folder) / "alerts.json")
            self.assertFalse(alerts.add("지난 일정", "2030-10-29", "09:30", now))
            self.assertTrue(alerts.add("삭제할 일정", "2030-10-29", "10:00", now))
            alerts.remove("삭제할 일정", "2030-10-29", "10:00")
            self.assertEqual(alerts.due(10, datetime(2030, 10, 29, 9, 55, tzinfo=tz)), [])

    def test_snooze_reappears_five_minutes_later_even_after_start(self):
        tz = timezone(timedelta(hours=9))
        day = "2030-10-29"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "alerts.json"
            alerts = CalendarAlerts(path)
            alerts.add("회의", day, "10:00", datetime(2030, 10, 29, 9, 40, tzinfo=tz))
            self.assertEqual(len(alerts.due(10, datetime(2030, 10, 29, 9, 50, tzinfo=tz))), 1)
            self.assertTrue(alerts.snooze("회의", day, "10:00", now=datetime(2030, 10, 29, 9, 58, tzinfo=tz)))
            restarted = CalendarAlerts(path)
            self.assertEqual(restarted.due(10, datetime(2030, 10, 29, 10, 2, tzinfo=tz)), [])
            reminder = restarted.due(10, datetime(2030, 10, 29, 10, 3, tzinfo=tz))
            self.assertEqual([item["snoozed"] for item in reminder], [True])
            self.assertEqual(restarted.due(10, datetime(2030, 10, 29, 10, 4, tzinfo=tz)), [])


if __name__ == "__main__":
    unittest.main()
