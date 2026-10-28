"""The friend edition remains independent of company tasks and data."""

import io
import json
import queue
import unittest
from pathlib import Path
from unittest.mock import patch

import assistant


class FriendEditionTest(unittest.TestCase):
    def test_no_company_task_integration(self):
        schema = json.loads(assistant.RESPONSE_SCHEMA.read_text(encoding="utf-8"))
        self.assertFalse(any(key.startswith("task_") for key in schema["properties"]))
        self.assertFalse(hasattr(assistant.DeskBuddy, "show_tasks"))
        self.assertEqual(set(assistant.DeskBuddy.load_settings()),
                         {"name", "theme", "mascot", "workdir", "ai_backend",
                          "window_width", "window_height"})
        self.assertEqual(assistant.DATA_DIR.name, "MomoFriends")

    def test_google_and_notion_requests_remain_available(self):
        self.assertTrue(assistant.DeskBuddy.is_drive_request("구글 드라이브에 폴더 만들어줘"))
        self.assertTrue(assistant.DeskBuddy.is_notion_request("노션에서 페이지 찾아줘"))
        self.assertTrue(assistant.DeskBuddy.is_today_briefing("오늘 브리핑해줘"))

    def test_friend_voice_is_sent_to_ai_without_skipping_the_task(self):
        class CaptureInput(io.StringIO):
            def close(self):
                self.value = self.getvalue()
                super().close()

        class FakeProcess:
            def __init__(self):
                self.stdin = CaptureInput()
                result = {"type": "item.completed", "item": {"type": "agent_message",
                          "text": json.dumps({"message": "처리함~"})}}
                self.stdout = io.StringIO(json.dumps(result) + "\n")

            def wait(self):
                return 0

        buddy = assistant.DeskBuddy.__new__(assistant.DeskBuddy)
        buddy.settings = {"ai_backend": "codex"}
        buddy.workdir = Path.cwd()
        buddy.events = queue.Queue()
        buddy.process = None
        fake = FakeProcess()
        with patch.object(assistant.DeskBuddy, "find_cli", return_value="codex.exe"), \
             patch.object(assistant.DeskBuddy, "read_guidelines", return_value=""), \
             patch("assistant.subprocess.Popen", return_value=fake):
            buddy.ask_ai("저녁 곱창 회식일정 추가해줘")
        self.assertIn("그걸 내가 어캐암~", fake.stdin.value)
        self.assertIn("요청한 일정 추가를 실제로 진행", fake.stdin.value)
        self.assertIn("저녁 곱창 회식일정 추가해줘", fake.stdin.value)
        self.assertEqual(buddy.events.get_nowait()[0], "result")


if __name__ == "__main__":
    unittest.main()
