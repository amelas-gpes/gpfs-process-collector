"""The one-line data notice under the start buttons must not say more, or less, than the full notice.

The line is static text in web/index.html; the full notice is served by the application
(public_config()['data_notice']). Each claim of the line is checked against the sentence of the
full notice that backs it, so that a change to either is noticed.
"""
import re
import unittest
from pathlib import Path

from test_server import server

HTML = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")


class StartDataNoticeTests(unittest.TestCase):
    def setUp(self):
        found = re.search(r'<p id="data-brief"[^>]*>(.*?)</p>', HTML, re.S)
        self.assertIsNotNone(found, "web/index.html has the one-line data notice")
        self.brief = re.sub(r"<[^>]+>", "", found.group(1))
        self.notice = server.OpenAIClient({}).public_config()["data_notice"]

    def test_the_line_names_the_provider_and_what_is_sent(self):
        self.assertIn("Your voice, typed answers and files are sent to OpenAI to run the interview.", self.brief)
        # The full notice may be reworded; it must keep saying each of these in some form.
        self.assertRegex(self.notice, r"(?is)\b(text|answers?)\b.*\bsent to OpenAI")
        self.assertRegex(self.notice, r"(?is)\b(audio|voice|speech)\b.*\bOpenAI")
        self.assertRegex(self.notice, r"(?is)\bfile\b.*\bsent to OpenAI")

    def test_the_line_does_not_promise_that_nothing_is_kept(self):
        self.assertIn("The conversation is not saved automatically.", self.brief)
        self.assertRegex(self.notice, r"(?i)not saved automatically")
        # Files are stored on this computer, so the line must not claim that nothing is kept.
        self.assertRegex(self.notice, r"(?i)saved privately on this computer")
        self.assertNotRegex(self.brief, r"(?i)nothing is (kept|stored|saved)")

    def test_the_line_links_to_the_full_notice(self):
        self.assertIn("How your data is handled", self.brief)
        self.assertIn('<button type="button" id="open-data-notice"', HTML)
        disclosure = re.search(r'<details id="data-details"[^>]*>(.*?)</details>', HTML, re.S)
        self.assertIsNotNone(disclosure)
        self.assertRegex(disclosure[1], r'<summary>.*?Data handling.*?</summary>')
        self.assertIn('<p id="data-notice"', disclosure[1])


if __name__ == "__main__":
    unittest.main()
