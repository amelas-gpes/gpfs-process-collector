"""Private, bounded, source-bound fact transactions for a single interview call.

The ledger prevents omission from deleting prior facts. It does not certify a
model's interpretation: independent coverage/process review still owns that job.
"""
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import copy
import hashlib
import json
import re
import unicodedata
import uuid
import gpfs_interview

from interview_coverage import (TOPIC_DIMENSIONS, explicit_knowledge_gap, finding_reports_unavailable_knowledge,
                                statements, uncertain_wording)

TOPICS = tuple(TOPIC_DIMENSIONS)
MAX_ACTIVE_FACTS = 256
MAX_FACT_RECORDS = 512
MAX_OPERATIONS = 128
MAX_FACT_TEXT = 1600


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class RecordMetadataSource:
    """Provide identity and UTC time when creating a private ledger record."""

    new_uuid: Callable[[], uuid.UUID] = uuid.uuid4
    utc_now: Callable[[], datetime] = _utc_now

    def new_id(self, kind: str) -> str:
        return f"{kind}_{self.new_uuid().hex}"

    def timestamp(self) -> str:
        return self.utc_now().isoformat(timespec="milliseconds")


_SYSTEM_RECORDS = RecordMetadataSource()


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
    "question": {"type": "string", "maxLength": 1600, "description": "A short participant-facing question, when requested."},
    "base_revision": _TEXT,
    "fact_reconciliations": {"type": "array", "items": _RECONCILIATION},
    "topic_states": {"type": "array", "items": _object({
        "key": {"type": "string", "enum": list(TOPICS)},
        "status": {"type": "string", "enum": ["unknown", "partial", "captured", "not_applicable", "owner_followup"]},
        "participant_unavailable": {"type": "boolean"},
    })},
    "fact_operations": {"type": "array", "maxItems": MAX_OPERATIONS, "items": _object({
        "op": {"type": "string", "enum": ["add", "replace", "remove"]},
        "topic": {"type": "string", "enum": list(TOPICS)},
        "target_id": _TEXT,
        "kind": {"type": "string", "enum": ["detail", "gap", "not_applicable"]},
        "text": _TEXT, "evidence_turns": _REFS,
        "support": {"type": "array", "items": _object({"source_id": _TEXT, "quote": _TEXT}),
                    "description": "Verbatim supporting passages, each with the ID of an authorized cited source."},
        "reason": {"type": "string", "enum": ["new_evidence", "participant_correction", "capture_correction", "resolved_gap", "withdrawal"]},
    })},
    "summary": _TEXT, "focus": {"type": "string", "description": "Short plain-language topic shown to the participant under Now discussing."},
    "parking_lot": {"type": "array", "items": _TEXT, "description": "Open secondary points to revisit, kept across answers."},
})
FACT_DELTA_SCHEMA["properties"].update({
    "tag_operations": {"type": "array", "items": gpfs_interview.TAG_OPERATION},
    "connections_out": gpfs_interview.CONNECTIONS,
    "remove_connections": {"type":"array", "items": _object({"target_id": _TEXT, "evidence_turns": _REFS})},
    "resolved_parking_lot": {"type":"array", "items": _object({"text": _TEXT, "evidence_turns": _REFS})},
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
fact_state.topics[topic].held_for_wording, when present, names the fact (fact_id) and
the exact wording in it that made the application keep your proposed captured or
not_applicable topic partial: that wording reads as an unresolved point. If the
testimony leaves the point open, keep the topic partial, record the open point as a
gap and ask about it. If the testimony states it as a known fact, capture-correct
that fact to state what is known plainly, without the hedge. Do not propose the same
wording as complete again.
held_wording, when present, lists by topic the wording in the previous notes that reads
as an unresolved point and kept that topic partial; this turn starts without the earlier
fact_state that would carry held_for_wording. Treat each in the same way.
previous_capture.coverage_assessment.topics[].proposed_correction, when present, is a
corrected section the completion review proposed and the application did not apply; the
topic's gaps say why. findings_with_proposal_applied, when present, lists what the process
review found in the whole account with that proposal applied: a finding there may concern
another section and is not by itself an objection to the proposal. The proposal is a
reviewer's proposal, never evidence. Compare it with the participant's
own statements and correct your facts for that section with ordinary operations that cite
those statements. Do not record a statement, actor or step that no participant turn supports.
Every unmentioned active fact is retained. Do not rewrite unchanged facts or send
more than 128 operations. Existing fact IDs retain their topic. Moving a fact to another
topic requires a remove and an add. A participant correction or withdrawal cites a
participant turn later than the one on which the original fact was created. Use
capture_correction to repair an earlier interpretation of the same sources. When a
topic approaches its length budget, consolidate overlapping points with explicit
operations and retain their qualifications and citations. Do not send
the whole section as one fact. On the first call, seed all material facts available
in the full supplied conversation and authorized document excerpts, not only the
latest answer. On later calls, add newly learned facts AND backfill material facts
previous capture missed. Distinguish supplied source content from current practice.
Each fact must cite the exact passage that establishes its actor, action and
qualifiers. Put a short, substantive verbatim excerpt from each cited source in support.
Preserve quoted wording, numbers and role names. Preserve relevant
qualifiers. Detached PDF links or table cells do not establish a process relationship
solely by their extraction order. Preserve the supported functional handoff and
leave its destination unresolved when the source binding is ambiguous.

For each action in a note, identify the subject of its own clause. In first-person
testimony, "I" remains the speaker even when a different person is named in an
if-clause or owns the document being discussed. Separate who authorizes or sends
an item from who records, files, or receives it. When the same activity appears
under several topics, verify each attribution against the cited testimony and
repair earlier conflicting facts in this transaction. In Materials, describe the
artifact and its reported use; name its custodian only when the source identifies
that person. If the performer is unclear, preserve the action without assigning it.

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

One answer usually bears on several topics. After recording what it says, check every
other topic the same evidence touches and bring it up to date in this transaction: a
stated gate or requirement also belongs under rules, a named receiving process under
connections, a named record under materials. When evidence now supplies what an older
gap under ANY topic called unknown or unspecified, retire or narrow that gap with an
explicit operation and keep only the part that is still unanswered. No section may say
"unknown" or "not specified" about something another section, or a structured link of
this same capture, records.
connections_out and the connections topic describe the same links. State every link you
record under connections as well. A handoff the participant describes again in other
words is the same link: re-issue it with its wording and the added citation instead of
adding a second one. Record a separate link only when its outcome or condition differs.
A record, file, workbook, binder, package or report is prepared, sent, stored or received.
It is never the party that receives, checks, approves or finishes work, and a process
code such as FA-15A names a receiving process, not a person. Keep supporting records, the
process that receives them and the people who handle them apart in every fact.
The intake objective says why this interview is held. It is never the purpose of the
work: do not record it, or a restatement of it, under purpose.

Return all sixteen topic_states. unknown means no usable detail or discussed gap;
a discussed but unavailable detail is partial. participant_unavailable=true requires
an explicit, topic-specific participant knowledge limit supported by the gap's cited
participant turn (a short answer can be scoped by the immediately preceding question).
Generic inability to verify the whole procedure does not prove every topic unavailable.
Document omissions alone never establish participant unavailability. Captured and N/A
are provisional proposals, never permission to end, pause or offer to stop. The
application alone acknowledges a review and authorizes final checks or partial pauses.
Propose owner_followup only if the participant explains the applicable route and every remaining
gap is a specific owner decision, defined external handoff or nonmaterial detail. Record the
open point as a gap, and the reported interim action, affected scope and resolving role/source
as participant-cited facts. If sending vs acceptance, who acts, a release rule, or what happens
pending a decision is unclear, keep partial. A lead's owner_followup proposal stays partial until
independent review; it never makes the missing answer a fact.
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


def turn_focus(turns, baseline=None):
    """The latest participant answer and the question it answered, or None before any answer."""
    if baseline:
        current = [turn for index, turn in enumerate(turns) if turn.get("role") == "user"
                   and not turn.get("document_event") and (index >= len(baseline) or turn != baseline[index])]
        if current:
            questions = []
            for index, turn in enumerate(turns):
                if turn in current and index and turns[index - 1]["role"] == "assistant":
                    questions.append(turns[index - 1]["text"])
            return {"answer": " ".join(turn["text"] for turn in current), "question": " ".join(questions)}
    for index in range(len(turns) - 1, -1, -1):
        turn = turns[index]
        if turn.get("role") == "user" and not turn.get("document_event"):
            previous = turns[index - 1] if index else None
            question = previous["text"] if previous and previous.get("role") == "assistant" else ""
            return {"answer": turn.get("text", ""), "question": question}
    return None


def _content_words(text):
    words = re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", text).casefold())
    stems = {word[:5] for word in words if len(word) >= 4 and word not in _STOPWORDS}
    for block in re.findall(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7a3]+", text):
        stems.update(block[i:i + 2] for i in range(len(block) - 1))
    return stems


def _touched(fact, focus):
    """Could the latest answer (scoped by its question) affect this open claim?"""
    scope = focus["question"] + " " + focus["answer"]
    if re.search(r"\b(?:" + _TOPIC_WORDS[fact["topic"]] + r")", scope, re.I):
        return True
    if not re.search(r"[a-zA-Z]", scope) and any(char.isalpha() for char in scope):
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
    # A fact whose wording held a proposed complete topic at partial is an open claim too.
    held = {topic["held_for_wording"]["fact_id"] for topic in state["topics"].values() if "held_for_wording" in topic}
    targets = [fact for fact in state["facts"] if fact.get("state", "active") == "active"
               and (fact["kind"] == "gap" or fact["id"] in held or fact.get("needs_reconciliation")
                    or uncertain_wording(fact["text"], fact["topic"])
                    or re.search(r"\b(?:does not|doesn['’]t) (?:establish|specify|describe|identify|say|state)\b", fact["text"], re.I))]
    if focus is None:
        return targets
    return [fact for fact in targets if fact.get("needs_reconciliation") or _touched(fact, focus)]


def schema_for(state, allowed_sources=None, focus=None, with_question=True):
    """Constrain opaque capabilities instead of asking a model to copy hashes."""
    schema = copy.deepcopy(FACT_DELTA_SCHEMA)
    if not with_question:
        del schema["properties"]["question"]
        schema["required"].remove("question")
    if isinstance(allowed_sources, dict) and not any(source["authority"] == "document" for source in allowed_sources.values()):
        for branch in schema["properties"]["tag_operations"]["items"]["anyOf"]:
            values = branch["properties"]["value"]["enum"]
            if "gold_standard" in values:
                values.remove("gold_standard")
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
    # Stay within the project-wide dynamic enum budget, including repeated IDs
    # in the operation and reconciliation branches. The local validator checks
    # every source and target even when an enum is omitted.
    active_count = sum(fact["state"] == "active" for fact in state["facts"])
    compact = 6 * len(refs) + 4 * active_count + 2 * len(targets) > 650
    if compact:
        for branch in reconciliations["items"]["anyOf"]:
            branch["properties"]["target_id"] = {"type": "string"}
    if refs and not compact and len(refs) <= 200 and sum(map(len, refs)) <= 12000:
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
            edit["properties"]["target_id"] = {"type": "string"} if compact else {"type": "string", "enum": targets}
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
    state["revision"] = _digest({"facts": state["facts"], "topics": state["topics"], "parking_lot": state.get("parking_lot", []),
                                 "tags": state.get("tags", []), "connections_out": state.get("connections_out", []),
                                 "consolidation_required": state.get("consolidation_required", []),
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
        # Purpose and parking change review authority, but the actual source text
        # keeps its identity across those transitions.
        for row in rows:
            content = row.get("content_revision", row["source_revision"])
            if not isinstance(content, str) or not re.fullmatch(r"[a-f0-9]{64}", content):
                raise ValueError("Invalid document content revision.")
            active[row["id"]] = content
            if row["id"] in selected:
                selected[row["id"]] = content
    return selected, active


def reconcile_document_versions(state, active_versions, seeded=None):
    state = copy.deepcopy(state)
    known = state.setdefault("seeded_document_versions", {})
    if active_versions is not None:
        known = {identity: revision for identity, revision in known.items() if active_versions.get(identity) == revision}
    known.update(seeded or {})
    state["seeded_document_versions"] = known
    return _refresh(state)


def _new_fact(topic, kind, text, refs, catalog, origin="lead", *, allow_empty=False, records: RecordMetadataSource = _SYSTEM_RECORDS):
    if (not isinstance(text, str) or (not allow_empty and not text.strip()) or len(text) > MAX_FACT_TEXT
            or not isinstance(refs, list) or not refs or len(refs) > 100
            or any(not isinstance(ref, str) for ref in refs)
            or not set(refs) <= set(catalog)):
        raise ValueError("A fact requires bounded text and exact authorized evidence.")
    return {"id": records.new_id("fact"), "topic": topic, "kind": kind,
            "text": text.strip(), "evidence_turns": list(dict.fromkeys(refs)),
            "sources": {ref: copy.deepcopy(catalog[ref]) for ref in refs},
            "created_at_participant": max((value["position"] for value in catalog.values()
                if value["authority"] == "participant"), default=-1),
            "state": "active", "origin": origin, "recorded_at": records.timestamp()}


def _sentences(answer):
    # Split only for explicit legacy/independent-review import. Keep punctuation
    # and order; no semantic interpretation or network extraction is performed.
    # interview_coverage.statements is the same split: a coverage repair is refused
    # there when one of its statements would not fit a fact record here.
    result = statements(answer)
    if any(len(text) > MAX_FACT_TEXT for text in result):
        raise ValueError("A migrated fact is too large; recapture it from full evidence.")
    return result


def _source_proof(fact, passages, texts):
    """Review aids, never an assertion that a quote entails a claim."""
    def normalized(value):
        return " ".join(unicodedata.normalize("NFKC", value).translate(
            str.maketrans("‘’“”", "''\"\"")).casefold().split())
    cited = {ref: normalized(texts.get(ref, "")) for ref in fact["evidence_turns"]}
    support = []
    for passage in passages[:100]:
        ref, quote = passage.get("source_id"), passage.get("quote")
        if not isinstance(quote, str) or not isinstance(ref, str) or ref not in cited:
            continue
        phrase = normalized(quote)
        if len(phrase) >= 12 and len(phrase.split()) >= 3 and phrase in cited[ref]:
            support.append({"source_id": ref, "quote": quote.strip()[:800]})
    checks = []
    if set(cited) - {item["source_id"] for item in support}:
        checks.append("One or more cited sources lack a verified supporting passage.")
    corpus = " ".join(cited.values())
    for value in re.findall(r"(?<!\w)(?:[$€£]?\d[\d,.:/–-]*\d|[$€£]?\d)(?:\s*%|\s+(?:days?|hours?|minutes?|weeks?))?"
                            r"|\b(?:controller|registrar|instructor|custodian|treasurer|supervisor|preparer|reviewer|director|analyst|manager|CFO)\b",
                            fact["text"], re.I):
        if not re.search(r"(?<!\w)" + re.escape(normalized(value)) + r"(?!\w)", corpus):
            checks.append("Check this against the cited sources: " + value)
    fact.update(support=support, unverified=list(dict.fromkeys(checks)))


def seed_legacy(capture, context, turns, documents, *, records: RecordMetadataSource = _SYSTEM_RECORDS):
    """Explicit migration of a server-owned capture; never browser/provider fallback."""
    state, catalog = empty_state(), sources(context, turns, documents, include_retained=True)
    retired = {item["id"] for item in documents or [] if item.get("retained_only") or item.get("provenance_only")}
    for finding in capture.get("memo_findings", []):
        if finding["key"] not in TOPICS:
            raise ValueError("Unknown migrated topic.")
        topic = state["topics"][finding["key"]]
        topic.update(status="partial" if finding["status"] != "unknown" else "unknown",
                     discussed=any(catalog.get(ref, {}).get("authority") == "participant" for ref in finding.get("evidence_turns", [])))
        parts = [finding["answer"]] if finding["key"] == "name" and len(finding["answer"]) <= MAX_FACT_TEXT else _sentences(finding["answer"])
        for text in parts:
            if finding["status"] != "unknown":
                fact = _new_fact(finding["key"], "detail", text,
                                 finding["evidence_turns"], catalog, "legacy_aid", records=records)
                if set(finding["evidence_turns"]) & retired:
                    fact["state"] = "retired_source"
                state["facts"].append(fact)
    return _refresh(state)


def carried_sources(state, documents):
    """Document citations of active facts whose excerpt is outside this request."""
    current = {item["id"] for item in documents or []}
    return sorted({ref for fact in state["facts"] if fact["state"] == "active"
                   for ref, source in fact["sources"].items()
                   if source["authority"] == "document" and ref not in current})


def rebase(state, context, turns, documents, carried=()):
    """Retire facts whose sources changed.

    carried names excerpts of unchanged files that the caller confirmed for this
    interview but whose text this request could not carry. Such a source cannot
    be compared; it does not retire a fact. A source that is supplied is always
    compared.
    """
    state = copy.deepcopy(state)
    catalog = sources(context, turns, documents)
    def retain_sources(record):
        previous = record["sources"]
        current = {ref: catalog.get(ref, value) for ref, value in previous.items()
                   if (ref not in catalog and ref in carried) or
                   (ref in catalog and catalog[ref]["hash"] == value["hash"] and catalog[ref]["authority"] == value["authority"])}
        record["sources"] = current
        record["evidence_turns"] = [ref for ref in record["evidence_turns"] if ref in current]
        return len(current) == len(previous)
    for fact in state["facts"]:
        if fact["state"] == "active" and not retain_sources(fact):
            if fact["sources"]:
                fact["needs_reconciliation"] = True
            else:
                fact["state"] = "retired_source"
            state["topics"][fact["topic"]].update(status="partial", participant_unavailable=False)
    for key in ("tags", "connections_out"):
        for item in state.get(key, []):
            retain_sources(item)
        state[key] = [item for item in state.get(key, []) if item["sources"]]
    active = {fact["topic"] for fact in state["facts"] if fact["state"] == "active"}
    for key, topic in state["topics"].items():
        if key not in active:
            topic.update(status="unknown", discussed=False, participant_unavailable=False)
    return _refresh(state)


def model_state(state, focus=None):
    topics = copy.deepcopy(state["topics"])
    active = {fact["id"] for fact in state["facts"] if fact["state"] == "active"}
    for topic in topics.values():
        # A hold whose fact has since been retired has nothing left to point at.
        if "held_for_wording" in topic and topic["held_for_wording"]["fact_id"] not in active:
            del topic["held_for_wording"]
    for key, topic in topics.items():
        used = sum(len(fact["text"]) + 1 for fact in state["facts"] if fact["state"] == "active" and fact["topic"] == key)
        topic["remaining_characters"] = max(0, 12000 - max(0, used - 1))
    return {"base_revision": state["revision"], "topics": topics, "remaining_facts": MAX_ACTIVE_FACTS - len(active),
            "parking_lot": list(state.get("parking_lot", [])),
            "previous_summary": state.get("summary",""), "previous_focus": state.get("focus",""),
            "consolidation_required": state.get("consolidation_required", []),
            "tags": [{k: copy.deepcopy(v) for k, v in item.items() if k != "sources"} for item in state.get("tags", [])],
            "connections_out": [{k: copy.deepcopy(v) for k, v in item.items() if k != "sources"} for item in state.get("connections_out", [])],
            "reconciliation_targets": [fact["id"] for fact in reconciliation_targets(state, focus)],
            "facts": [{key: copy.deepcopy(fact[key]) for key in
                       ("id", "topic", "kind", "text", "evidence_turns", "origin", "created_at_participant") if key in fact}
                      for fact in state["facts"] if fact["state"] == "active"]}


def incremental_turns(turns, baseline, state, focus):
    """Keep new testimony, its surrounding questions, and earlier sources relevant to this change."""
    if len(turns) < 14 or not baseline or not focus:
        return turns
    # A revision, correction or ambiguous short answer warrants all the original wording.
    if turns[:len(baseline)] != baseline or len(focus["answer"].split()) < 7 or re.search(
            r"\b(actually|correction|instead|previous|earlier|i meant|used to|not anymore|scratch that)\b",
            focus["answer"], re.I):
        return turns
    related = {ref for f in state["facts"] if f["state"] == "active" and _touched(f, focus)
               for ref in f["evidence_turns"]}
    terms = _content_words(focus["answer"] + " " + focus["question"])
    start = max(0, len(baseline) - 4)
    keep = set(range(start, len(turns)))
    for n, turn in enumerate(turns[:start]):
        if turn["id"] in related or (turn["role"] == "user" and len(terms & _content_words(turn["text"])) >= 2):
            keep.add(n)
            if n:
                keep.add(n - 1)
    return [t for n, t in enumerate(turns) if n in keep]


LIVE_EXCERPT_SCHEMA = _object({
    "needs_full_capture": {"type": "boolean"},
    "facts": {"type": "array", "maxItems": 12, "items": _object({
        "topic": {"type": "string", "enum": list(TOPICS)}, "source_id": _TEXT, "quote": _TEXT})},
    "open_relationship": _TEXT, "gap_source_id": _TEXT,
})


def _caption_excerpt(source, proposed):
    if proposed in source:
        return proposed
    # The live captioner can place a space before a comma or omit a final
    # period. Recover the original span only when words and punctuation agree.
    parts = re.findall(r"\w+|[^\w\s]", proposed.removesuffix("."))
    if not parts:
        return ""
    pattern = re.escape(parts[0])
    for previous, part in zip(parts, parts[1:]):
        separator = r"\s+" if previous[-1].isalnum() and part[0].isalnum() else r"\s*"
        pattern += separator + re.escape(part)
    match = re.search(r"(?<!\w)" + pattern + r"(?!\w)" + (r"\.?" if proposed.endswith(".") else ""), source, re.I)
    return match.group() if match else ""


def excerpt_transaction(reply, state, new_answers):
    """Promote only exact participant clauses. A correction or a complex turn uses normal reconciliation."""
    if reply["needs_full_capture"] or not reply["facts"]:
        return None
    sources = {t["id"]: t["text"] for t in new_answers}
    states = {k: {"key": k, "status": "owner_followup" if v.get("owner_review_candidate") else v["status"],
                  "participant_unavailable": v["participant_unavailable"]} for k, v in state["topics"].items()}
    ops = []
    cited = defaultdict(list)
    known = {(f["topic"], f["text"], ref) for f in state["facts"] if f["state"] == "active" for ref in f["evidence_turns"]}
    for row in reply["facts"]:
        topic, ref, quote = row["topic"], row["source_id"], row["quote"].strip()
        if ref in sources and 5 <= len(quote) <= MAX_FACT_TEXT:
            quote = _caption_excerpt(sources[ref], quote)
        if (ref not in sources or topic not in states or len(quote) < 5 or len(quote) > MAX_FACT_TEXT
                or quote not in sources[ref] or states[topic]["status"] in ("not_applicable", "owner_followup")
                or states[topic]["participant_unavailable"]):
            return None
        cited[ref].append(quote)
        if (topic, quote, ref) in known:
            continue
        known.add((topic, quote, ref))
        ops.append({"op":"add", "topic":topic, "target_id":"", "kind":"detail", "text":quote,
                    "reason":"new_evidence", "evidence_turns":[ref], "support":[{"source_id":ref, "quote":quote}]})
        states[topic]["status"] = "partial"
    if set(sources) != set(cited):
        return None
    for ref, answer in sources.items():
        clauses = re.split(r"(?<=[.!?;])\s+", answer)
        quotes = cited[ref]
        words = _content_words(answer)
        if words and len(words & _content_words(" ".join(quotes))) / len(words) < .8:
            return None
        # Quoting an affirmative substring inside a negated or conditional sentence
        # reverses its meaning. Keep the whole qualification or use the full review.
        for quote in quotes:
            for clause in clauses:
                if quote not in clause:
                    continue
                qualifier = r"\b(?:never|not|no|only|unless|except|until|without|if|otherwise|\d+(?:[,.]\d+)*)\b|n't\b"
                if not set(re.findall(qualifier, clause.casefold())) <= set(re.findall(qualifier, quote.casefold())):
                    return None
    return {"base_revision":state["revision"], "topic_states":list(states.values()), "fact_operations":ops,
            "fact_reconciliations":[], "summary":state.get("summary") or next(iter(cited.values()))[0],
            "focus":reply["facts"][0]["topic"], "parking_lot":list(state.get("parking_lot", [])),
            "tag_operations":[], "connections_out":[], "remove_connections":[], "resolved_parking_lot":[],
            "active_modules":state.get("active_modules", []), "recap_due":"none"}


_TOPIC_WORDS = {
    "name": r"name|called|alias", "purpose": r"purpose|result|outcome|deliver",
    "trigger": r"start|trigger|cadence|frequency|deadline|receiv|detect",
    "completion": r"finish|complet|clos|handoff|settle", "accountable": r"owner|owns?\b|accountab|responsib",
    "lifecycle": r"step|route|stage|handoff|workflow|release|receive|next|prepar|process",
    "checks": r"check|approv|review|sign.off|control|reconcil", "variations": r"varia|differ|client|fund|country|currency",
    "pain_points": r"pain|manual|difficult|rekey|effort|time|bottleneck", "risk": r"risk|wrong|fail|consequence|impact",
    "materials": r"material|file|template|procedure|document|location|stored|retention",
    "scope": r"entity|entities|fund|manco|standard|client|scope|parent|enterprise",
    "rules": r"rule|source|agreement|lpa|side.letter|calculat|method|policy|interpret|requir|must\b|cannot|gate\b|gates\b|mandator|prohibit|permitted|allowed",
    "connections": r"upstream|downstream|parallel|depend|input|output|handoff|process|takes? over|hands? (?:it |them )?(?:off|over)|[a-z]{2,5}-\d{1,3}[a-z]?\b",
    "data_systems": r"data|system|record|origin|manual|import|spreadsheet|workbook|rekey",
    "volume": r"volume|count|many|peak|effort|time|frequency|exception",
}

_REPORTED_GAP = re.compile(
    r"\b(?:unknown|unconfirmed|unspecified|unavailable|not (?:recorded|known|confirmed|specified|established)|"
    r"(?:does not|doesn't|doesn’t) (?:identify|name|state|specify|say|describe))\b", re.I)


def _gap_discussed(topic, gaps, turns, documents):
    """A model's absence note is not proof the participant discussed a topic."""
    by_id = {turn["id"]: (index, turn) for index, turn in enumerate(turns)}
    pattern = _gap_scope_pattern(topic)
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
    return False


def _gap_scope_pattern(topic):
    # Context nouns (client, process, time, data) appear in questions about
    # many different topics. Only a specific information need scopes a bare
    # "I don't know" to one of those headings.
    subject = {
        # Narrower than _TOPIC_WORDS["rules"], whose everyday words ("must", "cannot") only
        # decide which gaps an answer reopens: they do not make a topic one the participant discussed.
        "rules": r"rule|source|agreement|lpa|side.letter|calculat|method|policy|interpret",
        "variations": r"varia\w*|differ\w*|alternate routes?|exceptions?",
        "scope": r"entit\w*|scope|applicab\w*|which (?:funds?|clients?|countries)",
        "pain_points": r"pain\w*|manual\w*|difficult\w*|delay\w*|rekey\w*|bottleneck\w*",
        "volume": r"volume\w*|how (?:many|often|long)|peak\w*|effort|frequen\w*",
        "data_systems": r"systems?|record of truth|source of truth|origin\w*|spreadsheets?|workbooks?|rekey\w*",
        "connections": r"upstream|downstream|dependenc\w*|other process\w*|feeds? into|hands? off to",
    }.get(topic, _TOPIC_WORDS[topic])
    return r"\b(?:" + subject + r")"


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
            if re.search(_gap_scope_pattern(topic), scope, re.I):
                found = True
                break
        if not found:
            return False
    return True


_CONDITION_FILLER = frozenset("""a an the is are was were be been being it this that these those to of for in on at by with
    as and or then when if once after before will would can may also""".split())
# How the Connections note words a structured link to another process, role or party.
CONNECTION_WORDING = {"provides_input_to": "Provides input to", "consumes": "Uses the output of", "hands_off_to": "Hands off to",
                      "requires_approval_from": "Requires approval from", "happens_after": "Happens after",
                      "variant_of": "Is a variant of", "subprocess_of": "Is a subprocess of",
                      "parallel_with": "Runs in parallel with", "shares_calculation_with": "Shares a calculation with"}
STRUCTURED_LINK = "structured_link"
OBJECTIVE_GAP = "The intake states the interview objective. The business purpose remains unconfirmed."


def _condition_words(text):
    return {word for word in re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", text).casefold()) if word not in _CONDITION_FILLER}


def same_condition(left, right):
    """Whether two conditions of one link to one counterpart say the same thing.

    A participant who describes a handoff twice words it twice ("unresolved screening is
    escalated", "unresolved or failed screening is escalated"). Those are one link. The
    test is deliberately narrow: every word of the shorter wording occurs in the longer,
    the longer adds at most two words, and any figures are the same in both. Wordings
    that name different outcomes ("clearance is communicated", "a block is communicated")
    share too little and stay separate links.
    """
    one, other = sorted((_condition_words(left), _condition_words(right)), key=len)
    if len(one) < 2 or not one <= other or len(other - one) > 2:
        return one == other and bool(one)
    return {word for word in one if any(char.isdigit() for char in word)} == {word for word in other if any(char.isdigit() for char in word)}


def merge_equivalent_connections(items):
    """One link per relationship, counterpart and condition, keeping every citation.

    The fuller wording of an equivalent condition is kept, with the identity of the link
    that was recorded first and the sources of both.
    """
    merged = []
    for item in items:
        match = next((old for old in merged if old["relationship_type"] == item["relationship_type"]
                      and old["counterpart"].casefold() == item["counterpart"].casefold()
                      and (old["condition"].casefold() == item["condition"].casefold() or same_condition(old["condition"], item["condition"]))), None)
        if match is None:
            merged.append(copy.deepcopy(item))
            continue
        sources = {**match.get("sources", {}), **copy.deepcopy(item.get("sources", {}))}
        if len(_condition_words(item["condition"])) > len(_condition_words(match["condition"])):
            match["condition"] = item["condition"]
        match.update(sources=sources, evidence_turns=list(sources) or list(dict.fromkeys([*match["evidence_turns"], *item["evidence_turns"]])),
                     created_at_participant=min(match.get("created_at_participant", -1), item.get("created_at_participant", -1)))
    return merged


def _names(text, counterpart):
    """Whether a note names this counterpart: by its whole name, or by its process code (FA-16)."""
    plain = " ".join(unicodedata.normalize("NFKC", text).casefold().split())
    name = " ".join(unicodedata.normalize("NFKC", counterpart).casefold().split())
    code = re.match(r"[a-z]{2,5}-\d+[a-z]?(?![\w-])", name)
    return bool(name) and (name in plain or bool(code and re.search(r"(?<![\w-])" + re.escape(code.group(0)) + r"(?![\w-])", plain)))


def _note_structured_connections(result, catalog, texts, records: RecordMetadataSource):
    """Keep the Connections note in step with the structured links of the same capture.

    The links to other processes are recorded as structured connections and, separately,
    described under the Connections topic. A capture could record a handoff as a link
    while its Connections note still read "unknown": two panels then contradicted each
    other. Every link whose counterpart no detail of that topic names is stated there as
    a detail of its own, with the link's sources. The statement goes when the link goes,
    or when the notes come to name the counterpart themselves. Nothing here reads a
    source or decides anything: it restates a link the same capture already accepted.
    """
    links = {item["id"]: item for item in result.get("connections_out", [])}
    active = [fact for fact in result["facts"] if fact["state"] == "active" and fact["topic"] == "connections"]
    written = [fact for fact in active if fact["kind"] == "detail" and fact.get("origin") != STRUCTURED_LINK]
    for fact in active:
        if fact.get("origin") != STRUCTURED_LINK:
            continue
        link = links.get(fact.get("connection_id"))
        if link is None or any(_names(other["text"], link["counterpart"]) for other in written):
            fact.update(state="withdrawn", change_reason="withdrawal", change_evidence=list(fact["evidence_turns"]), change_text="")
    stated = {fact.get("connection_id") for fact in result["facts"]
              if fact["state"] == "active" and fact.get("origin") == STRUCTURED_LINK}
    count = sum(fact["state"] == "active" for fact in result["facts"])
    size = len("\n".join(fact["text"] for fact in result["facts"] if fact["state"] == "active" and fact["topic"] == "connections"))
    for identity, link in links.items():
        refs = [ref for ref in link["evidence_turns"] if ref in catalog]
        if identity in stated or not refs or any(_names(other["text"], link["counterpart"]) for other in written):
            continue
        condition = link["condition"].strip()
        text = CONNECTION_WORDING[link["relationship_type"]] + " " + link["counterpart"].strip() + (": " + condition if condition else "")
        text = (text if text.endswith((".", "!", "?")) else text + ".")[:MAX_FACT_TEXT]
        if count >= MAX_ACTIVE_FACTS or size + len(text) + 1 > 12000:
            break
        fact = _new_fact("connections", "detail", text, refs, catalog, STRUCTURED_LINK, records=records)
        fact["connection_id"] = identity
        _source_proof(fact, [], texts)
        fact["unverified"] = []  # It restates an accepted link; the link carries the citation.
        result["facts"].append(fact)
        count, size = count + 1, size + len(text) + 1


def _settle_objective_as_purpose(result, context):
    """The interview's objective is not the purpose of the work.

    The intake's objective says why the interview is held ("document how this process
    works, including its controls"). A purpose statement that rests on the intake alone
    can only restate that, unless the factual background field says more. Such a
    statement is not kept as the business purpose: it is dropped when participant or
    document evidence states the purpose, and otherwise recorded as the open gap it is.
    That gap is retired in turn once evidence states the purpose.
    """
    objective = _normalized_detail(str(context.get("objective", "")))
    background = _normalized_detail(str(context.get("background", "")))
    purpose = [fact for fact in result["facts"] if fact["state"] == "active" and fact["topic"] == "purpose"]
    evidenced = any(fact["kind"] == "detail" and any(source["authority"] != "context" for source in fact["sources"].values())
                    for fact in purpose)
    for fact in purpose:
        if set(fact["evidence_turns"]) != {"context"}:
            continue
        restated = fact["text"] == OBJECTIVE_GAP or (fact["kind"] == "detail" and bool(objective) and (
            not background or objective in _normalized_detail(fact["text"]) and objective not in background))
        if not restated:
            continue
        if evidenced:
            fact.update(state="withdrawn", change_reason="capture_correction", change_evidence=["context"], change_text="")
        elif fact["text"] != OBJECTIVE_GAP:
            fact.update(kind="gap", text=OBJECTIVE_GAP, support=[], unverified=[])


def apply_delta(state, delta, context, turns, documents, focus=None, *, preserve_on_limit=False,
                records: RecordMetadataSource = _SYSTEM_RECORDS):
    """Apply an already schema-checked transaction atomically to private state."""
    if delta["base_revision"] != state["revision"]:
        raise ValueError("Fact transaction refers to a stale capture revision.")
    rows, operations = delta["topic_states"], delta["fact_operations"]
    if len(rows) != len(TOPICS) or {row["key"] for row in rows} != set(TOPICS):
        raise ValueError("All sixteen fact topic states are required exactly once.")
    if len(operations) > MAX_OPERATIONS:
        raise ValueError("Too many fact operations in one answer.")
    result, catalog, seen = copy.deepcopy(state), sources(context, turns, documents), set()
    result["summary"] = delta["summary"].strip() or state.get("summary", "")
    result["focus"] = delta["focus"].strip() or state.get("focus", "")
    texts = {"context": " ".join(str(value) for value in context.values())}
    texts.update({turn["id"]: turn["text"] for turn in turns if turn["role"] == "user"})
    texts.update({doc["id"]: doc.get("text", "") for doc in documents or [] if doc["id"] in catalog})
    parked = list(dict.fromkeys([*state.get("parking_lot", []), *delta["parking_lot"]]))
    for item in delta.get("resolved_parking_lot", []):
        if item["text"] in parked and item["evidence_turns"] and all(
                catalog.get(ref, {}).get("authority") == "participant" for ref in item["evidence_turns"]):
            parked.remove(item["text"])
    result["parking_lot"] = parked
    tags = copy.deepcopy(result.get("tags", []))
    tag_seen = set()
    for operation in delta.get("tag_operations", []):
        if len(delta["tag_operations"]) > 128:
            raise ValueError("Too many taxonomy operations.")
        candidate = {key: operation[key] for key in gpfs_interview.TAG_FIELDS}
        if operation["op"] != "remove":
            gpfs_interview.ground_classification(candidate, turns, documents)
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
            tags.append({"id": records.new_id("tag"), **candidate,
                         "sources": {ref: copy.deepcopy(catalog[ref]) for ref in candidate["evidence_turns"]}})
    if len(tags) > 128:
        raise ValueError("Too many active taxonomy records.")
    result["tags"] = tags
    connections = {(item["relationship_type"], item["counterpart"].casefold(), item["condition"].casefold()): item
                   for item in result.get("connections_out", [])}
    for withdrawal in delta.get("remove_connections", []):
        for key, old in list(connections.items()):
            if withdrawal["target_id"] != old.get("id") or not withdrawal["evidence_turns"]:
                continue
            if all(catalog.get(ref, {}).get("authority") == "participant" for ref in withdrawal["evidence_turns"]) and any(
                    catalog[ref]["position"] > old.get("created_at_participant", -1) for ref in withdrawal["evidence_turns"]):
                del connections[key]
    for item in delta.get("connections_out", []):
        if not item["counterpart"].strip():
            continue
        gpfs_interview.validate_metadata({"connections_out": [item]}, catalog)
        key = item["relationship_type"], item["counterpart"].casefold(), item["condition"].casefold()
        merged = dict(connections.get(key, {}).get("sources", {}))
        merged.update({ref: copy.deepcopy(catalog[ref]) for ref in item["evidence_turns"]})
        before = connections.get(key, {})
        connections[key] = {**copy.deepcopy(item), "sources": merged, "evidence_turns": list(merged),
                            "id": before.get("id") or records.new_id("connection"),
                            "created_at_participant": before.get("created_at_participant", max(
                                (value["position"] for value in catalog.values() if value["authority"] == "participant"), default=-1))}
    # The same handoff described twice in other words is one link with both citations.
    connections = merge_equivalent_connections(list(connections.values()))
    if len(connections) > 100:
        raise ValueError("This interview has reached its external connection limit.")
    result["connections_out"] = connections
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
                    or not set(refs) <= set(catalog)):
                raise ValueError("An unchanged gap requires exact authorized evidence.")
            for fact in result["facts"]:
                if fact["id"] == row["target_id"]:
                    fact.pop("needs_reconciliation", None)
                    break
        matching = [operation for operation in operations if operation.get("target_id") == row["target_id"]]
        if (disposition == "unchanged" and matching or disposition != "unchanged" and
                (len(matching) != 1 or matching[0]["op"] != disposition)):
            raise ValueError("A reconciliation disposition must match its explicit fact operation.")
    existing = {fact["id"]: fact for fact in result["facts"] if fact["state"] == "active"}
    # Retire before adding, so adding a replacement and removing its predecessor
    # in the same transaction produces the same active facts in either order.
    for operation in sorted(operations, key=lambda item: item["op"] == "add"):
        op, target, topic = operation["op"], operation["target_id"], operation["topic"]
        if topic not in TOPICS or op not in ("add", "replace", "remove"):
            raise ValueError("Invalid fact operation.")
        # Validate the correction's authority too, even when it removes a fact.
        new = _new_fact(topic, operation["kind"], operation["text"], operation["evidence_turns"], catalog,
                        allow_empty=op == "remove", records=records)
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
            objective = _normalized_detail(str(context.get("objective", "")))
            if (topic == "purpose" and set(new["evidence_turns"]) == {"context"} and objective
                    and objective in _normalized_detail(new["text"])
                    and objective not in _normalized_detail(str(context.get("background", "")))):
                new.update(kind="gap", text=OBJECTIVE_GAP)
            _source_proof(new, operation.get("support", []), texts)
            # Exact duplicate additions do not grow the ledger on retries.
            duplicate = next((fact for fact in result["facts"] if fact["state"] == "active"
                              and fact["topic"] == topic and fact["kind"] == new["kind"]
                              and _normalized_detail(fact["text"]) == _normalized_detail(new["text"])), None)
            if duplicate:
                duplicate["sources"].update(new["sources"])
                duplicate["evidence_turns"] = list(duplicate["sources"])
            elif op == "replace":
                result["facts"].insert(result["facts"].index(old) + 1, new)
            else:
                result["facts"].append(new)
    # Two things one capture must not say at once: a purpose that is only the interview's
    # objective, and a link to another process that its own Connections note does not know.
    _settle_objective_as_purpose(result, context)
    _note_structured_connections(result, catalog, texts, records)
    if preserve_on_limit:
        # Keep the last supported version of an overflowing section while
        # publishing the other sections in this same accepted transaction.
        prior_by_topic = {key: [f for f in state["facts"] if f["topic"] == key] for key in TOPICS}
        active = [f for f in result["facts"] if f["state"] == "active"]
        counts = {key: sum(f["topic"] == key for f in active) for key in TOPICS}
        growth = {key: counts[key] - sum(f["state"] == "active" for f in prior_by_topic[key]) for key in TOPICS}
        overflow = {key for key in TOPICS if len("\n".join(f["text"] for f in active if f["topic"] == key)) > 12000}
        active_count = len(active) - sum(growth[key] for key in overflow)
        for key in sorted(TOPICS, key=lambda k: growth[k], reverse=True):
            if active_count <= MAX_ACTIVE_FACTS:
                break
            if key not in overflow and growth[key] > 0:
                overflow.add(key)
                active_count -= growth[key]
        if overflow:
            result["facts"] = [f for f in result["facts"] if f["topic"] not in overflow]
            for key in TOPICS:
                if key in overflow:
                    result["facts"].extend(copy.deepcopy(prior_by_topic[key]))
        old_limits = set(state.get("consolidation_required", []))
        edited = {op["topic"] for op in operations if op["op"] in ("replace", "remove")}
        result["consolidation_required"] = sorted(overflow | (old_limits - edited))
    for row in rows:
        key = row["key"]
        facts = [fact for fact in result["facts"] if fact["state"] == "active" and fact["topic"] == key]
        gaps = [fact for fact in facts if fact["kind"] == "gap"]
        status = row["status"]
        owner_candidate = status == "owner_followup"
        if owner_candidate:
            status = "partial"
        if key in result.get("consolidation_required", []):
            status = "partial"
        if not facts:
            status = "unknown"
        elif status == "unknown" or gaps:
            status = "partial"
        if status == "not_applicable" and not any(fact["kind"] == "not_applicable" and any(
                value["authority"] == "participant" for value in fact["sources"].values()) for fact in facts):
            status = "partial"
        participant_detail = any(fact["kind"] != "gap" and any(src["authority"] == "participant"
                                 for src in fact["sources"].values()) for fact in facts)
        if status in ("captured", "not_applicable") and any(
                all(src["authority"] == "document" for src in fact["sources"].values())
                for fact in facts):
            status = "partial"
        discussed = participant_detail or _gap_discussed(key, gaps, turns, documents)
        held = state["topics"][key].get("held_for_wording")
        result["topics"][key] = {"status": status, "discussed": bool(discussed),
            "participant_unavailable": bool(row["participant_unavailable"] and _unavailable(key, gaps, turns))}
        if (owner_candidate and participant_detail and gaps and key not in result.get("consolidation_required", [])
                and all(any(src["authority"] == "participant" for src in gap["sources"].values()) for gap in gaps)):
            result["topics"][key]["owner_review_candidate"] = True
        # The reason a topic was held stays with it while the held fact is unchanged, so a
        # lead that leaves the fact alone for a turn is not left without the note.
        if held and any(fact["id"] == held["fact_id"] for fact in facts):
            result["topics"][key]["held_for_wording"] = copy.deepcopy(held)
    return _refresh(result)


def _normalized_detail(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split()).rstrip(".!?")


def normalize_operations(delta, state, catalog):
    """Repair unambiguous labels locally and keep ambiguous changes as a topic to review."""
    operations = delta.get("fact_operations")
    if not isinstance(operations, list) or len(operations) > MAX_OPERATIONS:
        return []
    active = {fact["id"]: fact for fact in state["facts"] if fact["state"] == "active"}
    accepted, skipped, topics = [], set(), set()
    for row in operations:
        if not isinstance(row, dict):
            accepted.append(row)
            continue
        target, op, topic = row.get("target_id"), row.get("op"), row.get("topic")
        old = active.get(target) if isinstance(target, str) else None
        if op == "add" and isinstance(row.get("text"), str) and not row["text"].strip():
            if isinstance(topic, str) and topic in TOPICS:
                topics.add(topic)
            continue
        if old and topic != old["topic"]:
            if op == "remove":
                row["topic"] = old["topic"]
            elif op == "replace" and isinstance(topic, str) and topic in TOPICS:
                skipped.add(target)
                topics.update((topic, old["topic"]))
                continue
        refs = row.get("evidence_turns")
        if old and row.get("reason") in ("participant_correction", "withdrawal") and isinstance(refs, list) and refs and all(
                isinstance(ref, str) and ref in catalog for ref in refs) and any(catalog[ref]["authority"] == "participant" for ref in refs):
            if not any(catalog[ref]["authority"] == "participant" and catalog[ref]["position"] > old["created_at_participant"] for ref in refs):
                row["reason"] = "capture_correction"
        accepted.append(row)
    delta["fact_operations"] = accepted
    for row in delta.get("fact_reconciliations", []):
        if isinstance(row, dict) and isinstance(row.get("target_id"), str) and row["target_id"] in skipped:
            old = active[row["target_id"]]
            row.update(disposition="unchanged", basis="A proposed cross-topic correction needs clarification.",
                       evidence_turns=list(old["evidence_turns"]))
    return sorted(topics)


def findings(state):
    result = []
    for key in TOPICS:
        facts = [fact for fact in state["facts"] if fact["state"] == "active" and fact["topic"] == key]
        answer = "\n".join(fact["text"] for fact in facts)
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
                     'participant_unavailable': bool(state['topics'][key]['participant_unavailable']),
                     'evidence_turns': refs if discussed else []})
    return rows


def public_capture(state, delta, labels):
    return {"question": delta.get("question", ""), "summary": state.get("summary", delta["summary"]), "focus": state.get("focus", delta["focus"]),
            "parking_lot": state.get("parking_lot", delta["parking_lot"]), "memo_findings": findings(state),
            "coverage": [{"key": key, "label": labels[key], "status": "missing"} for key in TOPICS],
            "closure": {"asked": False, "confirmed": False}, "ready_for_draft": False,
            "taxonomy": [{k: copy.deepcopy(v) for k, v in item.items() if k not in ("id", "sources")} for item in state.get("tags", [])],
            "connections_out": [{k: copy.deepcopy(v) for k, v in item.items() if k not in ("sources", "id", "created_at_participant")} for item in state.get("connections_out", [])],
            "active_modules": delta.get("active_modules", []), "recap_due": delta.get("recap_due", "none")}


def _repaired_facts(active, kind, section, refs, topic, catalog, statement_evidence, records: RecordMetadataSource):
    """The repaired section (its statements, in order) as facts.

    A lead fact whose whole text the repair kept word for word, as consecutive
    statements, stays that same fact: its ID, citations and origin are untouched.
    Every other statement becomes a coverage_repair fact. This is an exact comparison,
    not an interpretation of the prose; a reworded statement is a new statement. A gap
    record is never kept, because a repaired section has no open gap.
    """
    placed = [None] * len(section)
    for fact in active:
        own = _sentences(fact["text"])
        if fact["kind"] != kind or not own:
            continue
        for start in range(len(section) - len(own) + 1):
            if section[start:start + len(own)] == own and not any(placed[start:start + len(own)]):
                placed[start:start + len(own)] = [fact] + [True] * (len(own) - 1)
                break
    return [item if isinstance(item, dict) else _new_fact(topic, kind, section[index],
                (statement_evidence or {}).get(section[index], refs), catalog, "coverage_repair", records=records)
            for index, item in enumerate(placed) if item is not True]


def sync_review(state, capture, context, turns, documents, *, records: RecordMetadataSource = _SYSTEM_RECORDS):
    """Persist explicit validated coverage repairs; never infer edits from prose."""
    state, catalog = copy.deepcopy(state), sources(context, turns, documents)
    # A repair the review proposed but did not apply (the process reviewer did not clear
    # the repaired text) changes nothing here: the lead's facts stay as they are.
    withdrawn = (capture.get("coverage_adjudication") or {}).get("withdrawn_repairs", [])
    for repair in capture.get("coverage_assessment", {}).get("capture_repairs", []):
        key = repair["key"]
        if key in withdrawn:
            continue
        finding = next(item for item in capture["memo_findings"] if item["key"] == key)
        if repair["answer"] != finding["answer"] or repair["evidence_turns"] != finding["evidence_turns"]:
            raise ValueError("Coverage repair and published answer disagree.")
        kind = "not_applicable" if finding["status"] == "not_applicable" else "detail"
        active = [fact for fact in state["facts"] if fact["topic"] == key and fact["state"] == "active"]
        repaired = _repaired_facts(active, kind, _sentences(repair["answer"]), repair["evidence_turns"], key, catalog,
                                   repair.get("statement_evidence"), records)
        kept = {id(fact) for fact in repaired}
        # Only the statements the repair changed or dropped are retired, and they stay
        # in the ledger as superseded_review. The kept facts move behind them so the
        # section reads in the order the review published.
        for fact in active:
            if id(fact) not in kept:
                fact["state"] = "superseded_review"
        state["facts"] = [fact for fact in state["facts"] if id(fact) not in kept] + repaired
    for finding in capture["memo_findings"]:
        topic = state["topics"][finding["key"]]
        proposed, topic["status"] = topic["status"], finding["status"]
        # The completion gate reads wording, so a proposed captured or not-applicable
        # topic can come back partial. Record which fact and which wording held it:
        # the lead then sees why, instead of having the same proposal reset every turn.
        # The note lasts while the topic is partial and a fact still reads that way: a lead
        # that leaves the fact alone and keeps the topic partial for a turn still sees it.
        # It goes when the fact is reworded or retired, or the topic passes the gate.
        previous = topic.pop("held_for_wording", None)
        if finding["status"] == "partial" and (previous or proposed in ("captured", "not_applicable")):
            active = [fact for fact in state["facts"] if fact["state"] == "active" and fact["topic"] == finding["key"]]
            if proposed not in ("captured", "not_applicable"):
                active = [fact for fact in active if fact["id"] == previous["fact_id"]]
            for fact in active:
                wording = uncertain_wording(fact["text"], fact["topic"])
                if wording:
                    topic["held_for_wording"] = {"fact_id": fact["id"], "wording": wording}
                    break
    return _refresh(state)


def source_binding(context, supporting) -> str:
    """Identify the input behind a capture, review ticket, or in-flight HTTP reply."""
    return _digest([context, supporting_identity(supporting)])


def supporting_identity(supporting):
    def canonical(value, key=""):
        if isinstance(value, dict):
            if key == "document":
                # The background reader adds interpretations as it works. The selected
                # passages, their text and the file's source revision identify the evidence.
                value = {name: item for name, item in value.items() if name not in ("observations", "questions")}
            elif key == "review":
                value = dict(value)
                value.pop("reviewed_chunks", None)
                if isinstance(value.get("limitations"), list):
                    # "Retained questions/observations/review notes reached ... limit" is about the
                    # reviewer's own notes, which are not part of the evidence either. It is written
                    # while the in-depth batches arrive, which now happens in seconds, while the
                    # notes and the map of the same files are still being written.
                    value["limitations"] = [item for item in value["limitations"]
                                            if not (isinstance(item, str) and item.startswith("Retained "))]
                if value.get("phase") in ("deep", "complete"):
                    # Finishing a normal review does not change the source. A stopped or
                    # failed review, changed extraction coverage or limitations still matter.
                    value.pop("phase")
                    value.pop("review_complete", None)
            return {name: canonical(item, name) for name, item in value.items()}
        if isinstance(value, list):
            result = [canonical(item, "document" if key == "documents" else "") for item in value]
            if key in ("documents", "pending_documents", "excerpts", "retained_evidence", "source_versions"):
                result.sort(key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False))
            return result
        return value
    if isinstance(supporting, dict):
        # Which earlier citations did not fit depends on the list a request asked
        # for, not on the evidence it was given. A replay asks for the capture's own
        # excerpts, so that count differs while files and excerpts are identical.
        # How many matches for the current wording were left unread depends on
        # that wording in the same way.
        supporting = {name: item for name, item in supporting.items()
                      if name not in ("omitted_prior_sources", "carried_sources", "omitted_query_matches")}
    return canonical(supporting)
