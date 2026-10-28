"""Bounded Google Drive actions through Momo's own Chrome DevTools connection."""

from __future__ import annotations

import json
import queue
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime
from datetime import timezone
from urllib.parse import urlencode


DRIVE_ROOT = "https://drive.google.com/drive/u/0/my-drive"
CALENDAR_ROOT = "https://calendar.google.com/calendar/u/0/r"


class ChromeMCP:
    def __init__(self, endpoint: str) -> None:
        npx = shutil.which("npx.cmd") or shutil.which("npx")
        if not npx:
            raise ValueError("Google Drive 기능에는 Node.js의 npx가 필요해.")
        self.process = subprocess.Popen(
            ["cmd.exe", "/c", npx, "-y", "chrome-devtools-mcp@latest",
             f"--browserUrl={endpoint}", "--no-usage-statistics", "--no-performance-crux"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.responses: queue.Queue[dict] = queue.Queue()
        self.diagnostics: list[str] = []
        self.next_id = 1
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        try:
            self._send({"jsonrpc": "2.0", "id": self._id(), "method": "initialize",
                        "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                                   "clientInfo": {"name": "momo", "version": "0.8.1"}}})
            response = self._receive(1, timeout=45)
            if "error" in response:
                raise ValueError(f"Chrome 연결을 시작하지 못했어: {response['error']}")
            self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except Exception:
            self.close()
            raise

    def _id(self) -> int:
        value = self.next_id
        self.next_id += 1
        return value

    def _send(self, message: dict) -> None:
        if not self.process.stdin:
            raise ValueError("Chrome 연결 입력이 닫혔어.")
        self.process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        self.process.stdin.flush()

    def _read_stdout(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            try:
                self.responses.put(json.loads(line))
            except json.JSONDecodeError:
                self.diagnostics.append(line.strip())
                self.diagnostics = self.diagnostics[-10:]

    def _read_stderr(self) -> None:
        assert self.process.stderr is not None
        for line in self.process.stderr:
            self.diagnostics.append(line.strip())
            self.diagnostics = self.diagnostics[-10:]

    def _receive(self, request_id: int, timeout: float = 35) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None and self.responses.empty():
                raise ValueError("Chrome 연결이 종료됐어. " + " ".join(self.diagnostics[-2:])[-300:])
            try:
                response = self.responses.get(timeout=min(0.5, max(0.01, deadline - time.monotonic())))
            except queue.Empty:
                continue
            if response.get("id") == request_id:
                return response
        raise ValueError("Chrome 응답 시간이 초과됐어.")

    def call(self, name: str, arguments: dict | None = None, timeout: float = 35) -> str:
        request_id = self._id()
        self._send({"jsonrpc": "2.0", "id": request_id, "method": "tools/call",
                    "params": {"name": name, "arguments": arguments or {}}})
        response = self._receive(request_id, timeout)
        if response.get("error"):
            raise ValueError(f"Chrome 도구 오류: {response['error']}")
        result = response.get("result") or {}
        content = "\n".join(part.get("text", "") for part in result.get("content", [])
                            if isinstance(part, dict) and part.get("type") == "text")
        if result.get("isError"):
            raise ValueError("Chrome 도구 오류: " + content[-350:])
        return content

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def __enter__(self) -> ChromeMCP:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def _drive_page_id(pages: str) -> int | None:
    preferred = re.search(r"(?m)^(\d+): .*https://drive\.google\.com/drive/u/\d+/my-drive", pages)
    if preferred:
        return int(preferred.group(1))
    for line in pages.splitlines():
        match = re.search(r"^(\d+): .*https://drive\.google\.com/drive/", line)
        if match and not re.search(r"https://drive\.google\.com/drive/u/\d+/trash", line):
            return int(match.group(1))
    return None


def _trash_page_id(pages: str) -> int | None:
    match = re.search(r"(?m)^(\d+): .*https://drive\.google\.com/drive/u/\d+/trash", pages)
    return int(match.group(1)) if match else None


def _folder_row_uids(snapshot: str, name: str) -> list[str]:
    if not name or any(character in name for character in "\r\n"):
        raise ValueError("삭제할 폴더 이름을 정확히 알려줘.")
    found: list[str] = []
    lines = snapshot.splitlines()
    for index, line in enumerate(lines):
        match = re.search(r'\buid=(\S+) row "([^"]+)"', line)
        if not match:
            continue
        label = match.group(2)
        child = lines[index + 1] if index + 1 < len(lines) else ""
        exact_child = re.search(r'\buid=\S+ "([^"]+)"', child)
        if (label.startswith(name + " ") and re.search(r"(?:^| )폴더(?: |$)", label)
                and exact_child and exact_child.group(1) == name):
            found.append(match.group(1))
    return found


def _single_uid(snapshot: str, label: str) -> str | None:
    matches = re.findall(r'\buid=(\S+) button "([^"]+)"', snapshot)
    candidates = [uid for uid, text in matches if text.startswith(label)]
    return candidates[0] if len(candidates) == 1 else None


def _calendar_page_id(pages: str) -> int | None:
    match = re.search(r"(?m)^(\d+): .*https://calendar\.google\.com/calendar/u/\d+/r", pages)
    return int(match.group(1)) if match else None


def _selected_page_id(pages: str, host: str) -> int | None:
    for line in pages.splitlines():
        if host in line and "[selected]" in line:
            match = re.match(r"(\d+):", line)
            if match:
                return int(match.group(1))
    return None


def _calendar_time_label(start: str) -> str:
    try:
        hour, minute = (int(part) for part in start.split(":"))
        if not 0 <= hour < 24 or not 0 <= minute < 60:
            raise ValueError
    except ValueError as exc:
        raise ValueError("삭제할 일정의 시작 시각을 HH:MM으로 알려줘.") from exc
    return ("오전" if hour < 12 else "오후") + f" {hour % 12 or 12}:{minute:02d}"


def trash_calendar_event(endpoint: str, title: str, day: str, start: str) -> str:
    """Delete one precisely matched Calendar event from Momo's dedicated Chrome."""
    if not title.strip() or len(title) > 200:
        raise ValueError("삭제할 일정 제목을 정확히 알려줘.")
    try:
        target_day = datetime.strptime(day, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("삭제할 일정 날짜를 YYYY-MM-DD로 알려줘.") from exc
    time_label = _calendar_time_label(start)
    date_label = f"{target_day.year}년 {target_day.month}월 {target_day.day}일"
    with ChromeMCP(endpoint) as client:
        page_id = _calendar_page_id(client.call("list_pages"))
        if page_id is None:
            page_id = _calendar_page_id(client.call("new_page", {"url": CALENDAR_ROOT}, timeout=50))
        if page_id is None:
            raise ValueError("Google Calendar 탭을 열지 못했어. Google용 Chrome에서 로그인해줘.")
        client.call("select_page", {"pageId": page_id})
        snapshot = client.call("take_snapshot", {"pageId": page_id})
        if date_label not in snapshot or not re.search(r"\bmain description=", snapshot):
            target_url = f"{CALENDAR_ROOT}/day/{target_day.year}/{target_day.month}/{target_day.day}"
            page_id = _calendar_page_id(client.call("new_page", {"url": target_url}, timeout=50))
            if page_id is None:
                raise ValueError("요청한 날짜의 Calendar 화면을 열지 못했어.")
            snapshot = client.call("take_snapshot", {"pageId": page_id})
        dialog_close = _single_uid(snapshot, "닫기") if re.search(r'\bdialog "', snapshot) else None
        if dialog_close:
            client.call("click", {"pageId": page_id, "uid": dialog_close})
            snapshot = client.call("take_snapshot", {"pageId": page_id})
        candidates = []
        for uid, label in re.findall(r'\buid=(\S+) button "([^"\n]+)"', snapshot):
            if (f", {title}," in label and label.startswith(time_label + "~")
                    and date_label in label):
                candidates.append(uid)
        if not candidates:
            raise ValueError(f"{day} {start}의 '{title}' 일정을 찾지 못했어.")
        if len(candidates) != 1:
            raise ValueError("같은 제목과 시작 시각의 일정이 여러 개야. 삭제하지 않았어.")
        client.call("click", {"pageId": page_id, "uid": candidates[0]})
        snapshot = client.call("take_snapshot", {"pageId": page_id})
        dialog = re.search(r'\buid=\S+ dialog "([^"\n]+)"', snapshot)
        if not dialog or dialog.group(1) != title or date_label not in snapshot or time_label not in snapshot:
            raise ValueError("열린 일정의 제목·날짜·시각이 요청과 달라. 삭제하지 않았어.")
        delete = _single_uid(snapshot, "일정 삭제")
        if delete is None:
            raise ValueError("일정 삭제 버튼을 찾지 못했어. 캘린더 권한을 확인해줘.")
        client.call("click", {"pageId": page_id, "uid": delete})
        target_url = f"{CALENDAR_ROOT}/day/{target_day.year}/{target_day.month}/{target_day.day}"
        pages = client.call("new_page", {"url": target_url}, timeout=50)
        verify_page = _selected_page_id(pages, "calendar.google.com")
        if verify_page is None:
            raise ValueError("삭제 후 캘린더를 다시 열지 못했어.")
        for _ in range(8):
            time.sleep(0.5)
            snapshot = client.call("take_snapshot", {"pageId": verify_page})
            if date_label not in snapshot or not re.search(r"\bmain description=", snapshot):
                continue
            remaining = [label for _, label in re.findall(r'\buid=(\S+) button "([^"\n]+)"', snapshot)
                         if f", {title}," in label and label.startswith(time_label + "~")
                         and date_label in label]
            if not remaining and not re.search(r'\bdialog "', snapshot):
                return f"Google Calendar의 '{title}' ({day} {start}) 일정을 삭제하고 다시 연 화면에서 사라진 것을 확인했어."
        raise ValueError("일정 삭제 결과를 확인하지 못했어. 캘린더 화면을 다시 확인해줘.")


def create_calendar_event(endpoint: str, title: str, day: str, start: str, end: str) -> str:
    """Create one event through a prefilled Calendar editor and verify after reload."""
    if not title.strip() or len(title) > 200:
        raise ValueError("추가할 일정 제목을 정확히 알려줘.")
    try:
        begins = datetime.fromisoformat(f"{day}T{start}:00").astimezone()
        ends = datetime.fromisoformat(f"{day}T{end}:00").astimezone()
    except ValueError as exc:
        raise ValueError("일정 날짜와 시작·종료 시각을 정확히 알려줘.") from exc
    if ends <= begins or (ends - begins).total_seconds() > 86400:
        raise ValueError("종료 시각은 시작 시각보다 늦어야 해.")
    date_label = f"{begins.year}년 {begins.month}월 {begins.day}일"
    start_label = _calendar_time_label(start)
    end_label = _calendar_time_label(end)
    target_day = f"{CALENDAR_ROOT}/day/{begins.year}/{begins.month}/{begins.day}"
    dates = (begins.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "/" +
             ends.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    editor_url = "https://calendar.google.com/calendar/r/eventedit?" + urlencode({
        "action": "TEMPLATE", "text": title, "dates": dates,
        "stz": "Asia/Seoul", "etz": "Asia/Seoul"})
    with ChromeMCP(endpoint) as client:
        pages = client.call("new_page", {"url": target_day}, timeout=50)
        day_page = _selected_page_id(pages, "calendar.google.com")
        if day_page is None:
            raise ValueError("Google Calendar 날짜 화면을 열지 못했어.")
        snapshot = client.call("take_snapshot", {"pageId": day_page})
        if date_label not in snapshot or "calendar.google.com/calendar/" not in snapshot:
            raise ValueError("Google Calendar 로그인 또는 날짜 화면을 확인하지 못했어.")
        existing = [label for _, label in re.findall(r'\buid=(\S+) button "([^"\n]+)"', snapshot)
                    if f", {title}," in label and label.startswith(start_label + "~")
                    and date_label in label]
        if existing:
            return f"'{title}' ({day} {start}) 일정이 이미 캘린더에 있어. 중복 추가하지 않았어."
        pages = client.call("new_page", {"url": editor_url}, timeout=50)
        editor_page = _selected_page_id(pages, "calendar.google.com")
        if editor_page is None:
            raise ValueError("Google Calendar 일정 입력 화면을 열지 못했어.")
        snapshot = client.call("take_snapshot", {"pageId": editor_page})
        if not all(value in snapshot for value in (title, f"{begins.month}월 {begins.day}일",
                                                   start_label, end_label)):
            raise ValueError("입력 화면의 제목·날짜·시각이 요청과 달라서 저장하지 않았어.")
        save = _single_uid(snapshot, "저장")
        if save is None:
            raise ValueError("Google Calendar 저장 버튼을 찾지 못했어.")
        client.call("click", {"pageId": editor_page, "uid": save})
        pages = client.call("new_page", {"url": target_day}, timeout=50)
        verify_page = _selected_page_id(pages, "calendar.google.com")
        if verify_page is None:
            raise ValueError("저장 후 캘린더를 다시 열지 못했어.")
        for _ in range(8):
            time.sleep(0.5)
            snapshot = client.call("take_snapshot", {"pageId": verify_page})
            found = [label for _, label in re.findall(r'\buid=(\S+) button "([^"\n]+)"', snapshot)
                     if f", {title}," in label and label.startswith(start_label + "~")
                     and date_label in label]
            if found:
                return f"Google Calendar에 '{title}' ({day} {start}~{end}) 일정을 저장하고 새 화면에서 확인했어."
        raise ValueError("저장 후 새 캘린더 화면에서 일정을 확인하지 못했어.")


def trash_drive_folder(endpoint: str, name: str) -> str:
    """Move one exactly named Drive folder to trash; never permanently delete."""
    name = name.strip()
    if not name or len(name) > 200 or name in {".", ".."}:
        raise ValueError("삭제할 Drive 폴더 이름을 정확히 알려줘.")
    with ChromeMCP(endpoint) as client:
        page_id = _drive_page_id(client.call("list_pages"))
        if page_id is None:
            pages = client.call("new_page", {"url": DRIVE_ROOT}, timeout=50)
            page_id = _drive_page_id(pages)
        if page_id is None:
            raise ValueError("Google Drive 탭을 열지 못했어. Google용 Chrome에서 로그인해줘.")
        client.call("select_page", {"pageId": page_id})
        snapshot = client.call("take_snapshot", {"pageId": page_id})
        if "drive.google.com/drive/" not in snapshot:
            raise ValueError("Google Drive 로그인 화면이야. Google용 Chrome에서 직접 로그인해줘.")
        search = re.search(r'\buid=(\S+) textbox "드라이브에서 검색"', snapshot)
        if not search:
            raise ValueError("Drive 검색창을 찾지 못했어. Google 로그인 상태를 확인해줘.")
        client.call("fill", {"pageId": page_id, "uid": search.group(1), "value": name})
        client.call("press_key", {"pageId": page_id, "key": "Enter"})
        rows = []
        for _ in range(8):
            time.sleep(0.5)
            snapshot = client.call("take_snapshot", {"pageId": page_id})
            rows = _folder_row_uids(snapshot, name)
            if rows:
                break
        pages = client.call("list_pages")
        trash_id = _trash_page_id(pages)
        if trash_id is None:
            trash_id = _trash_page_id(client.call("new_page", {
                "url": "https://drive.google.com/drive/u/0/trash"}, timeout=50))
        trashed_rows: list[str] = []
        if trash_id is not None:
            client.call("select_page", {"pageId": trash_id})
            trash_snapshot = client.call("take_snapshot", {"pageId": trash_id})
            trashed_rows = _folder_row_uids(trash_snapshot, name)
        if trashed_rows and rows:
            return (f"'{name}' 폴더가 이미 휴지통에 있고 Drive에도 같은 이름의 다른 폴더가 있어. "
                    "다른 폴더는 건드리지 않았어. 삭제할 폴더의 위치를 알려줘.")
        if trashed_rows:
            return f"Drive의 '{name}' 폴더는 이미 휴지통에 있어."
        if not rows:
            raise ValueError(f"Drive에서 '{name}' 폴더를 찾지 못했어.")
        if len(rows) != 1:
            raise ValueError(f"'{name}' 폴더가 여러 개야. 위치를 더 정확히 알려줘.")
        client.call("select_page", {"pageId": page_id})
        client.call("click", {"pageId": page_id, "uid": rows[0]})
        snapshot = client.call("take_snapshot", {"pageId": page_id})
        trash_button = _single_uid(snapshot, "휴지통으로 이동")
        if trash_button is None:
            raise ValueError("Drive에서 휴지통으로 이동 버튼을 찾지 못했어. 권한을 확인해줘.")
        client.call("click", {"pageId": page_id, "uid": trash_button})
        for _ in range(6):
            time.sleep(0.5)
            snapshot = client.call("take_snapshot", {"pageId": page_id})
            if not _folder_row_uids(snapshot, name):
                return f"Drive의 '{name}' 폴더를 휴지통으로 이동했고 목록에서 사라진 것을 확인했어."
        raise ValueError("Drive에서 휴지통 이동 결과를 확인하지 못했어. 다시 확인해줘.")
