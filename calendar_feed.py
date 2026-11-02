"""Read-only Google Calendar iCal feed for the desktop widget."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from urllib.parse import urlsplit

import requests
from icalendar import Calendar
import recurring_ical_events


def validate_feed_url(value: str) -> str:
    url = value.strip()
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != "calendar.google.com"
            or not parsed.path.endswith(".ics") or parsed.username or parsed.password
            or parsed.fragment):
        raise ValueError("Google Calendar의 비공개 iCal 주소(https://calendar.google.com/… .ics)를 입력해줘.")
    if "/public/" in parsed.path.lower():
        raise ValueError("이건 공개 iCal 주소야. 개인 일정은 Google Calendar의 'iCal 형식의 비공개 주소'를 사용해줘.")
    return url


def _local_datetime(value: date | datetime) -> datetime:
    local = datetime.now().astimezone().tzinfo
    if isinstance(value, datetime):
        return value.replace(tzinfo=local) if value.tzinfo is None else value.astimezone(local)
    return datetime.combine(value, time.min, tzinfo=local)


def parse_events(data: bytes, first: date, last: date) -> list[dict[str, str]]:
    """Return occurrences overlapping [first, last), including recurring events."""
    try:
        calendar = Calendar.from_ical(data)
        occurrences = recurring_ical_events.of(calendar).between(first, last)
    except Exception as exc:
        raise ValueError("캘린더 데이터를 읽지 못했어. iCal 주소를 확인해줘.") from exc
    rows: list[dict[str, str]] = []
    for event in occurrences:
        if str(event.get("status", "")).upper() == "CANCELLED":
            continue
        start_field = event.get("dtstart")
        if not start_field:
            continue
        start_raw = start_field.dt
        end_field = event.get("dtend")
        end_raw = end_field.dt if end_field else (
            start_raw + (timedelta(days=1) if not isinstance(start_raw, datetime) else timedelta(hours=1)))
        start = _local_datetime(start_raw)
        end = _local_datetime(end_raw)
        all_day = not isinstance(start_raw, datetime)
        day = max(first, start.date())
        while day < last and _local_datetime(day) < end:
            if _local_datetime(day + timedelta(days=1)) > start:
                rows.append({"day": day.isoformat(),
                             "time": "종일" if all_day else start.strftime("%H:%M"),
                             "title": str(event.get("summary", "(제목 없음)"))[:100],
                             "sort": "00:00" if all_day else start.strftime("%H:%M")})
            day += timedelta(days=1)
    rows.sort(key=lambda row: (row["day"], row["sort"], row["title"]))
    return rows


def fetch_events(url: str, first: date, last: date,
                 cache: dict[str, object] | None = None) -> list[dict[str, str]]:
    validate_feed_url(url)
    headers: dict[str, str] = {}
    if cache:
        if cache.get("etag"):
            headers["If-None-Match"] = str(cache["etag"])
        if cache.get("last_modified"):
            headers["If-Modified-Since"] = str(cache["last_modified"])
    try:
        response = requests.get(url, headers=headers, timeout=15, allow_redirects=False)
    except requests.RequestException as exc:
        raise ValueError("캘린더에 연결하지 못했어. 인터넷 연결을 확인해줘.") from exc
    if response.status_code == 304 and cache and isinstance(cache.get("body"), bytes):
        data = cache["body"]
    elif response.status_code == 200:
        data = response.content
        if cache is not None:
            cache.update({"body": data, "etag": response.headers.get("ETag"),
                          "last_modified": response.headers.get("Last-Modified")})
    else:
        raise ValueError(f"캘린더를 읽지 못했어 (HTTP {response.status_code}). 비공개 주소를 확인해줘.")
    if len(data) > 5_000_000:
        raise ValueError("캘린더 데이터가 너무 커서 위젯에서 읽지 않았어.")
    return parse_events(data, first, last)
