"""Explicit test-only adapter for historical full-capture provider fixtures.

Production accepts only typed fact transactions. Existing tests focused on other
contracts can express their intended mock capture through this adapter; ledger
behavior itself is tested with hand-authored operations, not this conversion.
"""
import copy
import re
import capture_facts

from interview_coverage import finding_reports_unavailable_knowledge


def fixture_reconciliations(prior, operations):
    """Explicit mock dispositions; never used by production/provider fallbacks."""
    rows = []
    for fact in capture_facts.reconciliation_targets(prior):
        operation = next((item for item in operations if item["target_id"] == fact["id"]), None)
        row = {"target_id": fact["id"], "disposition": operation["op"] if operation else "unchanged",
               "basis": "The controlled fixture explicitly retains or revises this exact assertion."}
        if not operation:
            row["evidence_turns"] = copy.deepcopy(fact["evidence_turns"])
        rows.append(row)
    return rows


def as_fact_delta(capture, model_input):
    prior = model_input["fact_state"]
    operations, states = [], []
    for finding in capture["memo_findings"]:
        key = finding["key"]
        unavailable = finding_reports_unavailable_knowledge(finding, model_input["turns"])
        kind = "gap" if unavailable else "not_applicable" if finding["status"] == "not_applicable" else "detail"
        desired = [] if finding["status"] == "unknown" else re.split(r"(?<=[.!?])\s+(?=[A-Z])|\n+", finding["answer"].strip())
        existing = [fact for fact in prior["facts"] if fact["topic"] == key]
        keep = set()
        for text in desired:
            match = next((fact for fact in existing if fact["text"] == text and fact["kind"] == kind
                          and fact["evidence_turns"] == finding["evidence_turns"]), None)
            if match:
                keep.add(match["id"])
            else:
                operations.append({"op": "add", "topic": key, "target_id": "", "kind": kind,
                                   "text": text, "evidence_turns": copy.deepcopy(finding["evidence_turns"]),
                                   "reason": "new_evidence"})
        for fact in existing:
            if fact["id"] not in keep:
                operations.append({"op": "remove", "topic": key, "target_id": fact["id"], "kind": fact["kind"],
                    "text": "The controlled test fixture explicitly replaces this prior assertion.",
                    "evidence_turns": copy.deepcopy(finding["evidence_turns"] or fact["evidence_turns"]),
                    "reason": "capture_correction"})
        states.append({"key": key, "status": finding["status"], "participant_unavailable": unavailable})
    return {key: copy.deepcopy(capture[key]) for key in ("question", "summary", "focus", "parking_lot")} | {
        "base_revision": prior["base_revision"], "fact_reconciliations": fixture_reconciliations(prior, operations),
        "topic_states": states, "fact_operations": operations}
