"""The friend edition remains independent of company tasks and data."""

import json
import unittest

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


if __name__ == "__main__":
    unittest.main()
