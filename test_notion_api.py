"""Notion trash requires an exact page match and verifies the API result."""

import unittest
from unittest.mock import Mock, patch

from notion_api import _same_requested_event_title, trash_page


class NotionTrashTest(unittest.TestCase):
    def test_notion_event_title_with_timestamp(self):
        actual = "당산 옛날 곱창 회식 2026-10-28T17:30:00.000+09:00"
        self.assertTrue(_same_requested_event_title(actual, "당산 옛날 곱창 회식"))
        self.assertTrue(_same_requested_event_title(
            actual, "당산 옛날 곱창 회식 @오늘 오후 5:30 (GMT+9)"))
        self.assertFalse(_same_requested_event_title(
            actual, "당산 옛날 곱창 회식 @오늘 오후 6:30 (GMT+9)"))
        self.assertFalse(_same_requested_event_title(
            "당산 옛날 곱창 회식 다른 페이지", "당산 옛날 곱창 회식"))

    def test_event_page_trashes_after_title_validation(self):
        page_id = "40786778-0f42-8010-b596-e3b5fbf11224"
        before = Mock(ok=True, status_code=200)
        before.json.return_value = {"object": "page", "id": page_id,
                                    "in_trash": False, "properties": {
                                        "title": {"type": "title", "title": [{"plain_text":
                                            "당산 옛날 곱창 회식 2026-10-28T17:30:00.000+09:00"}]}}}
        after = Mock(ok=True, status_code=200)
        after.json.return_value = {"id": page_id, "in_trash": True}
        with patch("notion_api.requests.get", return_value=before), \
             patch("notion_api.requests.patch", return_value=after) as update:
            result = trash_page("token", page_id,
                                "당산 옛날 곱창 회식 @오늘 오후 5:30 (GMT+9)")
        self.assertIn("휴지통으로 이동", result)
        update.assert_called_once()

    def test_trashes_exact_page(self):
        before = Mock(ok=True, status_code=200)
        before.json.return_value = {"object": "page", "id": "40786778-0f42-8159-ab9f-e4d92f545b52",
                                    "in_trash": False, "properties": {
                                        "title": {"type": "title", "title": [{"plain_text": "test"}]}}}
        after = Mock(ok=True, status_code=200)
        after.json.return_value = {"id": "40786778-0f42-8159-ab9f-e4d92f545b52", "in_trash": True}
        with patch("notion_api.requests.get", return_value=before), \
             patch("notion_api.requests.patch", return_value=after) as update:
            result = trash_page("token", "407867780f428159ab9fe4d92f545b52", "test")
        self.assertIn("휴지통으로 이동", result)
        self.assertEqual(update.call_args.kwargs["json"], {"in_trash": True})

    def test_different_title_is_not_trashed(self):
        before = Mock(ok=True, status_code=200)
        before.json.return_value = {"object": "page", "id": "40786778-0f42-8159-ab9f-e4d92f545b52",
                                    "in_trash": False, "properties": {
                                        "title": {"type": "title", "title": [{"plain_text": "other"}]}}}
        with patch("notion_api.requests.get", return_value=before), \
             patch("notion_api.requests.patch") as update:
            with self.assertRaises(ValueError):
                trash_page("token", "407867780f428159ab9fe4d92f545b52", "test")
        update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
