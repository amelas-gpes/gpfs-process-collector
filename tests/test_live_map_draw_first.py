"""In Live voice the map is returned as drawn, and its source check is a second request.

Measured with the real provider on 2026-11-23 (thirteen spoken answers, no files): the page asked
for a drawn and checked map in one request, 51 to 279 s each, and showed nothing until the check
returned, so the map covered answers 1 to 5 when the interview stopped. The draw alone took 12 to
62 s. The page now shows the drawn map and asks for the check with the token the draw returned.

Offline. The scripted team of test_background_continuity plays the models through the real
Coordinator. No provider or network is used.
"""
import copy
import unittest

from test_background_continuity import ScriptedTeam, account
from test_server import server


def live(*answers):
    return {**account(*answers), "live_map": True}


class LiveMapDrawFirst(unittest.TestCase):
    def setUp(self):
        self.client = ScriptedTeam()
        self.coordinator = self.client.coordinator

    def names(self):
        return [call["name"] for call in self.client.calls]

    def test_the_draw_returns_before_any_source_check_and_the_check_follows_on_request(self):
        payload = live("u1", "u2")
        drawn = self.coordinator.workflow_live_draw(copy.deepcopy(payload))
        self.assertEqual(self.names(), ["team_working_process_map"], "Only the map model is asked before the map is shown")
        self.assertRegex(drawn["check_token"], r"^[0-9a-f]{32}$")
        self.assertTrue(drawn["workflow"]["steps"])
        checked = self.coordinator.workflow_live_check({**copy.deepcopy(payload), "check_token": drawn["check_token"]})
        self.assertEqual(self.names(), ["team_working_process_map", "team_working_map_source_audit"])
        self.assertNotIn("check_token", checked)
        self.assertEqual([step["id"] for step in checked["workflow"]["steps"]], [step["id"] for step in drawn["workflow"]["steps"]])
        self.assertIn("route_assurance", checked, "The checked map carries its route review like any other")

    def test_a_token_checks_one_map_once_and_only_for_the_account_it_was_drawn_from(self):
        payload = live("u1", "u2")
        token = self.coordinator.workflow_live_draw(copy.deepcopy(payload))["check_token"]
        with self.assertRaises(server.APIError) as other:
            self.coordinator.workflow_live_check({**live("u1", "u2", "u3"), "check_token": token})
        self.assertEqual(other.exception.status, 409)
        with self.assertRaises(server.APIError) as spent:
            self.coordinator.workflow_live_check({**copy.deepcopy(payload), "check_token": token})
        self.assertEqual(spent.exception.status, 409, "A refused check gives the token up as well")
        for value in ("0" * 32, None, 7, {"check_token": token}):
            with self.assertRaises(server.APIError):
                self.coordinator.workflow_live_check({**copy.deepcopy(payload), "check_token": value})
        self.assertEqual(self.names(), ["team_working_process_map"], "No refused check reaches a model")

    def test_a_request_that_is_not_a_live_map_is_drawn_and_checked_in_one_piece(self):
        result = self.coordinator.workflow_live_draw(account("u1", "u2"))
        self.assertNotIn("check_token", result)
        self.assertEqual(self.names(), ["team_working_process_map", "team_working_map_source_audit"])

    def test_drawn_maps_are_not_kept_without_limit(self):
        import interview_orchestrator
        tokens = [self.coordinator.workflow_live_draw(live("u1"))["check_token"]
                  for _ in range(interview_orchestrator.LIVE_DRAWS_KEPT + 2)]
        self.assertEqual(len(self.coordinator._live_draws), interview_orchestrator.LIVE_DRAWS_KEPT)
        self.assertNotIn(tokens[0], self.coordinator._live_draws)
        self.assertIn(tokens[-1], self.coordinator._live_draws)

    def test_the_page_is_told_that_it_may_ask_this_way(self):
        self.assertIs(self.client.public_config()["agent_team"]["live_map_draw_first"], True)


if __name__ == "__main__":
    unittest.main()
