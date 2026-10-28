"""Import a KakaoTalk text export as private, retrievable conversation examples."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

import win32crypt


BRACKET_MESSAGE = re.compile(r"^\[(?P<speaker>[^\]]{1,80})\]\s*\[[^\]]+\]\s*(?P<text>.*)$")
COLON_MESSAGE = re.compile(
    r"^(?:(?:\d{4}[.-]\s*\d{1,2}[.-]\s*\d{1,2}|\d{4}년\s*\d{1,2}월\s*\d{1,2}일)"
    r"[^,]*,\s*)?(?P<speaker>[^:]{1,80})\s*:\s*(?P<text>.+)$")
DATE_LINE = re.compile(r"^(?:-+|=+|\d{4}년\s*\d{1,2}월\s*\d{1,2}일)")
URL = re.compile(r"https?://\S+", re.IGNORECASE)
EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?<!\d)0\d{1,2}[- ]?\d{3,4}[- ]?\d{4}(?!\d)")
WORD = re.compile(r"[가-힣A-Za-z0-9]{2,}")


def _clean(value: str, limit: int) -> str:
    value = URL.sub("<링크>", value)
    value = EMAIL.sub("<이메일>", value)
    value = PHONE.sub("<연락처>", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:limit]


def decode_export(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    for encoding in ("utf-8-sig", "cp949"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("대화 파일의 문자 인코딩을 읽지 못했어. 카카오톡에서 .txt로 다시 내보내줘.")


def parse_export(text: str, friend_name: str) -> list[dict[str, str]]:
    friend_name = friend_name.strip()
    if not friend_name:
        raise ValueError("따라 할 친구의 카톡 표시 이름을 입력해줘.")
    messages: list[tuple[str, str]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        match = BRACKET_MESSAGE.match(line) or COLON_MESSAGE.match(line)
        if match:
            speaker = match.group("speaker").strip()
            content = match.group("text").strip()
            if content:
                messages.append((speaker, content))
        elif messages and line and not DATE_LINE.match(line):
            speaker, previous = messages[-1]
            messages[-1] = (speaker, previous + " " + line)

    blocks: list[tuple[str, str]] = []
    for speaker, content in messages:
        if blocks and blocks[-1][0] == speaker:
            blocks[-1] = (speaker, blocks[-1][1] + " " + content)
        else:
            blocks.append((speaker, content))

    examples: list[dict[str, str]] = []
    for index, (speaker, content) in enumerate(blocks):
        if speaker != friend_name:
            continue
        reply = _clean(content, 500)
        if not reply or reply in {"사진", "동영상", "이모티콘", "파일"}:
            continue
        context = _clean(blocks[index - 1][1], 240) if index and blocks[index - 1][0] != friend_name else ""
        if context or len(reply) >= 8:
            examples.append({"context": context, "reply": reply})
    if not examples:
        raise ValueError(f"'{friend_name}' 이름의 대화를 찾지 못했어. 내보내기 파일의 표시 이름을 확인해줘.")
    return examples[-2000:]


def save_examples(path: Path, friend_name: str, examples: list[dict[str, str]]) -> None:
    content = json.dumps({"speaker": friend_name, "examples": examples}, ensure_ascii=False).encode("utf-8")
    encrypted = win32crypt.CryptProtectData(content, "Momo friend chat style", None, None, None, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix="chat-style-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(encrypted)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def load_examples(path: Path) -> dict:
    try:
        content = win32crypt.CryptUnprotectData(path.read_bytes(), None, None, None, 0)[1]
        data = json.loads(content.decode("utf-8"))
        if not isinstance(data.get("examples"), list):
            raise ValueError("저장된 말투 예시가 올바르지 않아. 다시 가져와줘.")
        return data
    except FileNotFoundError:
        return {"speaker": "", "examples": []}
    except (OSError, ValueError, KeyError, UnicodeDecodeError) as exc:
        raise ValueError("저장된 말투 예시를 읽지 못했어. 카톡 대화를 다시 가져와줘.") from exc


def select_examples(request: str, examples: list[dict[str, str]], limit: int = 6) -> list[dict[str, str]]:
    if not examples:
        return []
    tokens = set(WORD.findall(request.casefold()))
    scored = sorted(range(len(examples)), key=lambda index: (
        len(tokens & set(WORD.findall(examples[index]["context"].casefold()))),
        len(tokens & set(WORD.findall(examples[index]["reply"].casefold()))),
        index), reverse=True)
    chosen = scored[: min(3, limit)]
    for fraction in (0.15, 0.45, 0.75, 0.95):
        index = min(len(examples) - 1, int(len(examples) * fraction))
        if index not in chosen:
            chosen.append(index)
        if len(chosen) >= limit:
            break
    return [examples[index] for index in chosen[:limit]]


def style_context(request: str, data: dict) -> str:
    selected = select_examples(request, data.get("examples", []))
    if not selected:
        return ""
    lines = ["아래는 실제 카카오톡 대화에서 추린 말투 예시다. 예시의 말투와 반응 방식만 참고하고, "
             "예시 속 사실·개인정보를 현재 상황의 사실로 사용하거나 그대로 복사하지 않는다. "
             "사용자가 요청한 작업은 실제로 처리하고 결과를 정확하게 말한다."]
    for example in selected:
        if example["context"]:
            lines.append("상대: " + example["context"])
        lines.append("친구: " + example["reply"])
    return "\n".join(lines) + "\n\n"
