"""Scoped Notion page trash operation for explicitly requested deletions."""

from __future__ import annotations

import re
from datetime import datetime

import requests


NOTION_VERSION = "2026-03-11"
BASE = "https://api.notion.com/v1"


def _headers(token: str) -> dict[str, str]:
    if not token.strip():
        raise ValueError("Notion API 토큰을 먼저 연결해줘.")
    return {"Authorization": "Bearer " + token.strip(),
            "Notion-Version": NOTION_VERSION, "Content-Type": "application/json"}


def verify_token(token: str) -> None:
    response = requests.get(BASE + "/users/me", headers=_headers(token), timeout=15)
    if not response.ok:
        raise ValueError(f"Notion 토큰을 확인하지 못했어 (HTTP {response.status_code}).")


def _title(page: dict) -> str:
    for prop in page.get("properties", {}).values():
        if prop.get("type") == "title":
            return "".join(part.get("plain_text") or part.get("text", {}).get("content", "")
                           for part in prop.get("title", []))
    return ""


def _same_requested_event_title(actual: str, expected: str) -> bool:
    if actual == expected:
        return True
    match = re.fullmatch(
        r"(.+?) (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2}))",
        actual)
    if not match:
        return False
    base, timestamp = match.groups()
    if expected == base:
        return True
    if not expected.startswith(base + " @"):
        return False
    shown_time = re.search(r"(오전|오후)\s*(\d{1,2}):(\d{2})", expected)
    if not shown_time:
        return False
    meridiem, hour, minute = shown_time.groups()
    hour = int(hour) % 12 + (12 if meridiem == "오후" else 0)
    actual_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if (actual_time.hour, actual_time.minute) != (hour, int(minute)):
        return False
    if "@오늘" in expected and actual_time.date() != datetime.now().astimezone().date():
        return False
    return True


def trash_page(token: str, page_id: str, expected_title: str) -> str:
    """Verify page ID and exact title, then move that page to Trash."""
    normalized_id = page_id.replace("-", "")
    if not re.fullmatch(r"[0-9a-fA-F]{32}", normalized_id):
        raise ValueError("Notion 페이지 ID가 정확하지 않아.")
    if not expected_title or len(expected_title) > 200:
        raise ValueError("Notion 페이지 제목을 정확히 알려줘.")
    url = BASE + "/pages/" + normalized_id
    headers = _headers(token)
    response = requests.get(url, headers=headers, timeout=20)
    if response.status_code == 404:
        raise ValueError("Notion 연결이 이 페이지에 접근할 수 없어. 페이지를 Integration에 공유해줘.")
    if not response.ok:
        raise ValueError(f"Notion 페이지를 확인하지 못했어 (HTTP {response.status_code}).")
    page = response.json()
    if page.get("object") != "page" or page.get("id", "").replace("-", "").casefold() != normalized_id.casefold():
        raise ValueError("Notion 페이지 ID가 일치하지 않아.")
    actual_title = _title(page)
    if not _same_requested_event_title(actual_title, expected_title):
        raise ValueError(f"페이지 제목이 달라서 이동하지 않았어: '{actual_title}'.")
    if page.get("in_trash"):
        return f"Notion의 '{actual_title}' 페이지는 이미 휴지통에 있어."
    updated = requests.patch(url, headers=headers, json={"in_trash": True}, timeout=20)
    if not updated.ok:
        raise ValueError(f"Notion 휴지통 이동에 실패했어 (HTTP {updated.status_code}).")
    result = updated.json()
    if result.get("id", "").replace("-", "").casefold() != normalized_id.casefold() or not result.get("in_trash"):
        raise ValueError("Notion 휴지통 이동 결과를 확인하지 못했어.")
    return f"Notion의 '{actual_title}' 페이지를 휴지통으로 이동했어."
