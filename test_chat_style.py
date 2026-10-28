"""KakaoTalk export import and local style example selection."""

import tempfile
import unittest
from pathlib import Path

from chat_style import decode_export, load_examples, parse_export, save_examples, select_examples, style_context


class ChatStyleTest(unittest.TestCase):
    def test_bracket_export_groups_friend_burst_with_previous_message(self):
        text = ("[나] [오후 5:19] 저녁 곱창 회식일정 추가해줘\n"
                "[친구A] [오후 5:20] 그건 좀 웃김~\n"
                "[친구A] [오후 5:20] 몇 시인지 알려줘\n"
                "[나] [오후 5:21] 내일 여섯 시임\n"
                "[친구A] [오후 5:22] ㅇㅋ 시간 확인함~\n")
        examples = parse_export(text, "친구A")
        self.assertEqual(len(examples), 2)
        self.assertEqual(examples[0]["context"], "저녁 곱창 회식일정 추가해줘")
        self.assertEqual(examples[0]["reply"], "그건 좀 웃김~ 몇 시인지 알려줘")
        self.assertIn("ㅇㅋ 시간 확인함~", style_context("내일 일정 등록해줘", {"examples": examples}))

    def test_import_redacts_contacts_and_encrypts_local_copy(self):
        text = ("2026년 10월 28일 오후 5:20, 나 : 전화번호 010-1234-5678 알려줘\n"
                "2026년 10월 28일 오후 5:21, 친구 : https://example.com 보면 됨~\n")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "chat.txt"
            source.write_text(text, encoding="utf-8-sig")
            examples = parse_export(decode_export(source), "친구")
            self.assertIn("<연락처>", examples[0]["context"])
            self.assertIn("<링크>", examples[0]["reply"])
            stored = Path(directory) / "examples.dpapi"
            save_examples(stored, "친구", examples)
            self.assertNotIn(b"example.com", stored.read_bytes())
            self.assertEqual(load_examples(stored)["examples"], examples)

    def test_selection_prefers_related_exchange(self):
        examples = [{"context": "점심 뭐 먹지", "reply": "국밥 먹으셈~"},
                    {"context": "오늘 회식 몇 시임", "reply": "곱창은 여섯 시임~"},
                    {"context": "영화 볼래", "reply": "그건 좀 에바임~"}]
        self.assertEqual(select_examples("회식 몇 시야", examples)[0], examples[1])


if __name__ == "__main__":
    unittest.main()
