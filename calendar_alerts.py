"""Local reminders for Calendar events confirmed by Momo."""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path


REMINDER_OFFSETS = (60, 30, 5)


def _start_at(day: str, start: str) -> datetime:
    return datetime.fromisoformat(f"{day}T{start}").astimezone()


class CalendarAlerts:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.items: list[dict] = []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    try:
                        if not isinstance(item["title"], str) or not item["title"].strip():
                            continue
                        _start_at(item["day"], item["start"])
                        snooze_until = item.get("snooze_until")
                        if snooze_until is not None:
                            if datetime.fromisoformat(snooze_until).tzinfo is None:
                                continue
                        notified_minutes = item.get("notified_minutes")
                        if isinstance(notified_minutes, list):
                            notified_minutes = sorted({int(value) for value in notified_minutes
                                                       if int(value) in REMINDER_OFFSETS})
                        else:
                            # Old records only tracked a single reminder. Avoid replaying
                            # it after upgrade by treating the reminder sequence as done.
                            notified_minutes = list(REMINDER_OFFSETS) if item.get("notified") else []
                        self.items.append({"title": item["title"], "day": item["day"],
                                           "start": item["start"], "notified": bool(notified_minutes),
                                           "notified_minutes": notified_minutes,
                                           "snooze_until": snooze_until})
                    except (KeyError, TypeError, ValueError):
                        continue
        except (FileNotFoundError, OSError, ValueError):
            pass

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(prefix="calendar-alerts-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(self.items, stream, ensure_ascii=False, indent=2)
            for attempt in range(5):
                try:
                    os.replace(name, self.path)
                    break
                except PermissionError:
                    if attempt == 4:
                        raise
                    time.sleep(0.05)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    @staticmethod
    def _matches(item: dict, title: str, day: str, start: str) -> bool:
        return item["title"] == title and item["day"] == day and item["start"] == start

    def add(self, title: str, day: str, start: str, now: datetime | None = None) -> bool:
        now = now or datetime.now().astimezone()
        if _start_at(day, start) <= now:
            return False
        if any(self._matches(item, title, day, start) for item in self.items):
            return True
        self.items.append({"title": title, "day": day, "start": start,
                           "notified": False, "notified_minutes": [], "snooze_until": None})
        self._save()
        return True

    def remove(self, title: str, day: str, start: str) -> None:
        remaining = [item for item in self.items if not self._matches(item, title, day, start)]
        if len(remaining) != len(self.items):
            self.items = remaining
            self._save()

    def snooze(self, title: str, day: str, start: str, minutes: int = 5,
               now: datetime | None = None) -> bool:
        now = now or datetime.now().astimezone()
        if minutes <= 0:
            raise ValueError("다시 알릴 시간을 정확히 지정해줘.")
        for item in self.items:
            if self._matches(item, title, day, start) and item["notified"]:
                item["snooze_until"] = (now + timedelta(minutes=minutes)).isoformat()
                self._save()
                return True
        return False

    def due(self, minutes: int | tuple[int, ...], now: datetime | None = None) -> list[dict]:
        offsets = (minutes,) if isinstance(minutes, int) else tuple(minutes)
        offsets = tuple(sorted({value for value in offsets if value > 0}, reverse=True))
        if not offsets:
            return []
        now = now or datetime.now().astimezone()
        found = []
        changed = False
        remaining = []
        for item in self.items:
            begins = _start_at(item["day"], item["start"])
            snooze_until = item.get("snooze_until")
            if snooze_until:
                resumed = datetime.fromisoformat(snooze_until)
                if resumed <= now:
                    if now - resumed <= timedelta(minutes=30):
                        item["snooze_until"] = None
                        found.append({**item, "snoozed": True})
                        changed = True
                    else:
                        changed = True
                        continue
                remaining.append(item)
                continue
            if begins <= now:
                changed = True
                continue
            notified_minutes = item.setdefault("notified_minutes", [])
            due_offsets = [value for value in offsets
                           if value not in notified_minutes and begins - timedelta(minutes=value) <= now]
            if due_offsets:
                # If Momo was closed across several reminder points, show only the
                # most recent one and mark earlier points as passed.
                reminder_minutes = min(due_offsets)
                item["notified_minutes"] = sorted(set(notified_minutes + due_offsets))
                item["notified"] = True
                found.append({**item, "reminder_minutes": reminder_minutes})
                changed = True
            remaining.append(item)
        self.items = remaining
        if changed:
            self._save()
        return found
