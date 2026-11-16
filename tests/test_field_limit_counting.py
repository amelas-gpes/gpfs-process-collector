"""The browser and the server apply the same limits to the reply, the goal and the background,
and count them the same way: in characters (code points), not in UTF-16 units.

web/app.js keeps an over-long field whole and refuses to send it (tests/test_field_limits.cjs).
This file holds the other side: what the page lets through, the server accepts, and one character
more is refused by both.
"""
import re
import unittest
from pathlib import Path

from test_server import server

APP = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")
RARE = "\U00020BB7"  # one CJK character outside the basic plane: two UTF-16 units in a browser


def page_limit(field_id):
    found = re.search(r'\{id:"%s",limit:(\d+),' % re.escape(field_id), APP)
    if not found:
        raise AssertionError(f"web/app.js declares no limit for #{field_id}")
    return int(found.group(1))


def payload(objective="Understand the work", background="", answer="We log the request."):
    return {"context": {"process_name": "Supply order", "process_owner": "", "objective": objective,
                        "background": background},
            "turns": [{"id": "t001", "role": "assistant", "text": "What starts the work?"},
                      {"id": "t002", "role": "user", "text": answer}]}


class FieldLimitCountingTests(unittest.TestCase):
    def test_the_page_counts_code_points_before_it_refuses_a_field(self):
        self.assertIn("const charCount = value => {let count = 0; for (const _ of value) count++; return count;};", APP)
        self.assertIn("const exceeds = (value, limit) => value.length > limit && charCount(value) > limit;", APP)
        self.assertIn("exceeds(value, field.limit)", APP)

    def test_a_reply_at_the_page_limit_is_accepted_and_one_more_character_is_not(self):
        limit = page_limit("answer-text")
        self.assertEqual(limit, 6000)
        for unit in ("a", RARE):
            with self.subTest(unit=ascii(unit)):
                server.validate_payload(payload(answer=unit * limit))
                with self.assertRaisesRegex(ValueError, "Turn text must be text of at most 6000 characters"):
                    server.validate_payload(payload(answer=unit * (limit + 1)))

    def test_goal_and_background_at_the_page_limit_are_accepted_and_one_more_character_is_not(self):
        for field_id, key in (("objective", "objective"), ("background", "background")):
            limit = page_limit(field_id)
            for unit in ("a", RARE):
                with self.subTest(field=key, unit=ascii(unit)):
                    server.validate_payload(payload(**{key: unit * limit}))
                    with self.assertRaisesRegex(ValueError, f"{key} must be text of at most {limit} characters"):
                        server.validate_payload(payload(**{key: unit * (limit + 1)}))


if __name__ == "__main__":
    unittest.main()
