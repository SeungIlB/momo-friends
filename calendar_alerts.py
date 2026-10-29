"""Local reminders for Calendar events confirmed by Momo."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path


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
                        self.items.append({"title": item["title"], "day": item["day"],
                                           "start": item["start"], "notified": bool(item.get("notified")),
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
            os.replace(name, self.path)
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
                           "notified": False, "snooze_until": None})
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

    def due(self, minutes: int, now: datetime | None = None) -> list[dict]:
        if minutes <= 0:
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
            if not item["notified"] and begins - timedelta(minutes=minutes) <= now:
                item["notified"] = True
                found.append(item.copy())
                changed = True
            remaining.append(item)
        self.items = remaining
        if changed:
            self._save()
        return found
