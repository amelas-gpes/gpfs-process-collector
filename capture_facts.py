"""Private, bounded, source-bound fact transactions for a single interview call.

The ledger prevents omission from deleting prior facts. It does not certify a
model's interpretation: independent coverage/process review still owns that job.
"""
import copy
import hashlib
import json
import re
import uuid
import gpfs_interview

from interview_coverage import TOPIC_DIMENSIONS, explicit_knowledge_gap, finding_reports_unavailable_knowledge

TOPICS = tuple(TOPIC_DIMENSIONS)
MAX_ACTIVE_FACTS = 256
MAX_FACT_RECORDS = 512
MAX_OPERATIONS = 128
MAX_FACT_TEXT = 1600


def _object(properties):
    return {"type": "object", "additionalProperties": False,
            "properties": properties, "required": list(properties)}


_TEXT = {"type": "string"}
_REFS = {"type": "array", "items": _TEXT}
_RECONCILIATION = {"anyOf": [
    _object({"target_id": _TEXT, "disposition": {"type": "string", "enum": ["unchanged"]},
             "basis": _TEXT, "evidence_turns": _REFS}),
    _object({"target_id": _TEXT, "disposition": {"type": "string", "enum": ["replace", "remove"]},
             "basis": _TEXT}),
]}
# The question comes first so a streamed response can show it while the fact
# transaction is still being written. Reasoning precedes all output tokens, so
# the order of emitted fields does not shorten the model's deliberation.
FACT_DELTA_SCHEMA = _object({
    "question": _TEXT,
    "base_revision": _TEXT,
    "fact_reconciliations": {"type": "array", "items": _RECONCILIATION},
    "topic_states": {"type": "array", "items": _object({
        "key": {"type": "string", "enum": list(TOPICS)},
        "status": {"type": "string", "enum": ["unknown", "partial", "captured", "not_applicable"]},
        "participant_unavailable": {"type": "boolean"},
    })},
    "fact_operations": {"type": "array", "items": _object({
        "op": {"type": "string", "enum": ["add", "replace", "remove"]},
        "topic": {"type": "string", "enum": list(TOPICS)},
        "target_id": _TEXT,
        "kind": {"type": "string", "enum": ["detail", "gap", "not_applicable"]},
        "text": _TEXT, "evidence_turns": _REFS,
        "reason": {"type": "string", "enum": ["new_evidence", "participant_correction", "capture_correction", "resolved_gap", "withdrawal"]},
    })},
    "summary": _TEXT, "focus": _TEXT,
    "parking_lot": {"type": "array", "items": _TEXT},
})
FACT_DELTA_SCHEMA["properties"].update({
    "tag_operations": {"type": "array", "items": gpfs_interview.TAG_OPERATION},
    "connections_out": gpfs_interview.CONNECTIONS,
    "active_modules": {"type": "array", "items": {"type": "string", "enum": ["fund", "gp_carry", "manco", "multi_entity", "calculation", "spreadsheet", "client_approval", "client_specific"]}},
    "recap_due": {"type": "string", "enum": ["none", "scope_boundary", "walkthrough"]},
})
FACT_DELTA_SCHEMA["required"] = list(FACT_DELTA_SCHEMA["properties"])

FACT_CAPTURE_POLICY = gpfs_interview.CAPTURE_POLICY + "\nControlled taxonomy vocabulary: " + json.dumps(gpfs_interview.FACETS) + "\n" + """
Return the fact-transaction schema, not the older full memo_findings response.
The application assembles memo_findings; you provide one question and fact changes.
Copy base_revision from fact_state. The private fact_state is an aid, not evidence.
First reconcile every fact ID in fact_state.reconciliation_targets against the FULL
current testimony, including facts answered earlier but never reflected in the ledger.
Those targets are the open gaps and unresolved claims the latest answer could affect.
Return exactly one fact_reconciliations row for each target. Any other listed gap
stays retained unless the testimony answers it; then resolve it with an explicit
replace/remove operation even though no reconciliation row is required for it.
unchanged requires a
specific, cited basis explaining the precise remaining unknown. Each basis is at
most 25 words and 180 characters: name the remaining gap or the change, do not
rewrite the fact, quote the transcript, or repeat source text. Do not say a broad
gap remains simply because a smaller component is still unknown. replace/remove
must have a corresponding fact_operation with the same target; its evidence_turns
are the single canonical citation list. Do not duplicate those citations in the
reconciliation row. unchanged supplies its own evidence_turns and retains the fact.
If testimony now supplies the previously missing finish condition, actor, order or
other fact, explicitly narrow or retire that old gap while preserving any genuinely
unanswered part. Adding an answer beside its obsolete 'not established' statement
does not resolve it. A flagged mixed detail must be capture-corrected to separate
its supported facts from remaining gaps; do not delete its known facts.
Every unmentioned active fact is retained. Do not rewrite unchanged facts or send
the whole section as one fact. On the first call, seed all material facts available
in the full supplied conversation and authorized document excerpts, not only the
latest answer. On later calls, add newly learned facts AND backfill material facts
previous capture missed. Distinguish supplied source content from current practice.
Each fact must cite the exact passage that establishes its actor, action and
qualifiers. Detached PDF links or table cells do not establish a process relationship
solely by their extraction order. Preserve the supported functional handoff and
leave its destination unresolved when the source binding is ambiguous.

Each detail is a self-contained material assertion or conditional route, normally
one or two sentences. Preserve the actor, action, condition, inputs compared,
result, required ordering and handoff wherever the evidence supplies them. A named
stage/check alone is insufficient when its mechanism is available. Record each
completion condition and normal branch, not just a broad closeout label. Known
working artifacts belong in materials even when their availability is unknown.
The purpose can be a firm, internal team or client result; no extra client result
is required. Charging and variation-removal questions apply only when relevant to
reported scope. Cite an explicit scope-based reason for non-applicability; never
convert unknown applicable billing, approval or removal information into N/A.

Topic assignment is not exclusive. One cited statement can establish different
facts in more than one section. Preserve a reported conditional route in lifecycle;
also add its supported variation in variations when the person describes changed
work for different equipment, systems, available inputs or circumstances. A normal
branch belongs in lifecycle, but that does not erase a separately reported reason
that the work differs. Backfill the second section even when that source was
already captured under the first. Keep each section's remaining gaps explicit;
one alternate route does not establish all variation dimensions. Distinguish the
first action from the initiating event: 'first I retrieve the bag' explains sequence,
not why or when the process begins, its cadence or deadline. Do not manufacture
trigger facts from the position of a step in the conversation.

Use add with an empty target_id for a new detail, explicit gap, or participant's
N/A basis. Use replace/remove only for an identified existing fact ID with exact
supporting evidence and an explicit correction, withdrawal, resolved-gap or capture-
correction reason. A new answer supplements earlier facts unless it changes them.
For remove, text may be empty: the exact target, reason and evidence record the
retirement. Add and replace require substantive text for the resulting fact.
Do not remove unrelated conditions or qualifiers when correcting one claim. Capture
correction fixes your earlier unsupported interpretation; prior AI text is not proof.
Use gap records for specific unresolved questions, with the relevant participant or
document evidence. A lack of knowledge is not N/A. Resolve old gap records explicitly
when evidence answers them. Do not silently erase a conflict by omitting it.
Keep known details and unresolved qualifiers in separate fact records. A detail
must not bundle a supported route with an unrelated 'not yet known' sentence.
resolved_gap applies only to an existing gap record. Correcting a detail or an old
mixed capture uses capture_correction, retaining every still-supported condition.

Return all sixteen topic_states. unknown means no usable detail or discussed gap;
a discussed but unavailable detail is partial. participant_unavailable=true requires
an explicit, topic-specific participant knowledge limit supported by the gap's cited
participant turn (a short answer can be scoped by the immediately preceding question).
Generic inability to verify the whole procedure does not prove every topic unavailable.
Document omissions alone never establish participant unavailability. Captured and N/A
are provisional proposals, never permission to end, pause or offer to stop. The
application alone acknowledges a review and authorizes final checks or partial pauses.
Choose the spoken question AFTER reconciling and updating the account. Try answering
it from the actual testimony first; reject a question that asks for an already given
answer. Check every factual premise inside the question itself, not just in your
facts. Passive testimony ('corrections are listed') does not establish that the nearest
named reviewer lists them. Ask neutrally about the listed corrections or ask who
performs the action; never presuppose an unreported performer in a 'what happens after'
question. Do not infer a new actor merely to make the question sound natural.
"""

_UNRESOLVED_QUALIFIER = re.compile(
    r"\b(?:unknown|unclear|unconfirmed|not (?:yet )?(?:fully )?(?:established|specified|described|confirmed|known))\b|"
    r"\b(?:does not|doesn't|doesn’t) (?:establish|specify|describe|identify|say|state)\b|"
    r"\b(?:cannot|can't|can’t) (?:confirm|identify|explain)\b", re.I)


_STOPWORDS = frozenset("""
about after again against although always another anyone anything around because before being
between both cannot could does doing done during each either every everything from further have
having here into its itself just like more most much must never none nothing once only other
over same several should since some such than that their them then there these they this those
through under until very were what when where whether which while whom will with within without
would your
""".split())


def turn_focus(turns):
    """The latest participant answer and the question it answered, or None before any answer."""
    for index in range(len(turns) - 1, -1, -1):
        turn = turns[index]
        if turn.get("role") == "user" and not turn.get("document_event"):
            previous = turns[index - 1] if index else None
            question = previous["text"] if previous and previous.get("role") == "assistant" else ""
            return {"answer": turn.get("text", ""), "question": question}
    return None


def _content_words(text):
    # Compare short stems so "rejection" and "rejections" count as the same word.
    return {word[:5] for word in re.findall(r"[a-z0-9]+", text.lower()) if len(word) >= 4 and word not in _STOPWORDS}


def _touched(fact, focus):
    """Could the latest answer (scoped by its question) affect this open claim?"""
    scope = focus["question"] + " " + focus["answer"]
    if re.search(r"\b(?:" + _TOPIC_WORDS[fact["topic"]] + r")", scope, re.I):
        return True
    return len(_content_words(fact["text"]) & _content_words(scope)) >= 2


def reconciliation_targets(state, focus=None):
    """Select claims for explicit inspection; this never changes their status.

    With a focus (the latest answer and its question), only open claims that answer
    could affect are selected: the reconciliation rows the model must return stay
    short and an untouched gap keeps its exact prior wording. A model-facing
    fact_state carries the already selected IDs so fixtures stay consistent.
    """
    if "reconciliation_targets" in state:
        chosen = set(state["reconciliation_targets"])
        return [fact for fact in state["facts"] if fact["id"] in chosen]
    targets = [fact for fact in state["facts"] if fact.get("state", "active") == "active"
               and (fact["kind"] == "gap" or _UNRESOLVED_QUALIFIER.search(fact["text"]))]
    if focus is None:
        return targets
    return [fact for fact in targets if _touched(fact, focus)]


def schema_for(state, allowed_sources=None, focus=None):
    """Constrain opaque capabilities instead of asking a model to copy hashes."""
    schema = copy.deepcopy(FACT_DELTA_SCHEMA)
    schema["properties"]["base_revision"] = {"type": "string", "enum": [state["revision"]]}
    targets = [fact["id"] for fact in reconciliation_targets(state, focus)]
    reconciliations = schema["properties"]["fact_reconciliations"]
    reconciliations.update(minItems=len(targets), maxItems=len(targets))
    for branch in reconciliations["items"]["anyOf"]:
        branch["properties"]["target_id"] = {"type": "string", "enum": targets or [""]}
        branch["properties"]["basis"] = {"type": "string", "minLength": 1, "maxLength": 180}
    operation = copy.deepcopy(FACT_DELTA_SCHEMA["properties"]["fact_operations"]["items"])
    # Bound enum count/length for structured-output providers. Larger catalogs
    # retain string references, which still face exact application validation.
    refs = sorted(set(allowed_sources or []))
    if refs and len(refs) <= 200 and sum(map(len, refs)) <= 12000:
        operation["properties"]["evidence_turns"] = {"type": "array", "items": {"type": "string", "enum": refs}}
        reconciliations["items"]["anyOf"][0]["properties"]["evidence_turns"] = copy.deepcopy(operation["properties"]["evidence_turns"])
    add = copy.deepcopy(operation)
    add["properties"]["op"] = {"type": "string", "enum": ["add"]}
    add["properties"]["target_id"] = {"type": "string", "enum": [""]}
    add["properties"]["reason"] = {"type": "string", "enum": ["new_evidence"]}
    add["properties"]["text"] = {"type": "string", "minLength": 1, "maxLength": MAX_FACT_TEXT}
    branches = [add]
    for gap in (False, True):
        targets = sorted(fact["id"] for fact in state["facts"] if fact["state"] == "active"
                         and (fact["kind"] == "gap") == gap)
        if not targets:
            continue
        for op in ("replace", "remove"):
            edit = copy.deepcopy(operation)
            edit["properties"]["op"] = {"type": "string", "enum": [op]}
            edit["properties"]["target_id"] = {"type": "string", "enum": targets}
            edit["properties"]["text"] = {"type": "string", "minLength": 0 if op == "remove" else 1,
                                           "maxLength": MAX_FACT_TEXT}
            edit["properties"]["reason"] = {"type": "string", "enum": [
                "participant_correction", "capture_correction", "withdrawal"] + (["resolved_gap"] if gap else [])}
            branches.append(edit)
    schema["properties"]["fact_operations"]["items"] = branches[0] if len(branches) == 1 else {"anyOf": branches}
    return schema


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def sources(context, turns, documents, *, include_retained=False):
    result = {"context": {"hash": _digest(context), "authority": "context"}}
    for index, turn in enumerate(turns):
        if turn.get("role") == "user" and not turn.get("document_event"):
            result[turn["id"]] = {"hash": _digest(turn["text"]), "authority": "participant", "position": index}
    for item in documents or []:
        if include_retained or not item.get("retained_only") and not item.get("provenance_only"):
            result[item["id"]] = {"hash": _digest(item), "authority": "document"}
    return result


def empty_state():
    return {"version": 1, "facts": [], "seeded_document_versions": {}, "topics": {
        key: {"status": "unknown", "discussed": False, "participant_unavailable": False}
        for key in TOPICS}, "revision": _digest([])}


def _refresh(state):
    active = [fact for fact in state["facts"] if fact["state"] == "active"]
    if len(active) > MAX_ACTIVE_FACTS:
        raise ValueError("The interview contains too many active fact records.")
    if len(state["facts"]) > MAX_FACT_RECORDS:
        retired = [fact for fact in state["facts"] if fact["state"] != "active"]
        remove = {fact["id"] for fact in retired[:len(state["facts"]) - MAX_FACT_RECORDS]}
        state["facts"] = [fact for fact in state["facts"] if fact["id"] not in remove]
    state["revision"] = _digest({"facts": state["facts"], "topics": state["topics"],
                                 "tags": state.get("tags", []), "connections_out": state.get("connections_out", []),
                                 "seeded_document_versions": state.get("seeded_document_versions", {})})
    return state


def document_versions(supporting, documents):
    """Read server-owned document identities independently of query selection."""
    selected = {}
    active_sources = [item for item in documents or [] if not item.get("retained_only") and not item.get("provenance_only")]
    for document in supporting.get("documents", []):
        supplied = [item for item in active_sources if item.get("document_id") == document["id"]]
        if not supplied:
            continue
        revision = document.get("source_revision")
        if not isinstance(revision, str) or not re.fullmatch(r"[a-f0-9]{64}", revision):
            # Legacy/adaptor contexts lack an authoritative file revision. Do
            # not infer unchanged source identity; use exact supplied evidence.
            revision = _digest({"document": document["id"], "purpose": document.get("purpose"),
                                "sources": sorted(supplied, key=lambda item: item["id"])})
        selected[document["id"]] = revision
    active = None
    if "source_versions" in supporting:
        rows = supporting["source_versions"]
        if not isinstance(rows, list) or len(rows) > 100:
            raise ValueError("Invalid active document revision catalog.")
        active = {}
        for row in rows:
            if (not isinstance(row, dict) or not isinstance(row.get("id"), str)
                    or not isinstance(row.get("source_revision"), str)
                    or not re.fullmatch(r"[a-f0-9]{64}", row["source_revision"]) or row["id"] in active):
                raise ValueError("Invalid active document revision.")
            active[row["id"]] = row["source_revision"]
        if any(active.get(identity) != revision for identity, revision in selected.items()):
            raise ValueError("Supplied document revision disagrees with the active catalog.")
    return selected, active


def reconcile_document_versions(state, active_versions, seeded=None):
    state = copy.deepcopy(state)
    known = state.setdefault("seeded_document_versions", {})
    if active_versions is not None:
        known = {identity: revision for identity, revision in known.items() if active_versions.get(identity) == revision}
    known.update(seeded or {})
    state["seeded_document_versions"] = known
    return _refresh(state)


def _new_fact(topic, kind, text, refs, catalog, origin="lead", *, allow_empty=False):
    if (not isinstance(text, str) or (not allow_empty and not text.strip()) or len(text) > MAX_FACT_TEXT
            or not isinstance(refs, list) or not refs or len(refs) > 100
            or any(not isinstance(ref, str) for ref in refs)
            or len(set(refs)) != len(refs) or not set(refs) <= set(catalog)):
        raise ValueError("A fact requires bounded text and exact authorized evidence.")
    return {"id": "fact_" + uuid.uuid4().hex, "topic": topic, "kind": kind,
            "text": text.strip(), "evidence_turns": list(refs),
            "sources": {ref: copy.deepcopy(catalog[ref]) for ref in refs},
            "created_at_participant": max((value["position"] for value in catalog.values()
                if value["authority"] == "participant"), default=-1),
            "state": "active", "origin": origin}


def _sentences(answer):
    # Split only for explicit legacy/independent-review import. Keep punctuation
    # and order; no semantic interpretation or network extraction is performed.
    result = re.split(r"(?<=[.!?])\s+(?=[A-Z])|\n+", answer.strip())
    if any(len(text) > MAX_FACT_TEXT for text in result):
        raise ValueError("A migrated fact is too large; recapture it from full evidence.")
    return [text for text in result if text]


def seed_legacy(capture, context, turns, documents):
    """Explicit migration of a server-owned capture; never browser/provider fallback."""
    state, catalog = empty_state(), sources(context, turns, documents, include_retained=True)
    retired = {item["id"] for item in documents or [] if item.get("retained_only") or item.get("provenance_only")}
    for finding in capture.get("memo_findings", []):
        if finding["key"] not in TOPICS:
            raise ValueError("Unknown migrated topic.")
        topic = state["topics"][finding["key"]]
        topic.update(status="partial" if finding["status"] != "unknown" else "unknown",
                     discussed=bool(finding.get("evidence_turns")))
        for text in _sentences(finding["answer"]):
            if finding["status"] != "unknown":
                fact = _new_fact(finding["key"], "detail", text,
                                 finding["evidence_turns"], catalog, "legacy_aid")
                if set(finding["evidence_turns"]) & retired:
                    fact["state"] = "retired_source"
                state["facts"].append(fact)
    return _refresh(state)


def rebase(state, context, turns, documents):
    state = copy.deepcopy(state)
    catalog = sources(context, turns, documents)
    for fact in state["facts"]:
        if fact["state"] == "active" and any(catalog.get(ref) != value for ref, value in fact["sources"].items()):
            fact["state"] = "retired_source"
            state["topics"][fact["topic"]].update(status="partial", participant_unavailable=False)
    for key in ("tags", "connections_out"):
        state[key] = [item for item in state.get(key, [])
                      if all(catalog.get(ref) == fingerprint for ref, fingerprint in item["sources"].items())]
    return _refresh(state)


def model_state(state, focus=None):
    return {"base_revision": state["revision"], "topics": copy.deepcopy(state["topics"]),
            "tags": [{k: copy.deepcopy(v) for k, v in item.items() if k != "sources"} for item in state.get("tags", [])],
            "connections_out": [{k: copy.deepcopy(v) for k, v in item.items() if k != "sources"} for item in state.get("connections_out", [])],
            "reconciliation_targets": [fact["id"] for fact in reconciliation_targets(state, focus)],
            "facts": [{key: copy.deepcopy(fact[key]) for key in
                       ("id", "topic", "kind", "text", "evidence_turns", "origin")}
                      for fact in state["facts"] if fact["state"] == "active"]}


_TOPIC_WORDS = {
    "name": r"name|called|alias", "purpose": r"purpose|result|outcome|deliver",
    "trigger": r"start|trigger|cadence|frequency|deadline|receiv|detect",
    "completion": r"finish|complet|clos|handoff|settle", "accountable": r"owner|owns?\b|accountab|responsib",
    "lifecycle": r"step|route|stage|handoff|workflow|release|receive|next|prepar|process",
    "checks": r"check|approv|review|sign.off|control|reconcil", "variations": r"varia|differ|client|fund|country|currency",
    "pain_points": r"pain|manual|difficult|rekey|effort|time|bottleneck", "risk": r"risk|wrong|fail|consequence|impact",
    "materials": r"material|file|template|procedure|document|location|stored|retention",
    "scope": r"entity|entities|fund|manco|standard|client|scope|parent|enterprise",
    "rules": r"rule|source|agreement|lpa|side.letter|calculat|method|policy|interpret",
    "connections": r"upstream|downstream|parallel|depend|input|output|handoff|process",
    "data_systems": r"data|system|record|origin|manual|import|spreadsheet|workbook|rekey",
    "volume": r"volume|count|many|peak|effort|time|frequency|exception",
}

_REPORTED_GAP = re.compile(
    r"\b(?:unknown|unconfirmed|unspecified|unavailable|not (?:recorded|known|confirmed|specified|established)|"
    r"(?:does not|doesn't|doesn’t) (?:identify|name|state|specify|say|describe))\b", re.I)


def _gap_discussed(topic, gaps, turns, documents):
    """A model's absence note is not proof the participant discussed a topic."""
    by_id = {turn["id"]: (index, turn) for index, turn in enumerate(turns)}
    source_text = {item["id"]: item.get("text", "") for item in documents or []
                   if not item.get("retained_only") and not item.get("provenance_only")}
    pattern = r"\b(?:" + _TOPIC_WORDS[topic] + r")"
    for gap in gaps:
        for ref in gap["evidence_turns"]:
            item = by_id.get(ref)
            if item and item[1].get("role") == "user" and not item[1].get("document_event"):
                index, turn = item
                question = turns[index - 1]["text"] if index and turns[index - 1]["role"] == "assistant" else ""
                if re.search(pattern, question, re.I):
                    return True
                if re.search(pattern, turn["text"], re.I) and (
                        explicit_knowledge_gap(turn["text"]) or _REPORTED_GAP.search(turn["text"])):
                    return True
            elif ref in source_text and re.search(pattern, source_text[ref], re.I) and _REPORTED_GAP.search(source_text[ref]):
                return True
    return False


def _unavailable(topic, gaps, turns):
    if not gaps:
        return False
    by_id = {turn["id"]: (index, turn) for index, turn in enumerate(turns)}
    for gap in gaps:
        found = False
        for ref in gap["evidence_turns"]:
            item = by_id.get(ref)
            if not item or item[1].get("role") != "user" or item[1].get("document_event"):
                continue
            index, turn = item
            finding = {"key": topic, "status": "partial", "answer": gap["text"], "evidence_turns": [ref]}
            if not finding_reports_unavailable_knowledge(finding, turns):
                continue
            prior_question = turns[index - 1]["text"] if index and turns[index - 1]["role"] == "assistant" else ""
            # The question scopes a short answer; only the participant answer
            # establishes unavailability. A generic document caveat cannot be
            # spread over all sixteen topics without topic-specific support.
            scope = turn["text"] + " " + prior_question
            if re.search(_TOPIC_WORDS[topic], scope, re.I):
                found = True
                break
        if not found:
            return False
    return True


def apply_delta(state, delta, context, turns, documents, focus=None):
    """Apply an already schema-checked transaction atomically to private state."""
    if delta["base_revision"] != state["revision"]:
        raise ValueError("Fact transaction refers to a stale capture revision.")
    rows, operations = delta["topic_states"], delta["fact_operations"]
    if len(rows) != len(TOPICS) or {row["key"] for row in rows} != set(TOPICS):
        raise ValueError("All sixteen fact topic states are required exactly once.")
    if len(operations) > MAX_OPERATIONS:
        raise ValueError("Too many fact operations in one answer.")
    result, catalog, seen = copy.deepcopy(state), sources(context, turns, documents), set()
    tags = copy.deepcopy(result.get("tags", []))
    tag_seen = set()
    for operation in delta.get("tag_operations", []):
        if len(delta["tag_operations"]) > 128:
            raise ValueError("Too many taxonomy operations.")
        candidate = {key: operation[key] for key in gpfs_interview.TAG_FIELDS}
        if operation["op"] != "remove":
            gpfs_interview.validate_metadata({"taxonomy": [candidate]}, catalog)
            gpfs_interview.validate_corroboration({"taxonomy": [candidate]}, turns, documents)
        elif not candidate["evidence_turns"] or not set(candidate["evidence_turns"]) <= set(catalog):
            raise ValueError("Removing a tag requires exact correction evidence.")
        target = operation["target_id"]
        if operation["op"] == "add":
            if target:
                raise ValueError("An added tag cannot replace a prior tag.")
        else:
            old = next((item for item in tags if item["id"] == target), None)
            if not old or target in tag_seen or old["facet"] != candidate["facet"]:
                raise ValueError("A tag correction requires one active tag in its facet.")
            tags.remove(old)
            tag_seen.add(target)
        if operation["op"] != "remove" and not any(all(item[k] == v for k, v in candidate.items()) for item in tags):
            tags.append({"id": "tag_" + uuid.uuid4().hex, **candidate,
                         "sources": {ref: copy.deepcopy(catalog[ref]) for ref in candidate["evidence_turns"]}})
    if len(tags) > 128:
        raise ValueError("Too many active taxonomy records.")
    result["tags"] = tags
    connections = delta.get("connections_out", [
        {key: value for key, value in item.items() if key != "sources"} for item in result.get("connections_out", [])])
    gpfs_interview.validate_metadata({"connections_out": connections}, catalog)
    result["connections_out"] = [{**copy.deepcopy(item), "sources": {
        ref: copy.deepcopy(catalog[ref]) for ref in item["evidence_turns"]}} for item in connections]
    required = {fact["id"] for fact in reconciliation_targets(state, focus)}
    reconciliations = delta.get("fact_reconciliations")
    if (not isinstance(reconciliations, list) or len(reconciliations) != len(required)
            or any(not isinstance(row, dict) for row in reconciliations)
            or any(not isinstance(row.get("target_id"), str) for row in reconciliations)
            or {row.get("target_id") for row in reconciliations} != required):
        raise ValueError("Every outstanding gap or unresolved qualifier requires an explicit reconciliation.")
    for row in reconciliations:
        disposition, basis = row.get("disposition"), row.get("basis")
        fields = {"target_id", "disposition", "basis"} | ({"evidence_turns"} if disposition == "unchanged" else set())
        if (disposition not in ("unchanged", "replace", "remove") or not isinstance(basis, str)
                or not basis.strip() or len(basis) > 180 or set(row) != fields):
            raise ValueError("A fact reconciliation requires a bounded basis and exact authorized evidence.")
        if disposition == "unchanged":
            refs = row["evidence_turns"]
            if (not isinstance(refs, list) or not refs or any(not isinstance(ref, str) for ref in refs)
                    or len(refs) != len(set(refs)) or not set(refs) <= set(catalog)):
                raise ValueError("An unchanged gap requires exact authorized evidence.")
        matching = [operation for operation in operations if operation.get("target_id") == row["target_id"]]
        if (disposition == "unchanged" and matching or disposition != "unchanged" and
                (len(matching) != 1 or matching[0]["op"] != disposition)):
            raise ValueError("A reconciliation disposition must match its explicit fact operation.")
    existing = {fact["id"]: fact for fact in result["facts"] if fact["state"] == "active"}
    for operation in operations:
        op, target, topic = operation["op"], operation["target_id"], operation["topic"]
        if topic not in TOPICS or op not in ("add", "replace", "remove"):
            raise ValueError("Invalid fact operation.")
        # Validate the correction's authority too, even when it removes a fact.
        new = _new_fact(topic, operation["kind"], operation["text"], operation["evidence_turns"], catalog,
                        allow_empty=op == "remove")
        if op == "add":
            if target or operation["reason"] != "new_evidence":
                raise ValueError("An added fact cannot replace an existing record.")
        else:
            old = existing.get(target)
            if not old or target in seen or old["topic"] != topic or operation["reason"] == "new_evidence":
                raise ValueError("A correction requires one active fact in its own topic.")
            if operation["reason"] == "resolved_gap" and old["kind"] != "gap":
                raise ValueError("Resolving a gap cannot retire a material detail.")
            if operation["reason"] in ("participant_correction", "withdrawal") and not any(
                    value["authority"] == "participant" and value["position"] > old["created_at_participant"]
                    for value in new["sources"].values()):
                raise ValueError("A participant correction needs new participant evidence.")
            seen.add(target)
            old.update(state="superseded" if op == "replace" else "withdrawn",
                       change_reason=operation["reason"], change_evidence=operation["evidence_turns"],
                       change_text=operation["text"])
        if op != "remove":
            # Exact duplicate additions do not grow the ledger on retries.
            if not any(fact["state"] == "active" and fact["topic"] == topic
                       and fact["kind"] == new["kind"] and fact["text"] == new["text"]
                       and fact["evidence_turns"] == new["evidence_turns"] for fact in result["facts"]):
                result["facts"].append(new)
    for row in rows:
        key = row["key"]
        facts = [fact for fact in result["facts"] if fact["state"] == "active" and fact["topic"] == key]
        gaps = [fact for fact in facts if fact["kind"] == "gap"]
        status = row["status"]
        if not facts:
            status = "unknown"
        elif status == "unknown" or gaps:
            status = "partial"
        if status == "not_applicable" and not any(fact["kind"] == "not_applicable" and any(
                value["authority"] == "participant" for value in fact["sources"].values()) for fact in facts):
            status = "partial"
        discussed = any(fact["kind"] != "gap" for fact in facts) or _gap_discussed(key, gaps, turns, documents)
        result["topics"][key] = {"status": status, "discussed": bool(discussed),
            "participant_unavailable": bool(row["participant_unavailable"] and _unavailable(key, gaps, turns))}
    return _refresh(result)


def findings(state):
    result = []
    for key in TOPICS:
        facts = [fact for fact in state["facts"] if fact["state"] == "active" and fact["topic"] == key]
        answer = "\n".join(dict.fromkeys(fact["text"] for fact in facts))
        if len(answer) > 12000:
            raise ValueError("A topic exceeds the supported detail bound; no facts were silently truncated.")
        refs = list(dict.fromkeys(ref for fact in facts for ref in fact["evidence_turns"]))
        result.append({"key": key, "status": state["topics"][key]["status"] if facts else "unknown",
                       "answer": answer, "evidence_turns": refs})
    return result


def discussion(state):
    """Source-backed discussion progress, separate from completeness proposals.

    A topic can have useful recorded testimony while remaining partial. Absence
    notes alone and retired source facts must not count as discussed testimony.
    """
    rows = []
    for key in TOPICS:
        refs = list(dict.fromkeys(ref for fact in state['facts']
            if fact['state'] == 'active' and fact['topic'] == key
            for ref in fact['evidence_turns']))
        discussed = bool(state['topics'][key]['discussed'] and refs)
        rows.append({'key': key, 'discussed': discussed,
                     'evidence_turns': refs if discussed else []})
    return rows


def public_capture(state, delta, labels):
    return {"question": delta["question"], "summary": delta["summary"], "focus": delta["focus"],
            "parking_lot": delta["parking_lot"], "memo_findings": findings(state),
            "coverage": [{"key": key, "label": labels[key], "status": "missing"} for key in TOPICS],
            "closure": {"asked": False, "confirmed": False}, "ready_for_draft": False,
            "taxonomy": [{k: copy.deepcopy(v) for k, v in item.items() if k not in ("id", "sources")} for item in state.get("tags", [])],
            "connections_out": [{k: copy.deepcopy(v) for k, v in item.items() if k != "sources"} for item in state.get("connections_out", [])],
            "active_modules": delta.get("active_modules", []), "recap_due": delta.get("recap_due", "none")}


def sync_review(state, capture, context, turns, documents):
    """Persist explicit validated coverage repairs; never infer edits from prose."""
    state, catalog = copy.deepcopy(state), sources(context, turns, documents)
    for repair in capture.get("coverage_assessment", {}).get("capture_repairs", []):
        key = repair["key"]
        finding = next(item for item in capture["memo_findings"] if item["key"] == key)
        if repair["answer"] != finding["answer"] or repair["evidence_turns"] != finding["evidence_turns"]:
            raise ValueError("Coverage repair and published answer disagree.")
        kind = "not_applicable" if finding["status"] == "not_applicable" else "detail"
        replacements = [_new_fact(key, kind, sentence, repair["evidence_turns"], catalog, "coverage_repair")
                        for sentence in _sentences(repair["answer"])]
        for fact in state["facts"]:
            if fact["topic"] == key and fact["state"] == "active":
                fact["state"] = "superseded_review"
        state["facts"].extend(replacements)
    for finding in capture["memo_findings"]:
        state["topics"][finding["key"]]["status"] = finding["status"]
    return _refresh(state)
