"""Safety checks for the exact Drive folder chosen for trash."""

import unittest
from unittest.mock import patch

from google_browser import (_folder_row_uids, _drive_page_id, _calendar_time_label,
                            create_calendar_event, trash_drive_folder)


class DriveFolderSelectionTest(unittest.TestCase):
    def test_calendar_time_label(self):
        self.assertEqual(_calendar_time_label("17:30"), "오후 5:30")
        self.assertEqual(_calendar_time_label("00:05"), "오전 12:05")

    def test_exact_folder_name_only(self):
        snapshot = '\n'.join([
            'uid=1_10 row "test 폴더 나님이 소유함" selectable',
            '  uid=1_11 "test"',
            'uid=1_12 row "test 2 폴더 나님이 소유함" selectable',
            '  uid=1_13 "test 2"',
            'uid=1_14 row "test 문서 나님이 소유함" selectable',
            '  uid=1_15 "test"',
        ])
        self.assertEqual(_folder_row_uids(snapshot, "test"), ["1_10"])

    def test_prefers_my_drive_over_other_tabs(self):
        pages = ("1: test (https://drive.google.com/drive/u/0/folders/abc)\n"
                 "2: My Drive (https://drive.google.com/drive/u/0/my-drive)\n"
                 "3: Trash (https://drive.google.com/drive/u/0/trash)")
        self.assertEqual(_drive_page_id(pages), 2)

    def test_existing_trashed_name_never_deletes_another_folder(self):
        root = ('uid=2_0 RootWebArea url="https://drive.google.com/drive/u/0/my-drive"\n'
                'uid=2_1 textbox "드라이브에서 검색"')
        results = ('uid=2_0 RootWebArea url="https://drive.google.com/drive/u/0/search?q=test"\n'
                   'uid=2_10 row "test 폴더 sobang"\n  uid=2_11 "test"')
        trash = ('uid=3_0 RootWebArea url="https://drive.google.com/drive/u/0/trash"\n'
                 'uid=3_10 row "test 폴더 휴지통으로 이동됨"\n  uid=3_11 "test"')

        class FakeClient:
            def __init__(self):
                self.searched = False
                self.clicked = False

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                pass

            def call(self, tool, args=None, **_kwargs):
                if tool == "list_pages":
                    return ("2: My Drive (https://drive.google.com/drive/u/0/my-drive)\n"
                            "3: Trash (https://drive.google.com/drive/u/0/trash)")
                if tool == "press_key":
                    self.searched = True
                if tool == "take_snapshot":
                    return trash if args["pageId"] == 3 else (results if self.searched else root)
                if tool == "click":
                    self.clicked = True
                return ""

        client = FakeClient()
        with patch("google_browser.ChromeMCP", return_value=client), \
             patch("google_browser.time.sleep"):
            outcome = trash_drive_folder("http://127.0.0.1:53728", "test")
        self.assertIn("같은 이름의 다른 폴더", outcome)
        self.assertFalse(client.clicked)

    def test_calendar_create_uses_prefilled_editor_and_verifies(self):
        class FakeClient:
            def __init__(self):
                self.urls = []
                self.saved = False

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                pass

            def call(self, tool, args=None, **_kwargs):
                if tool == "new_page":
                    self.urls.append(args["url"])
                    page = len(self.urls)
                    return f"{page}: Google Calendar ({args['url']}) [selected]"
                if tool == "take_snapshot":
                    if args["pageId"] == 2:
                        return ('uid=2_0 RootWebArea "Google Calendar" '
                                'url="https://calendar.google.com/calendar/r/eventedit"\n'
                                'uid=2_1 textbox "당산 옛날 곱창 회식"\n'
                                'uid=2_2 "10월 28일 오후 5:30 오후 6:30"\n'
                                'uid=2_3 button "저장"')
                    return ('uid=1_0 RootWebArea "Google Calendar" '
                            'url="https://calendar.google.com/calendar/u/0/r/day"\n'
                            'uid=1_1 main description="2026년 10월 28일"\n' +
                            ('uid=1_2 button "오후 5:30~오후 6:30, 당산 옛날 곱창 회식, 백승일, 2026년 10월 28일"'
                             if self.saved else ''))
                if tool == "click":
                    self.saved = True
                return ""

        client = FakeClient()
        with patch("google_browser.ChromeMCP", return_value=client), \
             patch("google_browser.time.sleep"):
            result = create_calendar_event("http://127.0.0.1:9222", "당산 옛날 곱창 회식",
                                           "2026-10-28", "17:30", "18:30")
        self.assertIn("새 화면에서 확인", result)
        self.assertIn("action=TEMPLATE", client.urls[1])
        self.assertTrue(client.saved)


if __name__ == "__main__":
    unittest.main()
