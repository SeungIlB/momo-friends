"""Calendar widget shows recurring and all-day events on their local dates."""

import unittest
from datetime import date
from unittest.mock import Mock, patch

from calendar_feed import fetch_events, parse_events, validate_feed_url


class CalendarFeedTest(unittest.TestCase):
    def test_private_google_url_only(self):
        url = "https://calendar.google.com/calendar/ical/example/private-abc/basic.ics"
        self.assertEqual(validate_feed_url(url), url)
        with self.assertRaises(ValueError):
            validate_feed_url("https://example.com/steal.ics")
        with self.assertRaisesRegex(ValueError, "공개 iCal"):
            validate_feed_url("https://calendar.google.com/calendar/ical/me/public/basic.ics")

    def test_recurring_and_all_day_events(self):
        feed = b"""BEGIN:VCALENDAR\r
VERSION:2.0\r
BEGIN:VEVENT\r
UID:daily@example.com\r
DTSTART:20261102T093000\r
DTEND:20261102T100000\r
RRULE:FREQ=DAILY;COUNT=2\r
SUMMARY:Daily standup\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:holiday@example.com\r
DTSTART;VALUE=DATE:20261103\r
DTEND;VALUE=DATE:20261104\r
SUMMARY:Day off\r
END:VEVENT\r
END:VCALENDAR\r
"""
        rows = parse_events(feed, date(2026, 11, 2), date(2026, 11, 5))
        self.assertEqual([(row["day"], row["time"], row["title"]) for row in rows], [
            ("2026-11-02", "09:30", "Daily standup"),
            ("2026-11-03", "종일", "Day off"),
            ("2026-11-03", "09:30", "Daily standup"),
        ])

    def test_unchanged_feed_uses_cached_body(self):
        url = "https://calendar.google.com/calendar/ical/example/private-abc/basic.ics"
        body = b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"
        first = Mock(status_code=200, content=body, headers={"ETag": '"v1"'})
        unchanged = Mock(status_code=304)
        cache = {}
        with patch("calendar_feed.requests.get", side_effect=[first, unchanged]) as get:
            self.assertEqual(fetch_events(url, date(2026, 11, 1), date(2026, 12, 1), cache), [])
            self.assertEqual(fetch_events(url, date(2026, 11, 1), date(2026, 12, 1), cache), [])
        self.assertEqual(get.call_args.kwargs["headers"], {"If-None-Match": '"v1"'})


if __name__ == "__main__":
    unittest.main()
