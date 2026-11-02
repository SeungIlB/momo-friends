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


SCHEDULE_NOTES_PAGE = "📝일정 메모"
SCHEDULE_NOTES_DATABASE = "일정 메모"
SCHEDULE_NOTE_PROPERTIES = {
    "일정": {"title": {}}, "시작 시각": {"date": {}}, "캘린더": {"rich_text": {}},
    "이벤트 ID": {"rich_text": {}}, "매핑 키": {"rich_text": {}},
    "Google Calendar URL": {"url": {}}, "요약 메모": {"rich_text": {}},
    "준비 상태": {"select": {"options": [
        {"name": "메모 있음", "color": "blue"}, {"name": "준비 중", "color": "yellow"},
        {"name": "준비 완료", "color": "green"},
    ]}},
}


def ensure_schedule_notes_database(token: str) -> tuple[str, str, bool]:
    """Find or create the schedule-notes inline database under the user's page."""
    headers = _headers(token)
    page_id, _ = find_page(token, SCHEDULE_NOTES_PAGE)
    children_url = f"{BASE}/blocks/{page_id}/children"
    cursor = None
    database = None
    for _ in range(10):
        params = {"page_size": 100}
        if cursor:
            params["start_cursor"] = cursor
        response = requests.get(children_url, headers=headers, params=params, timeout=20)
        if not response.ok:
            raise ValueError(f"일정 메모 페이지를 읽지 못했어 (HTTP {response.status_code}).")
        data = response.json()
        for block in data.get("results", []):
            if block.get("type") == "child_database" and block.get("child_database", {}).get("title") == SCHEDULE_NOTES_DATABASE:
                database = block
                break
        if database or not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    created = False
    if database is None:
        response = requests.post(BASE + "/databases", headers=headers, json={
            "parent": {"type": "page_id", "page_id": page_id},
            "title": [{"type": "text", "text": {"content": SCHEDULE_NOTES_DATABASE}}],
            "is_inline": True,
            "initial_data_source": {"properties": SCHEDULE_NOTE_PROPERTIES},
        }, timeout=25)
        if not response.ok:
            detail = response.json().get("message", "")
            raise ValueError(f"일정 메모 데이터베이스를 만들지 못했어 (HTTP {response.status_code}). {detail}".strip())
        database = response.json()
        created = True

    database_id = database.get("id")
    data_sources = database.get("data_sources") or []
    data_source_id = next((item.get("id") for item in data_sources if item.get("id")), None)
    if not data_source_id and database_id:
        response = requests.get(f"{BASE}/databases/{database_id}", headers=headers, timeout=20)
        if response.ok:
            data_sources = response.json().get("data_sources") or []
            data_source_id = next((item.get("id") for item in data_sources if item.get("id")), None)
    if not database_id or not data_source_id:
        raise ValueError("데이터베이스는 찾았지만 Notion API가 data source를 돌려주지 않았어. Notion 연결 권한과 API 버전을 확인해줘.")

    response = requests.get(f"{BASE}/data_sources/{data_source_id}", headers=headers, timeout=20)
    if not response.ok:
        raise ValueError(f"일정 메모 데이터베이스 구조를 읽지 못했어 (HTTP {response.status_code}).")
    current = response.json().get("properties", {})
    missing = {name: spec for name, spec in SCHEDULE_NOTE_PROPERTIES.items() if name not in current}
    if missing:
        updated = requests.patch(f"{BASE}/data_sources/{data_source_id}", headers=headers,
                                 json={"properties": missing}, timeout=20)
        if not updated.ok:
            raise ValueError(f"일정 메모 데이터베이스 열을 준비하지 못했어 (HTTP {updated.status_code}).")
    return database_id, data_source_id, created


def rename_schedule_note(token: str, old_title: str, new_title: str) -> str:
    """Rename one schedule-note row by its exact title, refusing ambiguous matches."""
    old_title, new_title = old_title.strip(), new_title.strip()
    if not old_title or not new_title or len(old_title) > 200 or len(new_title) > 200:
        raise ValueError("바꿀 메모 제목을 확인해줘.")
    if old_title == new_title:
        return f"메모 제목이 이미 ‘{new_title}’이야."
    _, data_source_id, _ = ensure_schedule_notes_database(token)
    headers = _headers(token)
    response = requests.get(f"{BASE}/data_sources/{data_source_id}", headers=headers, timeout=20)
    if not response.ok:
        raise ValueError(f"일정 메모 데이터베이스를 확인하지 못했어 (HTTP {response.status_code}).")
    properties = response.json().get("properties", {})
    title_property = next((name for name, prop in properties.items() if prop.get("type") == "title"), None)
    if not title_property:
        raise ValueError("일정 메모 데이터베이스에 제목 열이 없어.")

    matches = []
    cursor = None
    for _ in range(10):
        payload = {"filter": {"property": title_property, "title": {"equals": old_title}},
                   "page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        response = requests.post(f"{BASE}/data_sources/{data_source_id}/query",
                                 headers=headers, json=payload, timeout=25)
        if response.status_code == 401:
            raise ValueError("Notion API 토큰이 만료됐거나 유효하지 않아. 톱니 → Notion API 연결 설정에서 다시 입력해줘.")
        if not response.ok:
            raise ValueError(f"일정 메모 검색에 실패했어 (HTTP {response.status_code}).")
        data = response.json()
        matches.extend(page for page in data.get("results", [])
                       if page.get("object") == "page" and not page.get("in_trash")
                       and _title(page) == old_title)
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
        if not cursor:
            raise ValueError("일정 메모 검색 결과를 끝까지 확인하지 못했어.")
    else:
        raise ValueError("같은 제목의 메모가 많아. 날짜나 시간도 함께 알려줘.")
    if not matches:
        raise ValueError(f"‘{old_title}’ 메모를 일정 메모 데이터베이스에서 찾지 못했어.")
    if len(matches) > 1:
        dates = []
        for page in matches[:5]:
            for prop in page.get("properties", {}).values():
                if prop.get("type") == "date" and prop.get("date", {}).get("start"):
                    dates.append(prop["date"]["start"])
                    break
        detail = " (" + ", ".join(dates) + ")" if dates else ""
        raise ValueError(f"‘{old_title}’ 메모가 {len(matches)}개 있어{detail}. 날짜를 지정해줘.")

    page_id = matches[0].get("id")
    updated = requests.patch(f"{BASE}/pages/{page_id}", headers=headers, json={
        "properties": {title_property: {"title": [{"type": "text", "text": {"content": new_title}}]}}
    }, timeout=25)
    if not updated.ok:
        raise ValueError(f"메모 제목 수정에 실패했어 (HTTP {updated.status_code}).")
    if _title(updated.json()) != new_title:
        raise ValueError("Notion 응답에서 바뀐 제목을 확인하지 못했어.")
    return f"Notion 일정 메모 ‘{old_title}’을(를) ‘{new_title}’(으)로 바꿨어."


def find_page(token: str, title: str) -> tuple[str, str]:
    """Find one accessible, non-trashed page by its exact title."""
    title = title.strip()
    if not title or len(title) > 200:
        raise ValueError("삭제할 Notion 페이지 제목을 정확히 알려줘.")
    cursor = None
    matches: list[tuple[str, str]] = []
    for _ in range(10):
        body: dict = {"query": title, "filter": {"property": "object", "value": "page"},
                      "page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        response = requests.post(BASE + "/search", headers=_headers(token), json=body, timeout=20)
        if response.status_code == 401:
            raise ValueError("Notion API 토큰이 만료됐거나 유효하지 않아. 톱니 → Notion API 연결 설정에서 다시 입력해줘.")
        if not response.ok:
            raise ValueError(f"Notion 페이지 검색에 실패했어 (HTTP {response.status_code}).")
        data = response.json()
        for page in data.get("results", []):
            if page.get("object") != "page" or page.get("in_trash"):
                continue
            actual = _title(page)
            if _same_requested_event_title(actual, title):
                matches.append((page["id"], actual))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
        if not cursor:
            raise ValueError("Notion 검색 결과를 끝까지 확인하지 못했어.")
    else:
        raise ValueError("Notion 검색 결과가 너무 많아. 더 구체적인 페이지 제목으로 다시 요청해줘.")
    if not matches:
        raise ValueError(f"'{title}' 페이지를 찾지 못했어. Integration에 해당 페이지 접근 권한을 부여했는지 확인해줘.")
    if len(matches) != 1:
        raise ValueError(f"'{title}' 페이지가 {len(matches)}개야. 제목을 구분할 수 있게 바꾼 뒤 다시 요청해줘.")
    return matches[0]


def trash_page_by_title(token: str, title: str) -> str:
    page_id, actual_title = find_page(token, title)
    return trash_page(token, page_id, actual_title)


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
