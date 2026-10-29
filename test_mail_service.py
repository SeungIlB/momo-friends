"""Mail credentials stay local and sending uses only reviewed inputs."""

import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from mail_service import load_private, save_private, send_gmail, send_mailplug, validate_recipients
from mail_ui import MailMixin


class MailServiceTest(unittest.TestCase):
    def test_account_password_is_encrypted_and_recipients_are_validated(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "mail.dpapi"
            save_private(path, {"address": "me@example.com", "app_password": "private-password"})
            self.assertEqual(load_private(path)["app_password"], "private-password")
            self.assertNotIn(b"private-password", path.read_bytes())
        self.assertEqual(validate_recipients("a@example.com, b@example.com"),
                         ["a@example.com", "b@example.com"])
        with self.assertRaises(ValueError):
            validate_recipients("a@example.com\nBcc: victim@example.com")

    def test_mailplug_sends_through_authenticated_smtp(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "mail.dpapi"
            save_private(path, {"address": "me@example.com", "app_password": "app-password"})
            server = MagicMock()
            server.__enter__.return_value = server
            with patch("mail_service.smtplib.SMTP_SSL", return_value=server):
                send_mailplug(path, "friend@example.com", "제목", "본문")
            server.login.assert_called_once_with("me@example.com", "app-password")
            message = server.send_message.call_args.args[0]
            self.assertEqual(message["To"], "friend@example.com")
            self.assertEqual(message["Subject"], "제목")

    def test_gmail_sends_encoded_message_with_oauth_token(self):
        credentials = Mock(token="oauth-token")
        response = Mock()
        response.json.return_value = {"id": "sent-message"}
        with patch("mail_service._gmail_credentials", return_value=(credentials, "me@example.com")), \
             patch("mail_service.requests.post", return_value=response) as post:
            send_gmail(Path("unused"), "friend@example.com", "제목", "본문")
        self.assertIn(b"friend@example.com", base64.urlsafe_b64decode(post.call_args.kwargs["json"]["raw"]))
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer oauth-token")

    def test_inbox_detection_does_not_intercept_send_request(self):
        self.assertTrue(MailMixin.is_mail_inbox_request("최근 메일 확인해줘"))
        self.assertFalse(MailMixin.is_mail_inbox_request("메일 보내고 확인해줘"))


if __name__ == "__main__":
    unittest.main()
