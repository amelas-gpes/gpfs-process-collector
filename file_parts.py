"""The first notes from a file, read in parallel parts that together cover the whole file.

A notes request reads at most 60,000 characters (document_service.MAX_SUPPORT_CHARS) and its time is
the time the model takes to write its reply: on an 84-page procedure the single request read 48 of
the 84 pages and took 52 to 55 seconds. Here the file is split into consecutive parts of about 7,000
characters; each part is read by its own request at the same moment, and records the facts its
sections state within a share of one account's fact budget. One further request reads the opening of
each file and writes the fields that describe the whole account (topic states, summary, focus, tags,
connections). The replies are joined into the one fact transaction the ledger has always checked,
so nothing is accepted that the ledger would refuse from a single reply.

A part's reply is lean: a fact names its passage by section and line numbers instead of copying it,
and the passage is cut from the section's own text here, so every quotation is exact by construction.

Measured on the audit files (2026-11-19): 84 pages, 17 requests back in 6.7 s against 52 s, every page
read, 71 facts accepted with none flagged; 44 pages, 5.7 s against 41.5 s.

This module only plans the requests and joins the replies; interview_orchestrator sends them.
"""
from __future__ import annotations

import copy
import difflib
import re

# Characters of file text in one part, and at most this many parts in one reading.
PART_CHARS = 7000
MAX_PARTS = 24
# The account the parts write together: about 0.7 facts per 1,000 characters of the file, at most 80.
FACT_DENSITY = 0.7
MAX_FACTS = 80
# The opening the whole-account request reads, per file.
OPENING_CHARS = 12000
# A file larger than this is read the way it always was (one request over the selected excerpts).
MAX_FILE_CHARS = 400000
# A reading is worth splitting only when the files are larger than this.
MIN_SPLIT_CHARS = 9000
# The topic sweep reads files up to this size whole, and the opening of larger ones (see sweep_request).
SWEEP_MAX_CHARS = 160000
# Lines one cited passage may span.
MAX_QUOTE_LINES = 8
PART_TIMEOUT_SECONDS = 60

PART_INSTRUCTIONS = """

PARALLEL READING ASSIGNMENT
This file is being read by several requests at the same moment, each given one consecutive part of it.
This request has part {number} of {count}: {first} to {last}. Record the material facts that these sections
support, each under the one topic where it belongs most. Do not write a fact that these sections do not
state, and do not summarise parts you were not given: a table of contents or an overview that only lists
later sections is not itself evidence of their content.
FACT BUDGET: the whole file is recorded at the level of detail of one account of about {total} facts, and
this part's share is {budget}. Record at most {budget} facts: the ones a reader of the procedure could least
do without. Join closely related details of one step, check or rule into one fact rather than one fact per
sentence. When these sections state the process's name, purpose, scope, trigger, completion, owner or
volume, that is one of the facts to keep.
BREADTH FIRST: before a second fact goes to any topic, give one fact to every topic these sections speak
to, however briefly they speak to it: name, purpose, trigger, completion, accountable (who owns, performs,
reviews, approves), lifecycle (the steps), checks, variations, pain_points, risk, materials (records,
templates, files), scope (what is in and out), rules, connections (other processes it feeds or depends
on), data_systems and volume (how often, how many, how long the work takes). Only then use what is left of
the budget on further steps, checks and rules.
RARE STATEMENTS: a procedure seldom states its problems and exposures, so each such statement in these
sections is recorded even when the budget is spent: a known problem, weakness, single point of failure,
manual workaround or delay (pain_points); what could go wrong and what it would cost (risk); how often,
how many or how long (volume); another process this one feeds or depends on (connections).

REPLY FORMAT
Each section's text is shown with a line number before every line ("12| text"); the numbers are not part of
the text. A fact names its supporting passage in support as the section's source_id with first_line and
last_line (at most 8 lines: the lines that state the fact). Do not copy the passage: the application cuts it
from the section itself. Every fact here is a new fact from this file, so no operation, target or reason is
written. Write facts only; the topic states and the account's summary are written by another request."""

SWEEP_INSTRUCTIONS = """

PARALLEL READING ASSIGNMENT: TOPIC SWEEP
The detailed facts of these files are being recorded at this moment by other requests that read them part
by part, each within a small budget, so a topic that the files mention only briefly can be passed over.
This request reads the whole of the files and records, for each of the sixteen topics, the ONE statement
that tells most about it, when the files make one: name, purpose, trigger, completion, accountable,
lifecycle, checks, variations, pain_points, risk, materials, scope, rules, connections, data_systems and
volume. At most one fact per topic; write nothing for a topic the files do not speak to. A table of contents
that only names a section is not a statement about its topic.

REPLY FORMAT
Each section's text is shown with a line number before every line ("12| text"); the numbers are not part of
the text. A fact names its supporting passage in support as the section's source_id with first_line and
last_line (at most 8 lines). Do not copy the passage: the application cuts it from the section itself."""
# What the sweep adds when a file it reads was read only up to a limit (context_coverage.read_limit).
SWEEP_CUT_NOTE = """
A file whose context_coverage has a read_limit was read only up to that limit: its sections here end there.
Record nothing about the part of it that was not read."""
# The selection named for such a file when all of its indexed text is supplied.
CUT_SELECTION = "all indexed text (file read up to a limit)"

WHOLE_INSTRUCTIONS = """

PARALLEL READING ASSIGNMENT
The facts of these files are being recorded at this moment by other requests that read them part by part,
and the account's remaining fields by one more request. This request writes ONLY {fields}, from the
opening sections supplied here, for the account as a whole. Write no facts.{states}"""
STATES_NOTE = (" For topic_states, judge each topic by what the files as a whole evidently cover, using the opening,"
               " any contents or overview it gives and the file review summaries supplied.")

# The fields that describe the whole account, written by two requests side by side: one long reply
# would hold the notes back (measured 7.8 s for 1,214 tokens while the parts took 3 to 5.5 s).
WHOLE_GROUPS = (("topic_states", "summary", "focus", "parking_lot"),
                ("tag_operations", "connections_out", "active_modules", "recap_due"))
WHOLE_FIELDS = WHOLE_GROUPS[0] + WHOLE_GROUPS[1]


def _plain(text):
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def eligible(supporting):
    """The files of this request that are read whole: active, with indexed text, not saved-only."""
    rows = []
    for document in (supporting or {}).get("documents", []):
        if document.get("retained_only") or document.get("disposition") == "parked":
            continue
        if isinstance(document.get("id"), str) and re.fullmatch(r"doc_[0-9a-f]{24}", document["id"]):
            rows.append(document)
    return rows


def plan(supporting, sections_by_document):
    """The parts to read and the whole-file supporting context, or None to read the usual way.

    sections_by_document maps a file id to its sections in file order ({id, label, text, location}),
    as the document store gives them to this interview.
    """
    documents = eligible(supporting)
    if not documents:
        return None
    files = []
    for document in documents:
        sections = [section for section in sections_by_document.get(document["id"]) or []
                    if isinstance(section.get("text"), str) and section["text"].strip()
                    and not section.get("requires_vision") and not (section.get("location") or {}).get("requires_vision")]
        if not sections:
            return None
        files.append((document, sections))
    total = sum(len(section["text"]) for _, sections in files for section in sections)
    if total < MIN_SPLIT_CHARS or total > MAX_FILE_CHARS:
        return None
    size = max(PART_CHARS, -(-total // MAX_PARTS))
    parts = []
    for document, sections in files:
        current, length = [], 0
        for section in sections:
            if current and length + len(section["text"]) > size:
                parts.append((document, current))
                current, length = [], 0
            current.append(section)
            length += len(section["text"])
        if current:
            parts.append((document, current))
    facts = max(len(parts), min(MAX_FACTS, round(FACT_DENSITY * total / 1000)))
    whole = copy.deepcopy(supporting)
    whole_documents = {document["id"]: document for document in whole.get("documents", [])}
    for document, sections in files:
        target = whole_documents[document["id"]]
        target["excerpts"] = [_excerpt(document, section) for section in sections]
        # A file read only up to a page, row, sheet or cell limit (context_coverage.read_limit): all of
        # its index is supplied, and that is not the whole file.
        cut = bool((target.get("context_coverage") or {}).get("read_limit"))
        target["context_coverage"] = {**(target.get("context_coverage") or {}), "included_chunks": len(sections),
                                      "complete_text": not cut, "selection": CUT_SELECTION if cut else "whole file",
                                      "all_indexed_sections_supplied": True, "text_sections_supplied": len(sections)}
    lines = {section["id"]: section["text"].split("\n") for _, sections in files for section in sections}
    return {"supporting": whole, "files": files, "parts": parts, "total_chars": total, "total_facts": facts, "lines": lines}


def _excerpt(document, section, text=None):
    location = section.get("location") or {}
    return {"id": section["id"], "source_id": section["id"], "document_id": document["id"], "name": document.get("name", ""),
            "label": section.get("label", ""), "text": section["text"] if text is None else text, "location": location,
            **{key: location[key] for key in ("page", "sheet", "row_start", "row_end") if key in location}}


def _numbered(text):
    return "\n".join(f"{number}| {line}" for number, line in enumerate(text.split("\n"), 1))


def _restricted(supporting, document, excerpts):
    """A copy of the request's files holding only this part's sections of one file."""
    value = copy.deepcopy(supporting)
    ids = {excerpt["id"] for excerpt in excerpts}
    kept = []
    for row in value.get("documents", []):
        if row.get("id") != document["id"]:
            continue
        row["excerpts"] = excerpts
        for name in ("observations", "questions"):
            row[name] = [item for item in row.get(name, []) if isinstance(item, dict)
                         and all(source.get("source_id") in ids for source in item.get("sources", []) if isinstance(source, dict))]
        row["context_coverage"] = {**(row.get("context_coverage") or {}), "included_chunks": len(excerpts),
                                   "complete_text": False, "selection": "one part of the file",
                                   "all_indexed_sections_supplied": False, "text_sections_supplied": len(excerpts)}
        kept.append(row)
    value["documents"] = kept
    value["retained_evidence"] = []
    budget = value.get("context_budget")
    if isinstance(budget, dict):
        budget.update(characters=sum(len(excerpt["text"]) for excerpt in excerpts), chunks=len(excerpts))
    return value


def part_requests(reading, base_payload):
    """(payload, instructions suffix, schema, budget) for each part, in file order."""
    requests = []
    count, total = len(reading["parts"]), reading["total_chars"]
    for number, (document, sections) in enumerate(reading["parts"], 1):
        excerpts = [_excerpt(document, section, _numbered(section["text"])) for section in sections]
        payload = {**copy.deepcopy(base_payload), "supporting_documents": _restricted(reading["supporting"], document, excerpts)}
        size = sum(len(section["text"]) for section in sections)
        # One fact more than the part's share, for a topic that only this part speaks to.
        budget = max(1, round(reading["total_facts"] * size / total)) + 1
        label = lambda section: str(section.get("label", section["id"])).split(" · ")[-1]
        suffix = PART_INSTRUCTIONS.format(number=number, count=count, first=label(sections[0]), last=label(sections[-1]),
                                          total=reading["total_facts"], budget=budget)
        requests.append((payload, suffix, part_schema([section["id"] for section in sections], budget), budget))
    return requests


def part_schema(ids, budget):
    from capture_facts import TOPICS, MAX_FACT_TEXT  # noqa: PLC0415 - loaded beside this module
    support = {"type": "object", "additionalProperties": False, "required": ["source_id", "first_line", "last_line"],
               "properties": {"source_id": {"type": "string", "enum": list(ids)},
                              "first_line": {"type": "integer"}, "last_line": {"type": "integer"}}}
    fact = {"type": "object", "additionalProperties": False, "required": ["topic", "kind", "text", "support"],
            "properties": {"topic": {"type": "string", "enum": list(TOPICS)},
                           "kind": {"type": "string", "enum": ["detail", "gap", "not_applicable"]},
                           "text": {"type": "string", "minLength": 1, "maxLength": MAX_FACT_TEXT},
                           "support": {"type": "array", "minItems": 1, "maxItems": 3, "items": support}}}
    return {"type": "object", "additionalProperties": False, "required": ["fact_operations"],
            "properties": {"fact_operations": {"type": "array", "maxItems": max(2, 2 * budget), "items": fact}}}


def sweep_request(reading, base_payload):
    """(payload, instructions suffix, schema) of the topic sweep.

    It reads the whole files, or in files larger than SWEEP_MAX_CHARS their opening up to that size
    (shared between the files): what describes the whole account (name, purpose, trigger, scope) is
    stated early, as in a workbook's instructions tab.
    """
    share = SWEEP_MAX_CHARS // max(1, len(reading["files"]))
    chosen = {}
    for _, sections in reading["files"]:
        size = 0
        for section in sections:
            if size and size + len(section["text"]) > share:
                break
            chosen[section["id"]] = _numbered(section["text"])
            size += len(section["text"])
    value = copy.deepcopy(reading["supporting"])
    for row in value.get("documents", []):
        before = len(row.get("excerpts", []))
        row["excerpts"] = [{**excerpt, "text": chosen[excerpt["id"]]} for excerpt in row.get("excerpts", []) if excerpt["id"] in chosen]
        if len(row["excerpts"]) < before:
            row["context_coverage"] = {**(row.get("context_coverage") or {}), "complete_text": False,
                                       "selection": "opening of the file", "all_indexed_sections_supplied": False,
                                       "text_sections_supplied": len(row["excerpts"])}
    value["retained_evidence"] = []
    ids = list(chosen)
    schema = part_schema(ids, 8)
    schema["properties"]["fact_operations"]["maxItems"] = 16
    cut = any((row.get("context_coverage") or {}).get("read_limit") for row in value.get("documents", []))
    return ({**copy.deepcopy(base_payload), "supporting_documents": value},
            SWEEP_INSTRUCTIONS + (SWEEP_CUT_NOTE if cut else ""), schema)


def part_output_tokens(budget):
    """Room for the budgeted facts and a little more; a reply that runs on is cut off and asked again."""
    return min(6000, 600 + 220 * budget)


def whole_requests(reading, base_payload, request_schema):
    """(payload, instructions suffix, schema) of each request for the account-wide fields."""
    value = copy.deepcopy(reading["supporting"])
    for row in value.get("documents", []):
        opening, size = [], 0
        for excerpt in row.get("excerpts", []):
            if opening and size + len(excerpt["text"]) > OPENING_CHARS:
                break
            opening.append(excerpt)
            size += len(excerpt["text"])
        ids = {excerpt["id"] for excerpt in opening}
        row["excerpts"] = opening
        for name in ("observations", "questions"):
            row[name] = [item for item in row.get(name, []) if isinstance(item, dict)
                         and all(source.get("source_id") in ids for source in item.get("sources", []) if isinstance(source, dict))]
        row["context_coverage"] = {**(row.get("context_coverage") or {}), "included_chunks": len(opening),
                                   "complete_text": False, "selection": "opening of the file",
                                   "all_indexed_sections_supplied": False, "text_sections_supplied": len(opening)}
    value["retained_evidence"] = []
    requests = []
    for fields in WHOLE_GROUPS:
        schema = copy.deepcopy(request_schema)
        schema["properties"] = {key: schema["properties"][key] for key in fields}
        schema["required"] = list(fields)
        suffix = WHOLE_INSTRUCTIONS.format(fields=", ".join(fields[:-1]) + " and " + fields[-1],
                                           states=STATES_NOTE if "topic_states" in fields else "")
        requests.append(({**copy.deepcopy(base_payload), "supporting_documents": value}, suffix, schema))
    return requests


def _cut(lines, first, last):
    if not lines or type(first) is not int or type(last) is not int or first < 1 or first > len(lines):
        return ""
    end = min(len(lines), max(first, last), first + MAX_QUOTE_LINES - 1)
    return "\n".join(lines[first - 1:end]).strip()


def uncovered(part_replies, whole_replies):
    """Topics the account-wide reply judges covered for which no part recorded a fact."""
    covered = {row.get("topic") for reply in part_replies for row in (reply or {}).get("fact_operations", [])
               if isinstance(row, dict)}
    judged = {row.get("key") for reply in whole_replies for row in (reply or {}).get("topic_states", [])
              if isinstance(row, dict) and row.get("status") in ("partial", "captured", "not_applicable")}
    return sorted(judged - covered)


def join(reading, base_revision, part_replies, whole_replies, sweep_reply=None):
    """One fact transaction from the parts' facts and the account-wide replies.

    The topic sweep's fact for a topic is used only when no part recorded one for that topic.
    """
    lines = reading["lines"]
    covered = {row.get("topic") for reply in part_replies for row in (reply or {}).get("fact_operations", [])
               if isinstance(row, dict)}
    sweep = [row for row in (sweep_reply or {}).get("fact_operations", [])
             if isinstance(row, dict) and row.get("topic") not in covered]
    operations = []
    for reply in [*part_replies, {"fact_operations": sweep}]:
        for row in (reply or {}).get("fact_operations", []):
            if not isinstance(row, dict) or not isinstance(row.get("text"), str) or not row["text"].strip():
                continue
            support = []
            for cited in row.get("support", []):
                if not isinstance(cited, dict):
                    continue
                quote = _cut(lines.get(cited.get("source_id")), cited.get("first_line"), cited.get("last_line"))
                if quote and all(item["source_id"] != cited["source_id"] or item["quote"] != quote for item in support):
                    support.append({"source_id": cited["source_id"], "quote": quote})
            if not support:
                continue  # A fact whose passage cannot be found has nothing to stand on.
            operations.append({"op": "add", "topic": row["topic"], "target_id": "", "kind": row["kind"],
                               "text": row["text"].strip(), "support": support,
                               "evidence_turns": list(dict.fromkeys(item["source_id"] for item in support)),
                               "reason": "new_evidence"})
    operations = _without_repeats(operations)
    whole = {}
    for reply in whole_replies:
        whole.update({key: value for key, value in (reply or {}).items() if key in WHOLE_FIELDS})
    from capture_facts import TOPICS  # noqa: PLC0415 - loaded beside this module
    held = {row["topic"] for row in operations}
    judged = {}
    for row in whole.get("topic_states", []):
        if isinstance(row, dict) and row.get("key") in TOPICS and row["key"] not in judged:
            judged[row["key"]] = row
    # The ledger takes every topic's state exactly once: one the account-wide reply left out is
    # stated from the facts alone.
    states = []
    for key in TOPICS:
        row = judged.get(key) or {"key": key, "status": "unknown", "participant_unavailable": False}
        status = row.get("status")
        if key in held and status == "unknown":
            status = "partial"
        elif key not in held and status in ("partial", "captured", "not_applicable"):
            status = "unknown"  # No part recorded a fact for it; the ledger has nothing to show for it.
        states.append({"key": key, "status": status, "participant_unavailable": bool(row.get("participant_unavailable"))})
    transaction = {"base_revision": base_revision, "fact_reconciliations": [], "topic_states": states,
                   "fact_operations": operations[:128], "remove_connections": [], "resolved_parking_lot": []}
    for key in WHOLE_FIELDS[1:]:
        transaction[key] = copy.deepcopy(whole.get(key, "" if key in ("summary", "focus") else "none" if key == "recap_due" else []))
    return transaction


def _without_repeats(operations, alike=0.92):
    """Join facts that two neighbouring parts both recorded: under the same topic, nearly the same wording.

    Only near-identical wording with the same figures is joined: step 3 and step 4 are two facts.
    """
    kept = []
    for row in operations:
        plain = _plain(row["text"])
        figures = {token for token in plain.split() if any(character.isdigit() for character in token)}
        twin = next((other for other in kept if other["topic"] == row["topic"]
                     and figures == {token for token in _plain(other["text"]).split() if any(c.isdigit() for c in token)}
                     and difflib.SequenceMatcher(None, plain, _plain(other["text"])).ratio() >= alike), None)
        if twin is None:
            kept.append(row)
            continue
        if len(row["text"]) > len(twin["text"]):
            twin["text"] = row["text"]
        for item in row["support"]:
            if item not in twin["support"] and len(twin["support"]) < 8:
                twin["support"].append(item)
        twin["evidence_turns"] = list(dict.fromkeys(item["source_id"] for item in twin["support"]))
    return kept


def describe(reading):
    """Sizes only, never text: for the trace."""
    return {"files": len(reading["files"]), "parts": len(reading["parts"]), "characters": reading["total_chars"],
            "fact_budget": reading["total_facts"]}


__all__ = ["plan", "part_requests", "whole_requests", "sweep_request", "uncovered", "join", "describe", "part_output_tokens", "eligible"]
