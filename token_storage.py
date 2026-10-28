"""Protect the optional Notion token with the current Windows account."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import win32crypt


def save_token(path: Path, token: str, service: str = "Notion") -> None:
    token = token.strip()
    if not token:
        raise ValueError(f"{service} API 토큰을 입력해줘.")
    encrypted = win32crypt.CryptProtectData(token.encode("utf-8"), f"Momo {service}", None, None, None, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix="notion-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(encrypted)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def load_token(path: Path, service: str = "Notion") -> str:
    try:
        return win32crypt.CryptUnprotectData(path.read_bytes(), None, None, None, 0)[1].decode("utf-8")
    except FileNotFoundError:
        return ""
    except (OSError, ValueError) as exc:
        raise ValueError(f"저장된 {service} 토큰을 읽지 못했어. 연결 설정에서 다시 입력해줘.") from exc
