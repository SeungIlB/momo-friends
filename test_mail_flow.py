"""AI may propose mail, while the app retains the send decision."""

import io
import json
import queue
import unittest
from pathlib import Path
from unittest.mock import patch

import assistant


class CaptureInput(io.StringIO):
    def close(self):
        self.value = self.getvalue()
        super().close()


class FakeProcess:
    def __init__(self, *args, **kwargs):
        self.stdin = CaptureInput()
        response = {"message": "내용 확인해줘", "mail_action": "send", "mail_provider": "gmail",
                    "mail_to": "friend@example.com", "mail_subject": "안부", "mail_body": "안녕"}
        event = {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(response)}}
        self.stdout = io.StringIO(json.dumps(event) + "\n")

    def wait(self):
        return 0


class MailFlowTest(unittest.TestCase):
    def _buddy(self):
        buddy = assistant.DeskBuddy.__new__(assistant.DeskBuddy)
        buddy.settings = {"ai_backend": "codex"}
        buddy.workdir = Path.cwd()
        buddy.events = queue.Queue()
        buddy.process = None
        return buddy

    def test_mail_request_only_prepares_confirmation_data(self):
        buddy = self._buddy()
        fake = FakeProcess()
        with patch.object(assistant.DeskBuddy, "find_cli", return_value="codex.exe"), \
             patch.object(assistant.DeskBuddy, "read_guidelines", return_value=""), \
             patch("assistant.subprocess.Popen", return_value=fake), \
             patch("mail_service.send_gmail") as send:
            buddy.ask_ai("Gmail로 friend@example.com에게 이메일 보내줘. 제목 안부, 내용 안녕")
        kind, value = buddy.events.get_nowait()
        self.assertEqual(kind, "result")
        self.assertEqual(json.loads(value)["mail_to"], "friend@example.com")
        self.assertIn("발송 전 내용을 사용자에게 보여주고", fake.stdin.value)
        send.assert_not_called()

    def test_unrelated_request_cannot_trigger_mail_preview(self):
        buddy = self._buddy()
        with patch.object(assistant.DeskBuddy, "find_cli", return_value="codex.exe"), \
             patch.object(assistant.DeskBuddy, "read_guidelines", return_value=""), \
             patch("assistant.subprocess.Popen", return_value=FakeProcess()):
            buddy.ask_ai("안녕")
        self.assertIsNone(json.loads(buddy.events.get_nowait()[1])["mail_action"])


if __name__ == "__main__":
    unittest.main()
