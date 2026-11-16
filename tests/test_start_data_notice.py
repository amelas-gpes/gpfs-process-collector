"""Verify that Settings still receives the service's disclosure after the welcome link is removed."""
import unittest

from test_server import server


class SettingsDataNoticeTests(unittest.TestCase):
    def test_service_disclosure_identifies_sent_content(self):
        notice = server.OpenAIClient({}).public_config()["data_notice"]
        for content in (r"\b(text|answers?)\b", r"\b(audio|voice|speech)\b", r"\bfiles?\b"):
            with self.subTest(content=content):
                self.assertRegex(notice.lower(), content)
        self.assertRegex(notice.lower(), r"\bsent to\b")

    def test_service_disclosure_explains_local_retention(self):
        notice = server.OpenAIClient({}).public_config()["data_notice"].lower()
        self.assertIn("not saved automatically", notice)
        self.assertIn("saved privately on this computer", notice)


if __name__ == "__main__":
    unittest.main()
