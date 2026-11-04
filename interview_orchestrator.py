"""One conversational lead, bounded specialists, and an application-owned exit gate."""
import copy
import hashlib
import json
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import agent_team
import capture_facts
from interview_coverage import finding_reports_unavailable_knowledge

REVIEW_ACKNOWLEDGEMENT = "Let me check that I have everything before we finish."
PARTIAL_REVIEW_ACKNOWLEDGEMENT = "Let me check what we have and keep the unanswered parts open."
MAX_REVIEW_TICKETS = 128
_PROVISIONAL_QUESTION = re.compile(r'\s*\{\s*"question"\s*:\s*"((?:[^"\\]|\\.)*)"')
_COMPLETION_SPEECH = re.compile(
    r"\b(?:this|the|our|your) (?:interview|conversation|account|capture|documentation) "
    r"(?:is|looks|seems|has been) (?:complete|completed|finished|done|ready)\b|"
    r"\b(?:we(?:['’]re| are)|you(?:['’]re| are)) (?:all set|done|finished)\b|"
    r"\b(?:no (?:further|more) questions|that(?:['’]s| is) all (?:I|we) need)\b|"
    r"\b(?:all|every) (?:(?:eleven|11|required) )?(?:topics|sections) (?:are|have been) (?:covered|captured|complete)\b|"
    r"\b(?:anything|something|what) (?:else |important |more )*(?:[^?!.]{0,160})"
    r"(?:haven['’]t|have not|not yet|not) (?:asked|captured|covered|discussed|mentioned)\b|"
    r"\b(?:anything|something|what) (?:else )?(?:[^?!.]{0,80})(?:we|I) (?:missed|have missed)\b|"
    r"\b(?:have|did) (?:we|I) miss(?:ed)? (?:anything|any (?:part|section|topic|detail))\b|"
    r"\b(?:does|would) (?:this|that|the account|the capture) (?:cover|capture|include) everything\b|"
    r"\b(?:any other|anything else|something else) (?:important )?(?:detail |information |point )?"
    r"(?:you (?:want|would like) to )?(?:add|share|mention)\b|"
    r"\bbefore (?:we|I) (?:conclude|finish|stop|pause|wrap up)"
    r"(?:\s*[?!.]|\s*$| (?:here|now|the interview|this interview|the conversation)\b)|"
    r"\bare we (?:finished|done) with (?:the |this |our )?(?:process review|interview|conversation|capture)\b|"
    r"\b(?:(?:shall|can|may|could|should) we|(?:do you want|would you like|are you ready) to) "
    r"(?:now )?(?:end|finish|stop|pause|wrap up|conclude)"
    r"(?: (?:the |this |our )?(?:interview|conversation|session)\b| (?:now|here)\b|(?=\s*[?!.]|$))",
    re.I)
FAST_CAPTURE_POLICY = """
This is the conversational capture pass. Stored capture is a server-validated aid,
not new evidence. Reuse its supported facts and topic progress instead of asking
the participant to repeat them. Correct it when the current answer changes facts.
Maintain accumulated facts across the full conversation: preserve stated actors,
conditions, normal branches, rework, ordered approvals and completion qualifiers.
A later answer supplements earlier facts unless it actually corrects them. Do not
replace a detailed section with only the most recent step or a broad stage label.
Passive requirements such as 'differences must be resolved' do not identify who
resolves them. Keep that actor unknown unless evidence names them; a reviewer is
not automatically the resolver, approver or accountable process owner.
Use each fact in its proper section: system/team names are not alternate names for
the process; normal situational branches belong in flow of work, and a stated
difference in equipment, available inputs or circumstances can also establish a
separate partial variation with the same exact source; known artifacts
make materials at least partial. Event-driven cadence is known even if numerical
frequency or deadline is unknown. Keep those distinct remaining gaps explicit.
Before asking, check whether the precise information was already supplied. Ask
only a distinct material gap instead of rewording an answered completion question.
For documents, retain specific supported controls and handoffs with documentary
attribution. Unconfirmed current practice does not justify discarding those details
or treating documentary instructions as participant testimony.
Ask one focused question. First address an important current ambiguity, correction,
or a second issue the participant volunteered. Otherwise prefer a genuinely untouched
topic over repeatedly drilling into a partial topic or an acknowledged unavailable detail.
Before changing subjects, follow the actual item/branch just described to its next
necessary transition: if the participant has edited an item or put it in an intermediate
folder but has not explained its onward handoff/release, ask what happens to that item
next. A folder label such as Ready is not evidence of review, release or acceptance.
This immediate reported-route gap outranks an untouched heading; do not substitute
a new trigger/purpose question or invent a hypothetical exception.
Do not mechanically march through headings or ask a bundled checklist question.
Mark a topic captured only when the full section can be explained from the participant's
evidence without guessing. Captured statuses are provisional until independent review.
For materials, an explained inventory, supplied references/locations, availability, and
honest review state can complete the interview section. A participant can explicitly say
the materials exist and are available but have not been attached or independently reviewed;
an upload or independent file verification is not a prerequisite for this section. Preserve
that unreviewed status, never imply the file was read, and do not treat its contents as
confirmed current practice. Missing inventory, availability or needed references remain gaps.
Never authorize completion or say goodbye. When you think all eleven sections are
understood, the application will acknowledge once and arrange the final review.
"""


class Coordinator:
    """Ephemeral run registry. Only fixed public execution metadata is exposed."""

    def __init__(self, client, api):
        self.client, self.api = client, api
        self._lock = threading.RLock()
        self._runs = {}
        self._document_runs = {}
        self._captures = {}
        self._tickets = {}
        self._family_generations = {}
        self._run_families = {}
        self._cancelled_runs = {}

    def _new_run(self, payload, context, turns, documents, *, roles=None, include_document_analyst=False, lead_model=None):
        requested_token = payload.get("agent_run_id")
        token = uuid.uuid4().hex if requested_token is None else requested_token
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{20,80}", token):
            raise ValueError("A valid agent run identifier is required.")
        ledger = agent_team.build_evidence_ledger(context, turns, documents)
        models = dict(self.client.agent_models)
        if lead_model is not None:
            models["lead_interviewer"] = lead_model
        run = agent_team.TeamRun(ledger, models=models,
                                include_document_analyst=include_document_analyst,
                                **({"roles": roles} if roles else {}))
        with self._lock:
            now = time.monotonic()
            self._cancelled_runs = {key: at for key, at in self._cancelled_runs.items() if now - at < 1800}
            if token in self._cancelled_runs:
                raise self.api.APIError("This request was cancelled before it started. No speech was released.", 409)
            self._runs = {key: entry for key, entry in self._runs.items() if now - entry[0] < 1800}
            if token in self._runs:
                raise ValueError("This agent run already exists; use a new identifier for an explicit retry.")
            if len(self._runs) >= 128:
                finished = next((key for key, entry in self._runs.items()
                                 if entry[1].public_status()["status"] in ("completed", "error", "blocked", "idle")), None)
                if finished is None:
                    raise ValueError("Too many agent runs are still processing.")
                del self._runs[finished]
            self._runs[token] = (now, run)
        return token, run

    def status(self, token, document_scope=None):
        if not isinstance(token, str):
            raise ValueError("Run identifier must be text.")
        with self._lock:
            entry = self._runs.get(token)
            document = self._document_runs.get(document_scope)
            ticket = next((value for value in self._tickets.values() if token in value["run_tokens"]), None)
            if ticket:
                entry = (ticket["at"], ticket["run"])
        if not entry:
            if document:
                return document.public_status()
            return {"run_id": token or "waiting", "status": "pending", "agents": [], "events": []}
        result = entry[1].public_status()
        # The capability used for polling is opaque and private to this request.
        result["run_id"] = token
        if ticket:
            result["active_run_id"] = ticket["token"]
            result["attempt"] = ticket["attempt"]
            for event in result["events"]:
                event["sequence"] += ticket["event_offset"]
        if document:
            status = document.public_status()
            if not any(row["role"] == "document_analyst" for row in result["agents"]):
                result["agents"].extend(status["agents"])
            result["document_activity"] = {"run_id": status["run_id"], "status": status["status"]}
        return result

    def cancel(self, token):
        if not isinstance(token, str):
            raise ValueError("Run identifier must be text.")
        with self._lock:
            entry = self._runs.get(token)
            remembered = bool(re.fullmatch(r"[A-Za-z0-9_-]{20,80}", token))
            if remembered:
                now = time.monotonic()
                self._cancelled_runs = {key: at for key, at in self._cancelled_runs.items() if now - at < 1800}
                if len(self._cancelled_runs) >= 256:
                    self._cancelled_runs.pop(next(iter(self._cancelled_runs)))
                self._cancelled_runs[token] = now
            if entry:
                entry[1].cancel()
            for ticket in self._tickets.values():
                if token in ticket["run_tokens"]:
                    ticket["valid"] = False
                    ticket["run"].cancel()
                    remembered = True
        return {"cancelled": bool(entry) or remembered}

    def analyze_document(self, context, record, chunks, phase, store):
        # Original files, chunk retrieval and permissions remain in DocumentStore.
        sources = [{"id": item["id"], "text": item.get("text") or "[Authorized visual source]"}
                   for item in chunks]
        _, run = self._new_run({}, {"phase": phase}, [], sources, roles=("document_analyst",))
        with self._lock:
            if len(self._document_runs) >= 64:
                self._document_runs.pop(next(iter(self._document_runs)))
            self._document_runs[record.get("_scope", "")] = run
        return run.run_role("document_analyst", lambda: self.client.analyze_document(
            context, record, chunks, phase, store, _agent_managed=True))

    def _coverage(self, run, capture, context, turns, supporting):
        box = {}

        def assess():
            findings, assessment = self.client.assess_coverage(
                capture["memo_findings"], context, turns, supporting,
                force=True, model_override=self.client.agent_models["coverage_reviewer"], allow_capture_repair=True,
                split=True)
            box["findings"] = findings
            if not assessment or assessment.get("review_available") is False:
                raise self.api.APIError("Coverage review did not finish. Your account is retained; retry the review.")
            return assessment

        assessment = run.run_role("coverage_reviewer", assess)
        return box["findings"], assessment

    def _process(self, run, capture, context, turns, supporting):
        return run.run_role("process_reviewer", lambda: self.client.structured(
            agent_team.PROCESS_REVIEW_INSTRUCTIONS,
            {"context": context, "turns": turns, "candidate_capture": capture,
             "supporting_documents": supporting}, agent_team.PROCESS_REVIEW_SCHEMA,
            "process_specialist_review", 8000, reasoning_effort="medium", request_timeout=90,
            model_override=self.client.agent_models["process_reviewer"]))

    def _review(self, run, capture, context, turns, supporting):
        # Both inspect the same immutable account; neither consumes the other's
        # opinion as evidence. Parallel calls reduce the participant's wait.
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="interview-review") as pool:
            coverage = pool.submit(self._coverage, run, copy.deepcopy(capture), context, turns, supporting)
            process = pool.submit(self._process, run, copy.deepcopy(capture), context, turns, supporting)
            failures = []
            try:
                findings, assessment = coverage.result()
                capture["memo_findings"], capture["coverage_assessment"] = findings, assessment
            except (self.api.APIError, ValueError, agent_team.TeamBlockedError):
                failures.append("coverage_reviewer")
                for item in capture["memo_findings"]:
                    if item["status"] in ("captured", "not_applicable"):
                        item["status"] = "partial"
                capture["coverage_assessment"] = {"all_topics_covered": False, "review_available": False,
                                                 "topics": [], "unconfirmed_topics": list(self.api.COVERAGE)}
            try:
                capture["process_review"] = process.result()
            except (self.api.APIError, ValueError, agent_team.TeamBlockedError):
                failures.append("process_reviewer")
                capture["process_review"] = {"no_material_blockers": False, "findings": [],
                                             "next_question": "", "review_available": False}
        return failures

    def _permit(self, run, capture, supporting):
        permit = agent_team.completion_permit(
            run, capture.get("coverage_assessment"), capture.get("process_review"),
            current_revision=run.ledger.revision,
            # Only _confirmed_capture may consume a reply to a server-issued
            # final check. Browser-supplied old final-check text is insufficient.
            final_confirmation=False,
            user_stopped=self.api.participant_requested_stop(run.ledger.snapshot["turns"]))
        documents_pending = bool(supporting.get("pending_documents")) or any(
            item.get("review", {}).get("phase") not in (None, "complete")
            for item in supporting.get("documents", []))
        if documents_pending:
            permit.update(allowed=False, ready_for_final_check=False, complete=False, partial=True)
            permit["blockers"].append("documents_pending")
        return permit

    def _publish(self, token, run, capture, supporting, *, verified=False):
        # The manager must not display every circle as complete while the
        # independent process review still requires someone to guess a route,
        # actor, handoff or output. Preserve the bound specialist assessment;
        # this conservative adjudication changes only the published memo status.
        process_review = capture.get("process_review", {})
        material = [item for item in process_review.get("findings", []) if item.get("material")]
        process_unavailable = process_review.get("review_available") is False
        if material or process_unavailable:
            lifecycle = next((item for item in capture["memo_findings"] if item["key"] == "lifecycle"), None)
            if lifecycle and lifecycle["status"] in ("captured", "not_applicable"):
                lifecycle["status"] = "partial"
            capture["coverage_adjudication"] = {
                "unconfirmed_topics": ["lifecycle"], "process_finding_ids": [item["id"] for item in material],
                "reason": ("Process review did not finish; practical process coverage remains unconfirmed."
                           if process_unavailable else "Material questions about the practical process remain unresolved."),
            }
        statuses = {"unknown": "missing", "partial": "partial", "captured": "covered", "not_applicable": "covered"}
        capture["coverage"] = [{"key": item["key"], "label": self.api.COVERAGE[item["key"]],
                                "status": (statuses[item["status"]] if verified or item["status"] == "unknown"
                                           else "partial")} for item in capture["memo_findings"]]
        capture["coverage_verified"] = verified
        capture["completion"] = self._permit(run, capture, supporting)
        capture["ready_for_draft"] = capture["completion"]["ready_for_final_check"]
        capture["agent_team"] = self.status(token)
        capture["agent_run_id"] = token
        return capture

    def _unavailable_only_topics(self, capture):
        """Permit a partial pause only for specifically evidenced unavailable gaps."""
        if "documents_pending" in capture.get("completion", {}).get("blockers", []):
            return []
        assessment = capture.get("coverage_assessment", {})
        process = capture.get("process_review", {})
        if assessment.get("review_available") is False or process.get("review_available") is False:
            return []
        open_keys = [item["key"] for item in capture["memo_findings"]
                     if item["status"] not in ("captured", "not_applicable")]
        topics = {item["key"]: item for item in assessment.get("topics", [])}
        unavailable_sources = set()
        if not open_keys:
            return []
        for key in open_keys:
            topic = topics.get(key, {})
            sources = set(topic.get("unavailable_evidence_turns", []))
            unresolved = [item for item in topic.get("dimensions", []) if item.get("status") == "unresolved"]
            # Neither an untouched topic nor a failed/missing dimension audit is
            # proof that the participant cannot answer. A blank process-review
            # question alone is also insufficient to establish unavailability.
            if (topic.get("participant_unavailable") is not True or not sources or not topic.get("gaps")
                    or topic.get("next_question", "").strip() or not unresolved
                    or any(not item.get("detail", "").strip() or not set(item.get("evidence_turns", [])) & sources
                           for item in unresolved)):
                return []
            unavailable_sources.update(sources)
        material = [item for item in process.get("findings", []) if item.get("material")]
        if process.get("next_question", "").strip() or (
                process.get("no_material_blockers") is not True and not material):
            return []
        if any(item.get("question", "").strip() or not set(item.get("evidence_turns", [])) & unavailable_sources
               for item in material):
            return []
        return open_keys

    @staticmethod
    def _source_binding(context, supporting):
        def canonical(value, key=""):
            if isinstance(value, dict):
                return {name: canonical(item, name) for name, item in value.items()}
            if isinstance(value, list):
                result = [canonical(item) for item in value]
                if key in ("documents", "pending_documents", "excerpts", "retained_evidence", "source_versions"):
                    result.sort(key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False))
                return result
            return value
        data = json.dumps([context, canonical(supporting)], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(data.encode()).hexdigest()

    def retrieval_basis(self, payload):
        """Freeze retrieval selection for non-evidentiary UI/confirmation turns.

        The HTTP owner must still hydrate the current authorized document scope.
        These saved IDs are retrieval preferences, never source authorization.
        """
        try:
            context, turns = self.api.validate_payload(payload)
        except (ValueError, TypeError):
            return None
        if any(payload.get(key) is not None and not isinstance(payload[key], str)
               for key in ("review_ticket", "capture_token")):
            return None
        with self._lock:
            entry = self._tickets.get(payload.get("review_ticket"))
            state = self._captures.get(payload.get("capture_token"))
            if (entry and entry["valid"] and time.monotonic() - entry["at"] < 1800
                    and context == entry["context"] and self._ticket_turns_match(entry, turns)):
                run = entry["run"]
            elif (state and state["valid"] and time.monotonic() - state["at"] < 1800
                    and context == state["context"] and turns[:len(state["turns"])] == state["turns"]):
                extra = turns[len(state["turns"]):]
                if extra and extra[0]["role"] == "assistant" and extra[0]["text"] == state["capture"].get("question"):
                    extra = extra[1:]
                if extra:
                    if (len(extra) != 1 or extra[0]["role"] != "user"
                            or (state["capture"].get("speech_authorization", {}).get("kind") != "final_check"
                                and not (state["capture"].get("speech_authorization", {}).get("kind") == "pause"
                                         and state["capture"].get("coverage_verified") is True
                                         and self._unavailable_only_topics(state["capture"])))):
                        return None
                    ledger = agent_team.build_evidence_ledger(context, turns, [])
                    if not (agent_team.explicit_final_confirmation(ledger) or agent_team.participant_has_more_to_add(ledger)
                            or re.fullmatch(r"\s*(?:thanks|thank you|okay|ok|understood)[.!]?\s*", extra[0]["text"], re.I)):
                        return None
                run = state["run"]
            else:
                return None
            if run.public_status()["cancelled"] or run.public_status()["stale"]:
                return None
            snapshot = run.ledger.snapshot
            return {"turns": snapshot["turns"], "preferred_source_ids": sorted(item["id"] for item in snapshot["documents"])}

    def _remember(self, capture, context, turns, supporting, token, run, ticket=None, fact_state=None):
        capability = uuid.uuid4().hex + uuid.uuid4().hex
        capture["capture_token"] = capability
        if fact_state is not None:
            capture['topic_discussion'] = capture_facts.discussion(fact_state)
        with self._lock:
            now = time.monotonic()
            family, generation = self._run_families[run.run_id]
            progress = run.public_status()
            if self._family_generations.get(family) != generation or progress["stale"] or progress["cancelled"]:
                raise self.api.APIError("A newer answer replaced this response. No speech was released.", 409)
            self._captures = {key: value for key, value in self._captures.items() if now - value["at"] < 1800}
            self._tickets = {key: value for key, value in self._tickets.items()
                             if value["running"] or now - value["at"] < 1800}
            if len(self._captures) >= 256:
                self._captures.pop(next(iter(self._captures)))
            self._captures[capability] = {"at": now, "binding": self._source_binding(context, supporting),
                "context": copy.deepcopy(context), "turns": copy.deepcopy(turns), "capture": copy.deepcopy(capture), "token": token,
                "run": run, "ticket": ticket, "valid": True, "family": family, "generation": generation,
                "fact_state": copy.deepcopy(fact_state)}
            active_aliases = set(self._runs) | {state["token"] for state in self._captures.values()}
            for entry in self._tickets.values():
                entry["run_tokens"].intersection_update(active_aliases | {entry["original_token"], entry["token"]})
            active_runs = ({entry[1].run_id for entry in self._runs.values()}
                           | {state["run"].run_id for state in self._captures.values()}
                           | {entry["run"].run_id for entry in self._tickets.values()})
            self._run_families = {key: value for key, value in self._run_families.items() if key in active_runs}
            families = {value[0] for value in self._run_families.values()}
            self._family_generations = {key: value for key, value in self._family_generations.items() if key in families}
        return capture

    def _reserve_review_ticket(self, now):
        """Caller holds the coordinator lock; in-flight reviews are never evicted."""
        self._tickets = {key: entry for key, entry in self._tickets.items()
                         if entry["running"] or now - entry["at"] < 1800}
        while len(self._tickets) >= MAX_REVIEW_TICKETS:
            oldest = next((key for key, entry in self._tickets.items() if not entry["running"]), None)
            if oldest is None:
                raise self.api.APIError("Completion reviews are already processing. Try again when one finishes.", 429)
            del self._tickets[oldest]

    def _claim_family(self, payload, run):
        """Overlapping answers sharing a capability cannot publish older tickets."""
        with self._lock:
            old = self._captures.get(payload.get("capture_token"))
            family = old["family"] if old else uuid.uuid4().hex
            generation = self._family_generations.get(family, 0) + 1
            self._family_generations[family] = generation
            prior_runs = {entry[1].run_id: entry[1] for entry in self._runs.values()}
            prior_runs.update({entry["run"].run_id: entry["run"] for entry in self._tickets.values()})
            prior_runs.update({state["run"].run_id: state["run"] for state in self._captures.values()})
            for prior_run in prior_runs.values():
                identity = self._run_families.get(prior_run.run_id)
                if identity and identity[0] == family:
                    prior_run.invalidate("newer-conversation-generation")
            self._run_families[run.run_id] = (family, generation)
            # Keep only identities still referenced by bounded run/capture caches.
            active = ({entry[1].run_id for entry in self._runs.values()}
                      | {state["run"].run_id for state in self._captures.values()}
                      | {entry["run"].run_id for entry in self._tickets.values()})
            self._run_families = {key: value for key, value in self._run_families.items() if key in active}
            families = {value[0] for value in self._run_families.values()}
            self._family_generations = {key: value for key, value in self._family_generations.items() if key in families}

    def _invalidate_capture(self, state):
        with self._lock:
            state["valid"] = False
            state["run"].invalidate("replaced-evidence")
            for ticket in self._tickets.values():
                if ticket["run"] is state["run"] or ticket is self._tickets.get(state.get("ticket")):
                    ticket["valid"] = False
                    ticket["run"].invalidate("replaced-evidence")

    def _prior_capture(self, payload, context, turns, supporting):
        if payload.get("capture_token") is not None and not isinstance(payload["capture_token"], str):
            raise ValueError("Capture token must be text.")
        with self._lock:
            state = self._captures.get(payload.get("capture_token"))
        if not state or not state["valid"] or time.monotonic() - state["at"] >= 1800:
            return None, None
        if state["run"].public_status()["cancelled"] or state["run"].public_status()["stale"]:
            return None, None
        base = state["turns"]
        if (state["binding"] != self._source_binding(context, supporting)
                or turns[:len(base)] != base):
            self._invalidate_capture(state)
            return None, None
        extra = turns[len(base):]
        if extra and extra[0]["role"] == "assistant":
            if extra[0]["text"] != state["capture"].get("question"):
                self._invalidate_capture(state)
                return None, None
            extra = extra[1:]
        return state, extra

    def _fact_record(self, payload, context, turns):
        """Find a private published account; this grants no review authority."""
        capability = payload.get("capture_token")
        if not isinstance(capability, str):
            return None
        with self._lock:
            state = self._captures.get(capability)
            if not state or time.monotonic() - state["at"] >= 1800:
                return None
            # A cancelled/failed generation invalidates completion authority,
            # not the previously published source-backed facts. Prefer the most
            # recent published record in this family; an edited/older transcript
            # must rebuild rather than silently resurrect an earlier account.
            family = state["family"]
            # Registry insertion order breaks same-generation ties: Windows'
            # monotonic clock may give the initial capture and review the same
            # timestamp, but the later review must retain its repaired facts.
            state = max(((index, item) for index, item in enumerate(self._captures.values())
                         if item["family"] == family and time.monotonic() - item["at"] < 1800),
                        key=lambda pair: (pair[1]["generation"], pair[0]))[1]
            # A changed context (for example the working map naming the process)
            # does not discard participant-cited facts: rebase retires only the
            # facts that cite the context itself. The transcript must still match.
            if turns[:len(state["turns"])] != state["turns"]:
                return None
            # The assistant line after a capture may be the lead's own question or,
            # in live voice, the spoken interviewer's caption. Facts cite participant
            # turns, which rebase re-checks, so either keeps the ledger.
            return state

    def fact_source_ids(self, payload):
        """Private retrieval preferences, never authorization or source content."""
        try:
            context, turns = self.api.validate_payload(payload)
        except (ValueError, TypeError):
            return []
        state = self._fact_record(payload, context, turns)
        if not state or not state.get("fact_state"):
            return []
        return sorted({ref for fact in state["fact_state"]["facts"] if fact["state"] == "active"
                       for ref, source in fact["sources"].items() if source["authority"] == "document"})

    def _fact_base(self, payload, context, turns, evidence, supporting=None):
        """Reuse private facts; selection omission must not erase source claims."""
        state = self._fact_record(payload, context, turns)
        ledger = copy.deepcopy(state.get("fact_state")) if state else None
        if ledger is None:
            # Pre-ledger prose can mix facts and superseded gaps. Rebuild from
            # full sources, never import derived prose as factual authority.
            return capture_facts.empty_state()
        _, active_versions = capture_facts.document_versions(supporting or {}, evidence)
        if active_versions is not None:
            previous_sources = {item["id"]: item for item in state["run"].ledger.snapshot["documents"]}
            current_ids = {item["id"] for item in evidence if not item.get("retained_only") and not item.get("provenance_only")}
            for fact in ledger["facts"]:
                if fact["state"] != "active":
                    continue
                for ref, source in fact["sources"].items():
                    document = previous_sources.get(ref, {}).get("document_id")
                    old_revision = ledger.get("seeded_document_versions", {}).get(document)
                    if (source["authority"] == "document" and old_revision
                            and active_versions.get(document) != old_revision):
                        fact["state"] = "retired_source"
                        ledger["topics"][fact["topic"]].update(status="partial", participant_unavailable=False)
                        break
                    if (source["authority"] == "document" and ref not in current_ids and old_revision
                            and active_versions.get(document) == old_revision):
                        raise self.api.APIError("A referenced excerpt from an unchanged file could not fit in this response. "
                                                "Your account is retained; retry with the referenced files available.", 409)
        return capture_facts.rebase(ledger, context, turns, evidence)

    def _confirmed_capture(self, state, extra, context, turns, supporting):
        prior = state["capture"]
        if (prior.get("speech_authorization", {}).get("kind") == "pause"
                and prior.get("coverage_verified") is True and self._unavailable_only_topics(prior)
                and len(extra) == 1 and extra[0]["role"] == "user" and len(turns) == len(state["turns"]) + 2
                and re.fullmatch(r"\s*(?:thanks|thank you|okay|ok|understood)[.!]?\s*", extra[0]["text"], re.I)):
            capture = copy.deepcopy(prior)
            capture["no_new_run"] = True
            return self._remember(capture, context, turns, supporting, state["token"], state["run"], state.get("ticket"), state.get("fact_state"))
        if (prior.get("speech_authorization", {}).get("kind") != "final_check"
                or len(extra) != 1 or extra[0]["role"] != "user"
                or len(turns) != len(state["turns"]) + 2
                or not self._permit(state["run"], prior, supporting)["ready_for_final_check"]):
            return None
        ledger = agent_team.build_evidence_ledger(context, turns, state["run"].ledger.snapshot["documents"])
        confirmed = agent_team.explicit_final_confirmation(ledger)
        more = agent_team.participant_has_more_to_add(ledger)
        courtesy = bool(re.fullmatch(r"\s*(?:thanks|thank you|okay|ok)[.!]?\s*", extra[0]["text"], re.I))
        if not confirmed and not more and not courtesy:
            return None
        capture = copy.deepcopy(prior)
        capture["no_new_run"] = True
        capture.pop("review_ticket", None)
        if not confirmed:
            question = "What should we add to the account?" if more else prior["question"]
            capture.update(question=question, closure={"asked": not more, "confirmed": False})
            capture["completion"].update(allowed=False, complete=False, partial=True,
                participant_confirmed=False, ready_for_final_check=not more, revision=ledger.revision,
                blockers=["participant_has_more_to_add" if more else "confirmation_pending"])
            capture["ready_for_draft"] = not more
            capture["speech_authorization"] = {"approved": True, "kind": "question" if more else "final_check",
                "text": question, "revision": ledger.revision, "completion_allowed": False}
            return self._remember(capture, context, turns, supporting, state["token"], state["run"], state.get("ticket"), state.get("fact_state"))
        question = "Thank you. All eleven sections are captured and you have confirmed the account. It is ready for process-owner review."
        capture.update(question=question, closure={"asked": True, "confirmed": True}, ready_for_draft=True)
        capture["completion"].update(allowed=True, complete=True, partial=False, participant_confirmed=True,
                                     ready_for_final_check=True, blockers=[], revision=ledger.revision,
                                     review_revision=state["run"].ledger.revision)
        capture["speech_authorization"] = {"approved": True, "kind": "complete", "text": question,
                                           "revision": ledger.revision, "completion_allowed": True}
        return self._remember(capture, context, turns, supporting, state["token"], state["run"], fact_state=state.get("fact_state"))

    @staticmethod
    def _prior_context(previous):
        """The prior capture as lead context: its gaps and questions, not the full reviews.

        A completion review can run to 14k tokens. Re-sending it on every later
        turn slows the lead without adding evidence; the open gaps, reviewer
        questions and material findings are what the next question needs.
        """
        context = {key: copy.deepcopy(previous[key]) for key in ("summary", "focus", "parking_lot") if key in previous}
        assessment = previous.get("coverage_assessment")
        if isinstance(assessment, dict):
            context["coverage_assessment"] = {
                "review_available": assessment.get("review_available", True),
                "all_topics_covered": assessment.get("all_topics_covered", False),
                "topics": [{key: copy.deepcopy(topic.get(key)) for key in
                            ("key", "complete", "gaps", "next_question", "participant_unavailable")}
                           for topic in assessment.get("topics", []) if isinstance(topic, dict)]}
        review = previous.get("process_review")
        if isinstance(review, dict):
            context["process_review"] = {
                "review_available": review.get("review_available", True),
                "no_material_blockers": review.get("no_material_blockers", False),
                "next_question": review.get("next_question", ""),
                "findings": [{key: copy.deepcopy(finding.get(key)) for key in ("id", "kind", "material", "detail", "question")}
                             for finding in review.get("findings", []) if isinstance(finding, dict)]}
        return context

    def _usable_question(self, value):
        return (isinstance(value, str) and 0 < len(value) <= 1600 and value.count("?") == 1
                and value.rstrip().endswith("?") and not self.api.WRAP_UP_LANGUAGE.search(value)
                and not _COMPLETION_SPEECH.search(value))

    def _authorize(self, capture, run, question, kind):
        if kind == "question":
            if not self._usable_question(question):
                question = self.api.next_uncovered_question(capture)
            if not self._usable_question(question):
                question = "What can you clarify about the remaining open part of this process?"
        capture["question"] = question
        capture["speech_authorization"] = {"approved": True, "kind": kind, "text": question,
            "revision": run.ledger.revision, "completion_allowed": capture["completion"]["complete"]}

    def interview(self, payload):
        api = self.api
        context, turns = api.validate_payload(payload)
        supporting = payload.get("_supporting_documents", {})
        evidence = api.document_evidence_catalog(supporting)
        action = payload.get("action", "answer")
        if action not in ("start", "answer", "skip", "close", "document_followup"):
            raise ValueError("Unsupported interview action.")
        fact_state = self._fact_base(payload, context, turns, evidence, supporting)
        selected_document_versions, active_document_versions = capture_facts.document_versions(supporting, evidence)
        fact_state = capture_facts.reconcile_document_versions(fact_state, active_document_versions)
        prior, extension = self._prior_capture(payload, context, turns, supporting)
        if prior and not api.participant_requested_stop(turns):
            confirmed = self._confirmed_capture(prior, extension, context, turns, supporting)
            if confirmed:
                return confirmed
            if not extension and action == "answer":
                cached = copy.deepcopy(prior["capture"])
                cached["no_new_run"] = True
                return cached
        if prior:
            self._invalidate_capture(prior)
        active_facts = [fact for fact in fact_state["facts"] if fact["state"] == "active"]
        has_noncontext_facts = any(any(source["authority"] != "context" for source in fact["sources"].values())
                                   for fact in active_facts)
        large_rebuild = not has_noncontext_facts and sum(len(turn["text"]) for turn in turns) >= 6000
        new_document_baseline = any(fact_state.get("seeded_document_versions", {}).get(identity) != revision
                                    for identity, revision in selected_document_versions.items())
        baseline_seed = new_document_baseline or large_rebuild
        # Only open claims the latest answer could affect need explicit reconciliation
        # (and the stronger reconciliation model); untouched gaps keep their wording.
        focus = capture_facts.turn_focus(turns)
        model_role = ("document_analyst" if baseline_seed else "process_reviewer"
                      if capture_facts.reconciliation_targets(fact_state, focus) else "lead_interviewer")
        lead_model = self.client.agent_models[model_role]
        token, run = self._new_run(payload, context, turns, evidence, lead_model=lead_model)
        self._claim_family(payload, run)
        if api.participant_requested_stop(turns):
            run.cancel()
            question = "Of course. We can stop here. Your account is retained, with any unfinished sections still open."
            return {"question": question, "preserve_capture": True, "ready_for_draft": False,
                    "closure": {"asked": False, "confirmed": False},
                    "completion": {"allowed": False, "complete": False, "partial": True,
                                   "ready_for_final_check": False, "blockers": ["participant_stopped"]},
                    "agent_team": self.status(token), "agent_run_id": token,
                    "speech_authorization": {"approved": True, "kind": "pause", "text": question,
                                             "revision": run.ledger.revision, "completion_allowed": False}}
        if (action == "start" and not any(turn["role"] == "user" and not turn.get("document_event") for turn in turns)
                and not evidence and not supporting.get("documents") and not supporting.get("pending_documents")):
            # No process facts exist to review yet. Ask a deterministic opening
            # and leave every specialist pending rather than spending model calls
            # or pretending that a review has taken place.
            name = context.get("process_name", "").strip()
            question = f"Let's walk through {name}. What starts this work?" if name else "What work would you like to walk through?"
            findings = [{"key": key, "status": "unknown", "answer": "UNKNOWN", "evidence_turns": []}
                        for key in api.COVERAGE]
            if name:
                findings[0].update(status="partial", answer=name, evidence_turns=["context"])
            capture = {"question": question, "summary": "", "ready_for_draft": False,
                       "focus": "Understand the actual starting point", "parking_lot": [],
                       "closure": {"asked": False, "confirmed": False}, "memo_findings": findings,
                       "coverage": [{"key": key, "label": label, "status": "missing"} for key, label in api.COVERAGE.items()]}
            api.validate_interview(capture, turns, evidence)
            run.standby()
            self._publish(token, run, capture, supporting)
            capture["speech_authorization"] = {"approved": True, "kind": "question", "text": question,
                                               "revision": run.ledger.revision, "completion_allowed": False}
            fact_state = capture_facts.seed_legacy(capture, context, turns, evidence)
            return self._remember(capture, context, turns, supporting, token, run, fact_state=fact_state)
        extra = {}
        if prior:
            extra["previous_capture"] = self._prior_context(prior["capture"])
        extra["fact_state"] = capture_facts.model_state(fact_state, focus)
        extra["untouched_topics"] = [key for key, state in fact_state["topics"].items() if not state["discussed"]]
        if action == "document_followup":
            if payload.get("previous_capture") is None or supporting.get("pending_documents") or any(
                    doc.get("review", {}).get("phase") != "complete" for doc in supporting.get("documents", [])):
                raise ValueError("Finish reviewing the active files before asking a document follow-up.")
            # Browser captures may provide graph display context only; their
            # topic statuses and closure claims never seed interview progress.
            if not prior:
                extra["document_followup_requested"] = True
        def observe(text):
            # The question is the first streamed field. Publish it for display as
            # soon as it is complete and passes the same checks as a final question;
            # the capture itself is applied only after the whole response validates.
            match = _PROVISIONAL_QUESTION.match(text)
            if not match:
                return False
            try:
                question = json.loads('"' + match.group(1) + '"')
            except ValueError:
                return True
            if self._usable_question(question):
                run.set_provisional_question(question)
            return True

        def initial_capture():
            nonlocal fact_state
            request_schema = capture_facts.schema_for(fact_state, capture_facts.sources(context, turns, evidence), focus)
            transaction = self.client.structured(
            api.FACT_INTERVIEW_INSTRUCTIONS + api.foundation_instructions() + FAST_CAPTURE_POLICY +
            (api.DOCUMENT_FOLLOWUP_INSTRUCTIONS if action == "document_followup" else "") + capture_facts.FACT_CAPTURE_POLICY,
            {"context": context, "turns": turns, "action": action,
             "supporting_documents": supporting, **extra}, request_schema,
            "team_interview_capture", 12000 if baseline_seed or (not extra["fact_state"]["facts"]
                and (evidence or len(turns) > 12 or sum(len(turn["text"]) for turn in turns) >= 6000))
                else 6500, reasoning_effort="low",
            model_override=lead_model, on_text=observe)
            api.check_schema(transaction, request_schema)
            fact_state = capture_facts.apply_delta(fact_state, transaction, context, turns, evidence, focus)
            capture = capture_facts.public_capture(fact_state, transaction, api.COVERAGE)
            if not capture["question"].strip():
                capture["question"] = api.next_uncovered_question(capture)
            capture = api.validate_interview(capture, turns, evidence)
            fact_state = capture_facts.sync_review(fact_state, capture, context, turns, evidence)
            fact_state = capture_facts.reconcile_document_versions(fact_state, active_document_versions,
                selected_document_versions if baseline_seed else None)
            return capture
        capture = run.run_role("lead_interviewer", initial_capture)
        if run.public_status()["cancelled"] or run.public_status()["stale"]:
            raise api.APIError("This response was cancelled or replaced. No speech was released.", 409)
        documents_pending = bool(supporting.get("pending_documents")) or any(
            item.get("review", {}).get("phase") not in (None, "complete") for item in supporting.get("documents", []))
        candidate_full = (action != "document_followup" and not documents_pending
                          and api.memo_has_enough_detail(capture["memo_findings"]))
        open_findings = [item for item in capture["memo_findings"] if item["status"] not in ("captured", "not_applicable")]
        candidate_partial = (action != "document_followup" and not documents_pending and bool(open_findings)
                             and all(fact_state["topics"][item["key"]]["discussed"]
                                     and fact_state["topics"][item["key"]]["participant_unavailable"] for item in open_findings)
                             and all(finding_reports_unavailable_knowledge(item, turns) for item in open_findings))
        if not (candidate_full or candidate_partial):
            run.defer_roles(("coverage_reviewer", "process_reviewer"))
        self._publish(token, run, capture, supporting)
        capture["closure"] = {"asked": False, "confirmed": False}
        ticket_id = None
        if candidate_full or candidate_partial:
            ticket_id = uuid.uuid4().hex + uuid.uuid4().hex
            acknowledgement = PARTIAL_REVIEW_ACKNOWLEDGEMENT if candidate_partial else REVIEW_ACKNOWLEDGEMENT
            self._authorize(capture, run, acknowledgement, "review_pending")
            capture["review_purpose"] = "partial" if candidate_partial else "completion"
            capture["review_ticket"] = ticket_id
            with self._lock:
                self._reserve_review_ticket(time.monotonic())
                self._tickets[ticket_id] = {"at": time.monotonic(), "valid": True, "running": False,
                    "event": threading.Event(), "response": None, "failed": False,
                    "run": run, "token": token, "context": copy.deepcopy(context), "turns": copy.deepcopy(turns),
                    "run_tokens": {token}, "original_token": token, "attempt": 1, "event_offset": 0,
                    "supporting": copy.deepcopy(supporting), "capture": copy.deepcopy(capture),
                    "fact_state": copy.deepcopy(fact_state),
                    "binding": self._source_binding(context, supporting), "failure_messages": []}
        else:
            question = capture["question"]
            if (api.WRAP_UP_LANGUAGE.search(question) or not question.rstrip().endswith("?")
                    or action == "close"):
                question = ("How does the supplied document compare with what you actually do?"
                            if action == "document_followup" else api.next_uncovered_question(capture))
            if not question.rstrip().endswith("?"):
                question = "What can you clarify about the remaining open part of this process?"
            self._authorize(capture, run, question, "question")
        if evidence:
            capture["document_evidence"] = evidence
        return self._remember(capture, context, turns, supporting, token, run, ticket_id, fact_state)

    def _ticket_matches(self, entry, context, turns, supporting):
        if entry["binding"] != self._source_binding(context, supporting):
            return False
        return self._ticket_turns_match(entry, turns)

    @staticmethod
    def _ticket_turns_match(entry, turns):
        base = entry["turns"]
        if turns[:len(base)] != base:
            return False
        extra = turns[len(base):]
        allowed = [entry["capture"]["question"]] + entry["failure_messages"]
        # Displayed acknowledgements/failure notices are known assistant text,
        # not new process evidence. No participant addition may enter a ticket.
        return (len(extra) <= len(allowed) and all(turn["role"] == "assistant" and turn["text"] == text
                for turn, text in zip(extra, allowed)))

    def review(self, payload):
        api = self.api
        context, turns = api.validate_payload(payload)
        supporting = payload.get("_supporting_documents", {})
        ticket_id = payload.get("review_ticket")
        retry = payload.get("retry_review", False)
        if (not isinstance(ticket_id, str) or not isinstance(retry, bool)
                or payload.get("capture_token") is not None and not isinstance(payload["capture_token"], str)):
            raise ValueError("A review ticket and explicit retry choice are required.")
        with self._lock:
            entry = self._tickets.get(ticket_id)
            if not entry or not entry["valid"] or time.monotonic() - entry["at"] >= 1800:
                raise api.APIError("This review has expired or was replaced. Continue the interview to refresh it.", 409)
            progress = entry["run"].public_status()
            if progress["cancelled"] or progress["stale"]:
                raise api.APIError("This review was cancelled or replaced. No speech was released.", 409)
            if payload.get("capture_token"):
                state = self._captures.get(payload["capture_token"])
                if not state or not state["valid"] or state.get("ticket") != ticket_id:
                    raise api.APIError("This capture does not belong to the prepared review.", 409)
            if not self._ticket_matches(entry, context, turns, supporting):
                entry["valid"] = False
                entry["run"].invalidate("replaced-evidence")
                raise api.APIError("The account changed after this review was prepared. Continue the interview first.", 409)
            waiting = entry["running"]
            if not waiting and entry["response"] is not None and not (retry and entry["failed"]):
                return copy.deepcopy(entry["response"])
            if not waiting:
                if retry and entry["failed"]:
                    old_run = entry["run"]
                    token, run = self._new_run({}, entry["context"], entry["turns"], old_run.ledger.snapshot["documents"])
                    run.reuse_lead_result(old_run)
                    self._run_families[run.run_id] = self._run_families[old_run.run_id]
                    entry["run_tokens"].add(token)
                    entry["attempt"] += 1
                    entry["event_offset"] += len(old_run.public_status()["events"])
                    entry.update(token=token, run=run, response=None)
                entry["running"] = True
                entry["event"].clear()
            event = entry["event"]
        if waiting:
            if not event.wait(250):
                raise api.APIError("The review is still processing. Retry the same review ticket.", 409)
            with self._lock:
                if not entry["valid"] or entry["response"] is None:
                    raise api.APIError("This review was cancelled or replaced. No speech was released.", 409)
                return copy.deepcopy(entry["response"])
        run, token = entry["run"], entry["token"]
        try:
            capture = copy.deepcopy(entry["capture"])
            failures = self._review(run, capture, entry["context"], entry["turns"], entry["supporting"])
            if not entry["valid"] or run.public_status()["cancelled"] or run.public_status()["stale"]:
                raise api.APIError("This review was cancelled or replaced. No speech was released.", 409)
            self._publish(token, run, capture, supporting, verified=not failures)
            capture["closure"] = {"asked": False, "confirmed": False}
            if failures:
                question = "Your account is retained. The review could not finish; you can retry it when you are ready."
                kind = "pause"
                capture.update(review_retry_required=True, review_ticket=ticket_id)
            elif capture["completion"]["ready_for_final_check"]:
                question = api.FINAL_CHECK_PREFIX + " someone doing this work needs to know that we haven't captured?"
                kind = "final_check"
                capture["closure"]["asked"] = True
            elif unavailable_topics := self._unavailable_only_topics(capture):
                question = ("The remaining sections need information you do not have here: " +
                            "; ".join(api.COVERAGE[key] for key in unavailable_topics) +
                            ". We can keep this as a partial capture for follow-up.")
                kind = "pause"
            else:
                process = capture.get("process_review", {})
                question = process.get("next_question", "").strip()
                if not question:
                    question = next((item.get("next_question", "").strip()
                        for item in capture.get("coverage_assessment", {}).get("topics", [])
                        if not item.get("complete") and not item.get("participant_unavailable")
                        and item.get("next_question", "").strip()), "")
                if not question or api.WRAP_UP_LANGUAGE.search(question):
                    question = api.next_uncovered_question(capture)
                if not question.rstrip().endswith("?") or api.WRAP_UP_LANGUAGE.search(question):
                    question = "What can you clarify about the remaining open part of this process?"
                kind = "question"
            if not failures:
                capture.pop("review_ticket", None)
            self._authorize(capture, run, question, kind)
            if run.ledger.snapshot["documents"]:
                capture["document_evidence"] = run.ledger.snapshot["documents"]
            fact_state = entry.get("fact_state")
            if fact_state is not None:
                fact_state = capture_facts.sync_review(fact_state, capture, context, turns,
                                                     run.ledger.snapshot["documents"])
            self._remember(capture, context, turns, supporting, token, run, ticket_id, fact_state)
            with self._lock:
                if not entry["valid"] or run.public_status()["cancelled"] or run.public_status()["stale"]:
                    raise api.APIError("This review was cancelled or replaced. No speech was released.", 409)
                entry.update(response=copy.deepcopy(capture), failed=bool(failures))
                if failures:
                    entry["failure_messages"].append(question)
            return capture
        finally:
            with self._lock:
                entry["running"] = False
                event.set()

    def advisory_coverage(self, payload):
        """Check the provisional topics of the current capture in the background.

        The result is display-only: it never changes the private ledger, the
        published capture or the completion permit, which still require the full
        completion review bound to the actual run. Each check is one coverage call
        limited to the topics the lead marked captured or not applicable.
        """
        api = self.api
        context, turns = api.validate_payload(payload)
        supporting = payload.get("_supporting_documents", {})
        state = self._fact_record(payload, context, turns)
        if not state:
            raise api.APIError("No current capture is available to check. Continue the interview first.", 409)
        capture = state["capture"]
        extra = turns[len(state["turns"]):]
        if extra and not (len(extra) == 1 and extra[0]["role"] == "assistant"
                          and extra[0]["text"] == capture.get("question")):
            raise api.APIError("The account changed since this capture; the next answer refreshes it.", 409)
        findings = copy.deepcopy(capture.get("memo_findings", []))
        keys = [item["key"] for item in findings if item["status"] in ("captured", "not_applicable")]
        revision = state["run"].ledger.revision
        if not keys:
            return {"advisory": True, "revision": revision, "topics": [], "answers": {}}
        _, assessment = self.client.assess_coverage(
            findings, context, state["turns"], supporting, force=True,
            model_override=self.client.agent_models["coverage_reviewer"], topics=keys)
        if not assessment or assessment.get("review_available") is False:
            raise api.APIError("The advisory check did not finish. Captured topics stay provisional.")
        return {"advisory": True, "revision": revision,
                "topics": [{"key": topic["key"], "complete": topic["complete"], "gaps": topic["gaps"][:6],
                            "next_question": topic["next_question"]} for topic in assessment["topics"]],
                "answers": {item["key"]: item["answer"] for item in findings if item["key"] in keys}}

    def workflow(self, payload):
        api = self.api
        supporting = payload.get("_supporting_documents", {})
        evidence = api.document_evidence_catalog(supporting)
        context, turns = api.validate_payload(payload, require_answers=not bool(evidence))
        lead_model = self.client.agent_models["process_reviewer"]
        token, run = self._new_run(payload, context, turns, evidence, include_document_analyst=bool(evidence),
                                  lead_model=lead_model)
        previous = api.workflow_previous_capture(payload.get("previous_capture"), turns, evidence)
        def initial_workflow():
            update = self.client.structured(
                api.WORKFLOW_INSTRUCTIONS,
                {"context": context, "turns": turns, "previous_capture": previous, "supporting_documents": supporting},
                api.WORKFLOW_UPDATE_SCHEMA, "team_working_process_map", 22000 if evidence else 12000,
                reasoning_effort="medium", request_timeout=120,
                model_override=lead_model)
            # Validate within the role's execution boundary. Invalid graph/source
            # output must report an error rather than a completed lead review.
            capture = api.apply_workflow_update(copy.deepcopy(update), previous, turns, evidence)
            return {"update": update, "capture": capture}
        proposed = run.run_role("lead_interviewer", initial_workflow)
        update, capture = proposed["update"], proposed["capture"]
        def audited_workflow():
            audit = self.client.structured(api.WORKFLOW_AUDIT_INSTRUCTIONS,
                {"context": context, "turns": turns, "previous_capture": previous,
                 "supporting_documents": supporting, "candidate_update": update},
                api.WORKFLOW_AUDIT_SCHEMA, "team_working_map_source_audit", 24000 if evidence else 12000,
                reasoning_effort="medium", request_timeout=240 if evidence else 120,
                model_override=self.client.agent_models["document_analyst"] if evidence else lead_model)
            audited = api.apply_workflow_audit(update, audit, previous)
            return api.apply_workflow_update(audited, previous, turns, evidence)
        # Transcript-only maps need the same source check as documentary maps.
        # This stays in the bounded background worker, never the question path.
        # The lead's existing two-call budget covers generation plus source audit.
        capture = run.run_role("document_analyst" if evidence else "lead_interviewer", audited_workflow)
        run.defer_roles(("coverage_reviewer", "process_reviewer"))
        if run.public_status()["cancelled"] or run.public_status()["stale"]:
            raise api.APIError("This workflow response was cancelled or replaced. The existing map is unchanged.", 409)
        self._publish(token, run, capture, supporting)
        if evidence:
            capture["document_evidence"] = evidence
        return capture
