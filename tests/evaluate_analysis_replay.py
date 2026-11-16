"""Score the fictional registrar replay offline, or exercise selected production analysis stages."""
import argparse
import json
from pathlib import Path
import re
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import server
from evaluate_capture_attribution import validate_attribution

DATA = HERE / "fixtures" / "registrar-replay.json"
GROUPS = ("map", "draft", "coverage", "process_review", "document", "matcher")


def graph_scores(steps, routes):
    expected = {"prepare", "sign", "file"}
    signatures = {}
    for step in steps:
        title = step.get("title", "").casefold()
        owner = step.get("actor", "").casefold()
        for action, role, verb in (("prepare", "registrar", r"prepar|creat"),
                                   ("sign", "instructor", r"\bsign(?:s|ing)?\b"),
                                   ("file", "registrar", r"\bfil(?:e|es|ing)\b|archiv|stor")):
            if role in owner and re.search(verb, title):
                signatures[step["id"]] = action
                break
    reported = set(signatures.values())
    edges = {(signatures.get(row["from"]), signatures.get(row["to"])) for row in routes}
    expected_edges = {("prepare", "sign"), ("sign", "file")}
    supported = len(edges & expected_edges)
    return {"operation_recall": len(reported & expected) / len(expected),
            "operation_precision": len(signatures) / max(1, len(steps)),
            "route_precision": supported / max(1, len(edges)),
            "route_recall": supported / len(expected_edges)}


def score_replay(data):
    findings = {row["topic"]: row["text"] for row in data["facts"]}
    validate_attribution(findings)
    sources = {row["id"]: row["text"] for row in data["turns"]}
    excerpts = [(p["quote"], sources[p["source_id"]]) for row in data["facts"] for p in row["support"]
                if p["source_id"] in sources]
    def normalize(text):
        return " ".join(text.casefold().split())
    variation = findings["variations"].casefold()
    return {**graph_scores(data["steps"], data["routes"]),
            "participant_quote_precision": sum(normalize(q) in normalize(s) for q, s in excerpts) / max(1, len(excerpts)),
            "past_and_proposed_kept_distinct": "used to" in variation and "future" in variation}


def run_group(group, client, data):
    context, turns = data["context"], data["turns"]
    payload = {"context": context, "turns": turns, "action": "answer"}
    if group in ("map", "draft"):
        result = (client.coordinator.workflow({**payload, "_map_only": True}) if group == "map"
                  else client.draft(payload))
        artifact = result["workflow" if group == "map" else "draft"]
        return graph_scores(artifact["steps"], artifact["connections"])
    if group in ("process_review", "coverage"):
        from test_interview_coverage import fixture
        findings, _, transcript = fixture()
        # Give the reviewer a deliberate, material contradiction with its cited source.
        for item in findings:
            if item["key"] == "accountable":
                item["answer"] = "The external courier is solely accountable for Treasury acceptance."
                break
        if group == "coverage":
            _, reviewed = client.assess_coverage(findings, {}, transcript, {}, force=True,
                model_override=client.agent_models["coverage_reviewer"], topics=["accountable"])
            return {"contradictory_owner_flagged": bool(reviewed.get("review_available", True)
                    and reviewed.get("topics") and not reviewed["topics"][0]["complete"])}
        _, run = client.coordinator._new_run({}, {}, transcript, [], roles=("process_reviewer",))
        review = client.coordinator._process(run, {"memo_findings": findings}, {}, transcript, {})
        return {"contradictory_owner_flagged": not review["no_material_blockers"] and any(
            row["material"] and "u_accountable" in row["evidence_turns"] for row in review["findings"])}
    if group == "document":
        with tempfile.TemporaryDirectory() as directory:
            store = server.documents.DocumentStore(Path(directory))
            scope = store.create_scope()
            row = store.add(scope, "Fictional-register.csv", data["document_source"].encode())
            row = store.extract(scope, row["id"])
            chunks = store.chunks(scope, row["id"])["chunks"]
            result = client.analyze_document(context, {**row, "_scope": scope}, chunks, "quick", store)
            refs = {chunk["id"] for chunk in chunks}
            observations = result["observations"]
            account = " ".join(item["text"] for item in observations).casefold()
            return {"source_references_valid": bool(observations) and all(
                    item["sources"] and set(item["sources"]) <= refs for item in observations),
                    "roles_and_artifacts_observed": all(word in account for word in ("registrar", "instructor", "waiver", "schedule"))}
    # Two entirely unrelated interviews are a negative control for proposed handoffs.
    def account(number, title, evidence):
        return {"submission_id": f"s{number}", "process_id": f"p{number}", "revision": 1,
                "scope": "Fictional museum", "context": {"process_name": title}, "turns": evidence}
    matcher = server.local_module("knowledge_ai", "knowledge_ai.py").build_analyzer(client)
    unrelated = [{"id": "m1", "role": "user", "text": "I water the orchard trees when the soil is dry."}]
    proposals = matcher(account(1, "Waiver filing", turns), [account(2, "Orchard watering", unrelated)])
    return {"unrelated_processes_left_unlinked": proposals == []}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay", type=Path, default=DATA)
    parser.add_argument("--live", action="store_true", help="Make provider calls for the selected groups.")
    parser.add_argument("--groups", nargs="+", choices=GROUPS)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.live != bool(args.groups):
        parser.error("Select --live and --groups together, or omit both for offline replay.")
    data = json.loads(args.replay.read_text(encoding="utf8"))
    receipt = {"app_version": server.VERSION, "offline_replay": score_replay(data), "groups": {}}
    if args.live:
        client = server.OpenAIClient(server.load_settings())
        for group in dict.fromkeys(args.groups):
            stages = []
            def completed(event, **values):
                if event == "provider_request_finished" and values.get("prompt_id"):
                    stages.append({key: values.get(key) for key in ("stage", "model", "prompt_id", "reasoning_effort")})
            client.diagnostic_callback = completed
            try:
                receipt["groups"][group] = {"scores": run_group(group, client, data), "requests": stages}
            except Exception as error:
                receipt["groups"][group] = {"error": type(error).__name__, "requests": stages}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2), encoding="utf8")
    passing = all(value == 1 for value in receipt["offline_replay"].values())
    for row in receipt["groups"].values():
        passing = passing and "scores" in row and all(value == 1 for value in row["scores"].values())
    return 0 if passing else 1


if __name__ == "__main__":
    sys.exit(main())
