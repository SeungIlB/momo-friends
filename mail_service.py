"""Gmail OAuth and Mailplug mail access with Windows-protected credentials."""

from __future__ import annotations

import base64
import imaplib
import json
import os
import re
import smtplib
import ssl
import tempfile
from email import message_from_bytes
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path

import requests
import win32crypt


GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.send",
                "https://www.googleapis.com/auth/gmail.readonly"]
GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
MAILPLUG_SMTP = "smtp.mailplug.co.kr"
MAILPLUG_IMAP = "imap.mailplug.co.kr"


def save_private(path: Path, data: dict) -> None:
    encrypted = win32crypt.CryptProtectData(json.dumps(data, ensure_ascii=False).encode("utf-8"),
                                            "Momo mail account", None, None, None, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix="mail-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(encrypted)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def load_private(path: Path) -> dict:
    try:
        raw = win32crypt.CryptUnprotectData(path.read_bytes(), None, None, None, 0)[1]
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("저장 형식 오류")
        return data
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        raise ValueError("저장된 메일 연결 정보를 읽지 못했어. 계정을 다시 연결해줘.") from exc


def connect_gmail(client_file: Path, token_path: Path) -> str:
    from google_auth_oauthlib.flow import InstalledAppFlow

    try:
        client = json.loads(client_file.read_text(encoding="utf-8"))
        if not isinstance(client.get("installed"), dict):
            raise ValueError("Google Cloud의 데스크톱 OAuth 클라이언트 JSON 파일을 선택해줘.")
        flow = InstalledAppFlow.from_client_secrets_file(str(client_file), GMAIL_SCOPES)
        credentials = flow.run_local_server(port=0, open_browser=True, prompt="consent")
        response = requests.get(GMAIL_API + "/profile", headers=_gmail_headers(credentials), timeout=20)
        response.raise_for_status()
        address = response.json().get("emailAddress", "")
        if not address:
            raise ValueError("연결된 Gmail 주소를 확인하지 못했어.")
        save_private(token_path, {"credentials": json.loads(credentials.to_json()), "address": address})
        return address
    except (OSError, requests.RequestException, KeyError, ValueError) as exc:
        raise ValueError(f"Gmail 연결에 실패했어: {exc}") from exc


def _gmail_credentials(token_path: Path):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    data = load_private(token_path)
    if not data.get("credentials"):
        raise ValueError("Gmail 계정을 먼저 연결해줘.")
    credentials = Credentials.from_authorized_user_info(data["credentials"], GMAIL_SCOPES)
    if not credentials.valid:
        credentials.refresh(Request())
        save_private(token_path, {"credentials": json.loads(credentials.to_json()),
                                  "address": data.get("address", "")})
    return credentials, data.get("address", "")


def _gmail_headers(credentials) -> dict[str, str]:
    return {"Authorization": "Bearer " + credentials.token, "Accept": "application/json"}


def validate_recipients(value: str) -> list[str]:
    recipients = [part.strip() for part in re.split(r"[,;]", value) if part.strip()]
    if not 1 <= len(recipients) <= 10:
        raise ValueError("받는 사람의 이메일 주소를 1~10개 입력해줘.")
    for address in recipients:
        parsed = parseaddr(address)[1]
        if (parsed != address or not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", address)
                or "\r" in address or "\n" in address):
            raise ValueError(f"이메일 주소를 확인해줘: {address}")
    return recipients


def _message(sender: str, recipients: list[str], subject: str, body: str) -> EmailMessage:
    if not subject.strip() or not body.strip() or "\r" in subject or "\n" in subject:
        raise ValueError("메일 제목과 본문을 확인해줘.")
    mail = EmailMessage()
    mail["From"] = sender
    mail["To"] = ", ".join(recipients)
    mail["Subject"] = subject.strip()
    mail.set_content(body.strip())
    return mail


def send_gmail(token_path: Path, to: str, subject: str, body: str) -> None:
    credentials, address = _gmail_credentials(token_path)
    if not address:
        raise ValueError("Gmail 발신 주소를 확인하지 못했어. 계정을 다시 연결해줘.")
    mail = _message(address, validate_recipients(to), subject, body)
    raw = base64.urlsafe_b64encode(mail.as_bytes()).decode("ascii")
    response = requests.post(GMAIL_API + "/messages/send", headers=_gmail_headers(credentials),
                             json={"raw": raw}, timeout=30)
    response.raise_for_status()
    if not response.json().get("id"):
        raise ValueError("Gmail의 발송 결과를 확인하지 못했어.")


def send_mailplug(account_path: Path, to: str, subject: str, body: str) -> None:
    account = load_private(account_path)
    address, password = account.get("address", ""), account.get("app_password", "")
    if not address or not password:
        raise ValueError("메일플러그 계정을 먼저 연결해줘.")
    mail = _message(address, validate_recipients(to), subject, body)
    with smtplib.SMTP_SSL(MAILPLUG_SMTP, 465, context=ssl.create_default_context(), timeout=25) as server:
        server.login(address, password)
        server.send_message(mail)


def verify_mailplug(address: str, password: str) -> None:
    validate_recipients(address)
    if not password:
        raise ValueError("메일플러그 앱 비밀번호를 입력해줘.")
    with smtplib.SMTP_SSL(MAILPLUG_SMTP, 465, context=ssl.create_default_context(), timeout=25) as server:
        server.login(address, password)


def _decode(value: str) -> str:
    try:
        return str(make_header(decode_header(value)))
    except (LookupError, UnicodeError, ValueError):
        return value


def recent_gmail(token_path: Path, limit: int = 5) -> list[dict[str, str]]:
    credentials, _ = _gmail_credentials(token_path)
    response = requests.get(GMAIL_API + "/messages", headers=_gmail_headers(credentials),
                            params={"q": "in:inbox", "maxResults": limit}, timeout=20)
    response.raise_for_status()
    messages = []
    for item in response.json().get("messages", []):
        detail = requests.get(GMAIL_API + "/messages/" + item["id"], headers=_gmail_headers(credentials),
                              params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]}, timeout=20)
        detail.raise_for_status()
        data = detail.json()
        headers = {entry["name"].lower(): _decode(entry["value"])
                   for entry in data.get("payload", {}).get("headers", [])}
        messages.append({"from": headers.get("from", ""), "subject": headers.get("subject", "(제목 없음)"),
                         "date": headers.get("date", ""), "snippet": data.get("snippet", "")[:160]})
    return messages


def recent_mailplug(account_path: Path, limit: int = 5) -> list[dict[str, str]]:
    account = load_private(account_path)
    address, password = account.get("address", ""), account.get("app_password", "")
    if not address or not password:
        raise ValueError("메일플러그 계정을 먼저 연결해줘.")
    with imaplib.IMAP4_SSL(MAILPLUG_IMAP, 993, ssl_context=ssl.create_default_context(), timeout=25) as server:
        server.login(address, password)
        status, _ = server.select("INBOX", readonly=True)
        if status != "OK":
            raise ValueError("메일플러그 받은편지함을 열지 못했어. IMAP 사용 설정을 확인해줘.")
        status, data = server.search(None, "ALL")
        if status != "OK":
            raise ValueError("메일플러그 받은편지함을 읽지 못했어.")
        messages = []
        for number in reversed(data[0].split()[-limit:]):
            status, parts = server.fetch(number, "(BODY.PEEK[HEADER])")
            if status != "OK":
                continue
            raw = next((part[1] for part in parts if isinstance(part, tuple)), b"")
            headers = message_from_bytes(raw)
            messages.append({"from": _decode(headers.get("From", "")),
                             "subject": _decode(headers.get("Subject", "(제목 없음)")),
                             "date": headers.get("Date", ""), "snippet": ""})
        return messages
