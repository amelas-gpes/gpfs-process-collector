"""Isolated server for tests/browser/typed-map.cjs. Every provider response is synthetic; data is disposable.

The provider draws one step for each typed answer and takes a moment to draw and to check, so the
page can be watched going from "Updating the map" to "check pending" to the checked map.
Usage: python -I -B tests/browser/typed_map_server.py [DRAW_SECONDS] [CHECK_SECONDS]. Prints the URL.
"""
import json
from pathlib import Path
import sys
import tempfile
import time

tests = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(tests))
from test_background_continuity import step
from test_concurrent_http import ConversationProvider
from test_draft_audit_corrections import corrections
from test_server import fixture_route_support, server


class TypingProvider(ConversationProvider):
    draw_seconds, check_seconds = .4, 3.0

    def public_config(self):
        return {**super().public_config(), "synthetic_test": True}

    def reply(self, path, body, *args, **kwargs):
        name = body["text"]["format"]["name"] if path == "responses" else ""
        if name not in ("team_working_process_map", "team_working_map_source_audit", "process_draft", "process_draft_audit"):
            return super().reply(path, body, *args, **kwargs)
        sent = json.loads(body["input"][0]["content"])
        if name == "process_draft":
            fields = body["text"]["format"]["schema"]["properties"]
            # A full-draft request here means that the checked map did not survive the browser round trip.
            assert "drop_steps" in fields, "Create draft requested a full rewrite of the checked map"
            result = {key: [] if spec["type"] == "array" else "" for key, spec in fields.items()}
            result.update(title="Invoice handling", overview="The interview describes how invoices are handled.",
                          memo_summary=[{"key": key, "answer": "UNKNOWN", "status": "unknown", "evidence_turns": []}
                                        for key in server.COVERAGE])
        elif name == "process_draft_audit":
            result = corrections(route_support=fixture_route_support(sent["proposed_routes_to_verify"], sent["turns"]))
        elif name == "team_working_process_map":
            time.sleep(self.draw_seconds)
            previous = sent["previous_capture"]["workflow"]
            drawn = {source for item in previous["steps"] for source in item["evidence_turns"]}
            last = previous["steps"][-1]["id"] if previous["steps"] else None
            number, upserts, routes = len(previous["steps"]), [], []
            for turn in sent["turns"]:
                if turn["role"] != "user" or turn["id"] in drawn:
                    continue
                number += 1
                upserts.append(step(f"S{number}", " ".join(turn["text"].split()[:5]).rstrip(".,"), "UNKNOWN", [turn["id"]]))
                if last:
                    routes.append({"from": last, "to": f"S{number}", "label": "", "evidence_turns": [turn["id"]]})
                last = f"S{number}"
            result = {"title": "Invoice handling", "upsert_steps": upserts, "remove_steps": [], "upsert_connections": routes,
                      "remove_connections": [], "open_questions": previous["open_questions"]}
        else:
            time.sleep(self.check_seconds)
            update = sent["candidate_update"]
            spoken = {turn["id"]: turn["text"] for turn in sent["turns"] if turn["role"] == "user"}
            result = {"title": update["title"], "discard_step_upserts": [], "discard_connection_upserts": [],
                      "discard_step_removals": [], "discard_connection_removals": [], "remove_steps": [], "remove_connections": [],
                      "route_support": [{"from": edge["from"], "to": edge["to"], "label": edge["label"],
                                         "passages": [{"source_id": source, "quote": spoken[source]}
                                                      for source in edge["evidence_turns"] if source in spoken]}
                                        for edge in sent["proposed_routes_to_verify"]],
                      "upsert_steps": [], "upsert_connections": [], "open_questions": update["open_questions"]}
        return {"status": "completed", "output": [{"content": [{"type": "output_text", "text": json.dumps(result)}]}]}


if __name__ == "__main__":
    if len(sys.argv) > 1:
        TypingProvider.draw_seconds = float(sys.argv[1])
    if len(sys.argv) > 2:
        TypingProvider.check_seconds = float(sys.argv[2])
    with tempfile.TemporaryDirectory() as directory:
        client = TypingProvider()
        client.incomplete()
        root = Path(directory)
        with server.InterviewServer(("127.0.0.1", 0), server.Handler, client=client, documents_root=root / "documents",
                                    knowledge_root=root / "knowledge", knowledge_settings={}) as httpd:
            print(f"http://127.0.0.1:{httpd.server_port}/", flush=True)
            httpd.serve_forever()
