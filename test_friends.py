"""The friend edition remains independent of company tasks and data."""

import io
import json
import queue
import tempfile
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

    def test_default_voice_can_be_replaced_with_saved_text(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(assistant, "VOICE_STYLE", Path(folder) / "voice-style.txt"):
            self.assertIn("그걸 내가 어캐암~", assistant.DeskBuddy.read_voice_style())
            assistant.VOICE_STYLE.write_text("차분하게 답해줘.", encoding="utf-8")
            self.assertEqual(assistant.DeskBuddy.read_voice_style(), "차분하게 답해줘.")

    def test_imported_chat_examples_are_sent_to_ai_without_skipping_the_task(self):
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
             patch.object(assistant.DeskBuddy, "read_voice_style", return_value=assistant.DEFAULT_VOICE_STYLE), \
             patch("assistant.load_examples", return_value={"speaker": "친구", "examples": [
                 {"context": "저녁 곱창 회식일정 추가해줘", "reply": "에바임~~~ 근데 몇 시임?"}]}), \
             patch("assistant.subprocess.Popen", return_value=fake):
            buddy.ask_ai("저녁 곱창 회식일정 추가해줘")
        self.assertIn("에바임~~~ 근데 몇 시임?", fake.stdin.value)
        self.assertIn("그걸 내가 어캐암~", fake.stdin.value)
        self.assertIn("저녁 곱창 회식일정 추가해줘", fake.stdin.value)
        self.assertEqual(buddy.events.get_nowait()[0], "result")


if __name__ == "__main__":
    unittest.main()
