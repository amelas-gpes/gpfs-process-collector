"""Shared GPFS discovery policy and evidence-bound classification contracts.

Vocabulary guides questions; it never establishes a client's practice or an
approved GPFS standard. No provider, filesystem or runtime work occurs here.
"""
import copy
from collections import Counter, defaultdict
import hashlib
import re
import unicodedata


STEP_DETAIL_FIELDS = ("duration", "deadline", "frequency", "responsible", "accountable", "consulted", "informed", "system", "control", "exception")

# Words that cannot identify which part of a process a question concerns.
_GENERAL = set("""about after again already also another asked before could detail determine
does each else from goes happen happens have into know more next other precisely process
question really reported second should someone something specific stated step team tell
that their them then there these they this through unknown what when where whether which
while with work would your""".split())
_MATERIAL = re.compile(r"\b(approv\w*|sign.off|releas\w*|hold|blocks?|resum\w*|reject\w*|handoff|criteria|criterion|threshold|replace[sd]?)\b", re.I)
_CORRECTION = re.compile(r"\b(actually|correction|instead|no longer|i meant|scratch that|used to|not anymore)\b", re.I)
_PARKED = re.compile(r"\b(?:I|we) (?:do(?:n't| not) know|(?:am|are) not sure|cannot (?:say|answer))\b|\bI['’]m not sure\b", re.I)


def memory_terms(text):
    words = re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", text).casefold())
    return {w.rstrip("s") for w in words if len(w) >= 4 and w not in _GENERAL}


def grounded_sequence(claim, evidence):
    """Keep a common predecessor without turning a list of its outcomes into a sequence."""
    explicit = re.compile(r",?\s+in (?:that|this) order(?=[.!?]?(?:\s|$))", re.I)
    if not explicit.search(claim):
        return claim
    evidence = tuple(evidence)
    pieces = re.split(r"(?<=[.!?])(\s+)", claim)
    if len(pieces) > 1:
        return "".join(grounded_sequence(piece, evidence) if n % 2 == 0 else piece
                       for n, piece in enumerate(pieces))

    def terms(words):
        return {w[:5] for w in re.findall(r"[a-z]+(?:-\d+)?", words.casefold()) if len(w) >= 3
                and w not in {"and","are","the","with","then","before","after","from","were","that","both","they"}}

    sentences = [part for source in evidence for part in re.split(r"(?<=[.!?])\s+", source)]
    claim_words = terms(claim)
    for sentence in sentences:
        requirement = re.search(r"\bbefore\s+(.+)", sentence, re.I)
        if not requirement:
            continue
        outcomes = requirement[1]
        for join in re.finditer(r"\s+and\s+", outcomes, re.I):
            left = terms(outcomes[:join.start()]) & claim_words
            right = terms(outcomes[join.end():]) & claim_words
            if len(left - right) < 2 or len(right - left) < 2:
                continue
            # A second passage can establish the order even if the first
            # sentence only listed the two outcomes of the required check.
            for text in evidence:
                for part in re.split(r"(?<=[.!?])\s+(?!then\b)", text, flags=re.I):
                    if re.search(r"\b(?:unclear|unconfirmed|unknown|unsure|might|not sure|do not know|don't know)\b", part, re.I):
                        continue
                    if explicit.search(part) and (left | right) <= terms(part):
                        return claim
                    for order in re.finditer(r"\b(?:then|before|after|followed by)\b", part, re.I):
                        first, second = terms(part[:order.start()]), terms(part[order.end():])
                        if order[0].casefold() == "after":
                            first, second = second, first
                        if (left - right) <= first and (right - left) <= second:
                            return claim
            return sentence.strip() if len(sentence.strip()) <= 1600 else explicit.sub("", claim)
    return claim


def question_candidates(turns, questions):
    """Rank grounded leads. Each quote is participant testimony, each lead an unresolved hypothesis."""
    answers = [t for t in turns if t.get("role") == "user" and not t.get("document_event")]
    if not answers:
        return []
    index = defaultdict(list)
    for n, turn in enumerate(answers):
        for term in memory_terms(turn["text"]):
            index[term].append(n)
    turn_terms = [memory_terms(t["text"]) for t in turns]
    positions = {t["id"]: i for i, t in enumerate(turns)}
    asked = [turn_terms[i] for i, t in enumerate(turns) if t.get("role") == "assistant" and "?" in t["text"]]
    exchanges = [(i, turn_terms[i], turn_terms[i] | turn_terms[i+1]) for i, t in enumerate(turns[:-1])
                 if t.get("role") == "assistant" and turns[i+1].get("role") == "user"]
    ranked = []
    for lead in dict.fromkeys(q for q in questions if isinstance(q, str)):
        lead = re.sub(r"^\s*(?:unknown|open question)\s*:\s*", "", lead, flags=re.I).strip()
        if not lead or len(lead) > 600 or re.search(r"\b(?:[Ss]\d+|detached component)\b", lead):
            continue
        terms = memory_terms(lead)
        if not terms or any(len(terms & prior) / max(1, len(terms | prior)) >= .65 for prior in asked):
            continue
        scores, hits = Counter(), Counter()
        for term in terms:
            for n in index.get(term, ()):
                scores[n] += 1 / len(index[term])
                hits[n] += 1
        matches = [n for n in scores if hits[n] >= 2]
        if not matches:
            continue
        best = max(matches, key=lambda n: (scores[n], n))
        source = answers[best]
        # Cite the sentence carrying the match, including qualifiers. Keep its exact wording.
        sentences = re.split(r"(?<=[.!?])\s+", source["text"].strip())
        ordered = [w for word in re.findall(r"[^\W_]+", lead) for w in memory_terms(word) if w in index]
        subject = ordered[:2]
        def relevance(sentence):
            shared = terms & memory_terms(sentence)
            return sum(1 / len(index[w]) for w in shared) + sum(2 for w in subject if w in shared)
        quote = max(sentences, key=relevance)
        if not quote or len(quote) > 650 or _PARKED.search(quote):
            continue
        anchors = sorted(terms & memory_terms(quote), key=lambda w: (w not in subject, len(index[w]), w))[:5]
        if len(anchors) < 2:
            continue
        # A later reply to this same issue can resolve it even when an older map
        # continues to list the question. Leave that case for the next review.
        source_pos = positions[source["id"]]
        anchor_set = set(anchors)
        if any(i > source_pos and (len(anchor_set & question) >= 2 or len(anchor_set & exchange) >= 3)
               for i, question, exchange in exchanges):
            continue
        identity = hashlib.sha256((" ".join(sorted(terms))).encode()).hexdigest()[:16]
        candidate = {"id": identity, "gap": lead, "source": source["id"], "quote": quote, "anchors": anchors}
        ranked.append(((bool(_MATERIAL.search(lead)), scores[best], best), candidate))
    return [item for _, item in sorted(ranked, key=lambda pair: pair[0], reverse=True)[:4]]


def resume_passages(turns):
    """Select verbatim operating evidence across the account, including later corrections."""
    groups = (r"trigger|starts?|begins?|request|receiv\w*", r"if|unless|depending|otherwise",
              r"approv\w*|sign.off|director|authoriz\w*", r"hold|reject\w*|rework|correct\w*",
              r"releas\w*|portal|complet\w*|notif\w*")
    answers = [t for t in turns if t.get("role") == "user" and not t.get("document_event")]
    selected = {}
    for pattern in [_CORRECTION, *(re.compile(r"\b(?:" + part + r")\b", re.I) for part in groups)]:
        candidates = [(t, s) for t in answers for s in re.split(r"(?<=[.!?])\s+", t["text"].strip())
                      if t["id"] not in selected and 12 <= len(s) <= 550 and pattern.search(s)]
        if candidates and pattern is _CORRECTION:
            t, sentence = candidates[-1]
            selected[t["id"]] = sentence
        elif candidates:
            t, sentence = max(candidates, key=lambda pair: (len(set(pattern.findall(pair[1].lower()))), -len(pair[1]) if len(pair[1]) > 300 else 0))
            selected[t["id"]] = sentence
    return [{"turn": k, "quote": v} for k, v in selected.items()]


def _detail_text(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


_MONEY = re.compile(r"[$\u00a3\u20ac]\s*\d[\d,]*(?:\.\d+)?")
_ISSUED = re.compile(r"\b(?:issu(?:ed|ance)|original notice)\b", re.I)
_REVISED = re.compile(r"\b(?:after issuance|subsequently|later|revised|updated|new information)\b", re.I)
_MISREAD = re.compile(r"\b(?:misread|misspoke|mistakenly|was (?:a )?mistake|always showed)\b", re.I)


def permission_conflicts(findings, documents):
    """Opposite permissions for otherwise identical clauses need scoped owner review."""
    candidates = []
    for row in findings or []:
        if any(ref.startswith("doc_") for ref in row.get("evidence_turns", [])):
            candidates.extend(row.get("answer","").splitlines())
    for doc in documents or []:
        if not doc.get("retained_only") and not doc.get("archived"):
            candidates.extend(re.split(r"[.!?\n]",doc.get("text","")))
    by_rule = {}
    modal = re.compile(r"\b(cannot|can not|can|may not|may)\b",re.I)
    for sentence in candidates:
        hit = modal.search(sentence)
        if not hit:
            continue
        key = " ".join(modal.sub("may",sentence.strip().rstrip("."),count=1).casefold().split())
        forms = by_rule.setdefault(key,{})
        forms["not" in hit[1].casefold()] = sentence.strip()[:700]
    return [pair for pair in by_rule.values() if len(pair) == 2][:16]


def material_mismatch(claim, passage):
    """Veto precise amounts or explicit qualifications absent from cited text."""
    if set(_MONEY.findall(claim)) - set(_MONEY.findall(passage)):
        return True
    scope = r"\b(?i:fund|class|series)\s+([A-Z0-9]+)\b"
    claimed_scope, quoted_scope = set(re.findall(scope, claim)), set(re.findall(scope, passage))
    if claimed_scope and quoted_scope and not claimed_scope <= quoted_scope:
        return True
    for positive, negative in ((r"\bsigned\b", r"\bunsigned\b"), (r"\bapproved\b", r"\bunapproved\b"),
                               (r"\bcan\b|\bmay\b", r"\bcannot\b|\bmust not\b")):
        if re.search(positive, claim,re.I) and re.search(negative,passage,re.I) and not re.search(positive,passage,re.I):
            return True
    for qualifier in (r"\bsecond\b|\b(?:two|2|dual)\b", r"\b(?:never|cannot|can't|prohibited|must not)\b"):
        if re.search(qualifier, claim, re.I) and not re.search(qualifier, passage, re.I):
            return True
    return False


_SENTENCES = re.compile(r"(?<=[.!?;])\s+|\n+|\s+(?:but|however|whereas)\s+", re.I)
_CLOCK = re.compile(r"\b(\d{1,2})(?::([0-5]\d))?\s*([ap]\.?m\.?)\b|\b([01]?\d|2[0-3]):([0-5]\d)\b", re.I)
_NEGATIVE = re.compile(r"\b(?:no|not|never|cannot|without|prohibited|forbidden)\b|\b\w+n['’]t\b", re.I)
_STOPPED = re.compile(r"\b(?:on hold|(?:we|they|work|processing)\s+(?:must\s+)?(?:stop|pause|halt)|"
                           r"(?:is|are|remains?)\s+(?:blocked|paused|suspended))\b", re.I)
_HOLD_ACTION = re.compile(r"\b(?:hold|halt|stop|pause|suspend|block|wait|await|defer)\w*\b", re.I)
_OWNERSHIP = re.compile(r"\b(?:owns?|is (?:responsible|accountable) for|has responsibility for)\b", re.I)
_ROLE_SPLIT = re.compile(r"[,;]|\s+\band\b\s+(?=[^,;.!?]{1,45}\b(?:owns?|is responsible|is accountable)\b)", re.I)
_OPERATOR = r"\b(?:user|person|signer|employee|individual|operator|staff member)s?\b"
_SINGLE_OPERATOR = re.compile(r"\b(?:same|single|one)\b(?:[\w-]*\s+){0,3}" + _OPERATOR, re.I)
_SEPARATE_OPERATORS = re.compile(r"\b(?:different|separate|distinct|independent)\b(?:[\w-]*\s+){0,3}" + _OPERATOR, re.I)


def _clock_values(text):
    values = set()
    for match in _CLOCK.finditer(text):
        hour, minute, half, full_hour, full_minute = match.groups()
        if half:
            values.add((int(hour) % 12 + 12 * half.lower().startswith("p"), int(minute or 0)))
        else:
            values.add((int(full_hour), int(full_minute)))
    return values


def _ownership_mismatch(claim, passage):
    """The role and the duty must belong to the same assertion in the cited account."""
    owns = _OWNERSHIP.search(claim)
    if not owns:
        return False
    actor = memory_terms(claim[:owns.start()])
    duty = memory_terms(claim[owns.end():])
    if not actor or not duty:
        return False
    matching_owners = []
    for clause in _ROLE_SPLIT.split(passage):
        verb = _OWNERSHIP.search(clause)
        if verb and duty <= memory_terms(clause[verb.end():]):
            matching_owners.append(memory_terms(clause[:verb.start()]))
    return bool(matching_owners) and not any(actor & owner for owner in matching_owners)


def control_mismatch(claim, passages):
    """Veto a material change in a control where the wording of its cited source resolves it."""
    times = _clock_values(claim)
    terms = memory_terms(claim)
    sentences = [s for text in passages for s in _SENTENCES.split(text) if s.strip()]
    if not terms or not sentences:
        return False
    # A different sentence in the same cited turn can describe a different control.
    overlap = [len(terms & memory_terms(s)) for s in sentences]
    strongest = max(overlap)
    matched = [s for s, score in zip(sentences, overlap) if score and score == strongest]
    if times and not any(times <= _clock_values(s) for s in matched):
        return True
    for sentence in matched:
        if _ownership_mismatch(claim, sentence):
            return True
        if _SINGLE_OPERATOR.search(claim) and not _NEGATIVE.search(claim) and _SEPARATE_OPERATORS.search(sentence):
            return True
        if re.search(r"\b(?:always|without exception|in every case)\b", claim, re.I) and re.search(
                r"\b(?:no default|no standard|case.by.case|varies|sometimes|not always)\b", sentence, re.I):
            return True
        # Cover both "execution is not authorized" and "no live execution is authorized".
        for predicate in ("authori[sz]ed|permitted|allowed", "approved", "required", "confirmed"):
            action = r"\b(?:" + predicate + r")\b"
            if (re.search(action, claim, re.I) and not _NEGATIVE.search(claim)
                    and re.search(r"(?:\bnot|\bnever|n['’]t)\s+(?:yet\s+)?" + action
                                  + r"|\bno\s+(?:\w+\s+){1,4}(?:is|are|was|were)\s+" + action, sentence, re.I)):
                return True
    return False


def route_outcome_mismatch(start, target, label, quotes):
    """Check the action at the destination against explicit prohibitions and stops."""
    first = re.match(r"[A-Za-z]{3,}", target)
    if not first or not quotes:
        return False
    stem = first[0].casefold().removesuffix("e")
    action = re.compile(r"\b" + re.escape(stem) + r"(?:e|es|s|ed|ing|ure)?\b", re.I)
    passages = " ".join(quotes)
    denied = any(action.match(re.sub(r"^\s*(?:(?:by itself|itself|automatically|necessarily|alone)\s+)?",
                                     "", passages[neg.end():], flags=re.I)) for neg in _NEGATIVE.finditer(passages))
    affirmed = any(action.search(clause) and not _NEGATIVE.search(clause) for clause in _SENTENCES.split(passages))
    if denied and not affirmed and not _NEGATIVE.search(target):
        # "Do not release until Finance approves" supports release on that
        # approval, while refusing the same action on an unrelated event.
        gate = re.search(r"\b(?:until|unless)\s+([^.!?;]+)", passages, re.I)
        proposed = start + " " + label
        if not gate or _NEGATIVE.search(proposed) or re.search(r"\b(?:missing|failed|pending|denied)\b", proposed, re.I):
            return True
        requirement = {word[:4] for word in memory_terms(gate[1])}
        trigger = {word[:4] for word in memory_terms(proposed)}
        if not requirement or len(requirement & trigger) < min(2, len(requirement)):
            return True
    holding = _HOLD_ACTION.match(target) or re.search(r"\b(?:put|place|mark)\b.*\b(?:hold|blocked|paused)\b", target, re.I)
    if _STOPPED.search(passages) and not (holding or action.search(passages)):
        return True
    waiver = re.search(r"\b(?:no|without|skip|bypass)\s+(?:(?:new|further|additional|another|the|a)\s+)*"
                       r"(review|approval|signature|check|verification|clearance)\b", label, re.I)
    if waiver and not _NEGATIVE.search(passages):
        return re.search(r"\b(?:re-?)?" + waiver[1][:5] + r"\w*", passages, re.I) is not None
    return False


def issued_amount_history(turns):
    """Recognize a later account of the same named financial amount at issuance."""
    prior, latest = [], None
    for turn in turns:
        if turn.get("role") != "user" or turn.get("document_event"):
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", turn["text"]):
            amounts = set(_MONEY.findall(sentence))
            if len(amounts) != 1:
                continue
            amount = amounts.pop()
            subjects = set(re.findall(r"\b(?:fee|estimate|valuation|balance|commitment|interest|distribution)\b", sentence.casefold()))
            if not subjects:
                continue
            scope = set(re.findall(r"\b(?i:fund|class|series)\s+([A-Z0-9]+)\b", sentence))
            for old, old_amount, old_subjects, old_scope, old_quote in reversed(prior):
                if old_amount != amount and subjects & old_subjects and scope == old_scope and old != turn["id"]:
                    corrected = bool(_MISREAD.search(turn["text"]))
                    changed = bool(_REVISED.search(turn["text"]))
                    if corrected or changed or re.search(r"\bnow\b", sentence, re.I):
                        latest = {"original":old_amount,"latest":amount,"earlier_id":old,"later_id":turn["id"],
                                "earlier_quote":old_quote,"later_quote":sentence,"account":"correction" if corrected else
                                "change" if changed else "unclear"}
                        break
            if _ISSUED.search(sentence):
                prior.append((turn["id"],amount,subjects,scope,sentence))
    return latest


def unestablished_reissue(claim, history, turns):
    """A changed estimate alone provides no basis to assert a new investor notice."""
    action = r"\b(?:(?:reissu\w*|resen[dt]|recirculat\w*)\s+(?:the\s+|a\s+)?(?:capital call\s+)?notice|(?:send|sent|issue[ds]?)\s+(?:a\s+|the\s+)?revised notice)\b"
    if not re.search(action, claim, re.I) or re.search(r"\b(?:no|never|do not|did not)\b",claim,re.I):
        return False
    later = next((t["text"] for t in turns if t.get("id")==history["later_id"]),"")
    return not any(re.search(action, sentence, re.I) and not re.search(r"\b(?:no|never|did not|not yet)\b", sentence,re.I)
                   for sentence in re.split(r"(?<=[.!?])\s+",later))


def amount_review_question(history):
    documents = set(re.findall(r"\b(?:invoice|notice|statement|bill)\b", history["earlier_quote"].casefold()))
    subject = f"the original {documents.pop()}" if len(documents) == 1 else "what was originally issued"
    return f"How, if at all, does the later amount of {history['latest']} affect {subject} at {history['original']}?"


def confirmed_passages(context):
    """Wording separately attested by a participant for a resolved source revision."""
    return {row["reference"]: row["answer"] for row in (context or {}).get("file_topic_reviews", [])
            if row.get("decision") == "confirmed" and row.get("reference") and row.get("answer")}


def _detail_sources(turns, documents, context):
    """The wording each source ID stands for when an operating detail quotes it."""
    sources = {turn["id"]: [_detail_text(turn.get("text", ""))] for turn in turns
               if turn.get("role") == "user" and not turn.get("document_event")}
    sources["context"] = [_detail_text(value) for key, value in (context or {}).items()
                          if key in ("process_name", "process_owner", "background") and isinstance(value, str) and value]
    sources.update({ref: [_detail_text(value)] for ref, value in confirmed_passages(context).items()})
    for document in documents or []:
        if isinstance(document.get("text"), str):
            sources[document["id"]] = [_detail_text(document["text"])]
    return sources


def _detail_passage(fact):
    return re.compile(r"(?<!\w)" + re.escape(_detail_text(fact)) + r"(?!\w)")


def validate_operating_details(steps, turns, documents, context, carried=()):
    """Bind each optional fact to its own quoted sources and to the same process step."""
    if not any(isinstance(step, dict) and "operating_details" in step for step in steps):
        return
    sources = _detail_sources(turns, documents, context)
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError("A process step must be an object.")
        details = step.get("operating_details", [])
        if not isinstance(details, list) or len(details) > 32:
            raise ValueError("A step can contain up to 32 cited operating details.")
        for row in details:
            if not isinstance(row, dict) or set(row) != {"field", "text", "evidence_turns"} or row["field"] not in STEP_DETAIL_FIELDS:
                raise ValueError("A step operating detail has an unsupported field.")
            fact, refs = row["text"], row["evidence_turns"]
            if not isinstance(fact, str) or not fact.strip() or len(fact) > 500 or not isinstance(refs, list) or not 1 <= len(refs) <= 15:
                raise ValueError("A step operating detail needs short quoted text and its supporting source references.")
            if any(not isinstance(ref, str) or ref not in step.get("evidence_turns", []) for ref in refs):
                raise ValueError("An operating detail must cite evidence from its own step.")
            passage = _detail_passage(fact)
            for ref in refs:
                if ref not in sources and ref in carried:
                    continue
                if not any(passage.search(source) for source in sources.get(ref, [])):
                    raise ValueError("The operating detail must quote the cited participant, context or document excerpt.")


def settle_operating_details(steps, turns, documents, context, carried=(), accepted=None):
    """Keep what the cited sources of a generated step bear out of its operating details.

    A model returns these details with the step. One of them can cite a source the step
    does not cite, or quote wording its source does not contain. That slip is the model's:
    it is settled here instead of refusing the whole map and showing the validation
    message to the participant. A detail keeps the sources that are the step's own and
    contain its wording; a detail that keeps none is dropped, as is one that is not a
    detail at all. Nothing is added or reworded. accepted maps a step ID to the details
    that step already had on the accepted map: those are kept as they are (an excerpt
    they cite may be outside this request). Returns the number of details dropped.
    validate_operating_details still checks the result.
    """
    sources, dropped = None, 0
    for step in steps:
        if not isinstance(step, dict) or not isinstance(step.get("operating_details"), list):
            continue
        own = [ref for ref in step.get("evidence_turns", []) if isinstance(ref, str)] if isinstance(step.get("evidence_turns"), list) else []
        known = (accepted or {}).get(step.get("id")) or []
        kept = []
        for row in step["operating_details"]:
            if row in known:
                kept.append(row)
                continue
            if (not isinstance(row, dict) or set(row) != {"field", "text", "evidence_turns"} or row["field"] not in STEP_DETAIL_FIELDS
                    or not isinstance(row["text"], str) or not row["text"].strip() or len(row["text"]) > 500
                    or not isinstance(row["evidence_turns"], list)):
                dropped += 1
                continue
            if sources is None:
                sources = _detail_sources(turns, documents, context)
            passage = _detail_passage(row["text"])
            refs = [ref for ref in dict.fromkeys(ref for ref in row["evidence_turns"] if isinstance(ref, str)) if ref in own
                    and (ref not in sources and ref in carried or any(passage.search(source) for source in sources.get(ref, [])))][:15]
            if not refs:
                dropped += 1
                continue
            kept.append(row if refs == row["evidence_turns"] else {**row, "evidence_turns": refs})
        if len(kept) > 32:
            dropped += len(kept) - 32
            kept = kept[:32]
        step["operating_details"] = kept
    return dropped


CONTEXT = """
GPFS CONTEXT
Capture current business processes at GP Fund Solutions (GPFS). Relevant entity
types include funds, GP/carry vehicles, management companies (ManCos), feeders,
blockers, holding companies, SPVs and co-investment vehicles. Enterprise work
such as HR, IT and internal operations need not be entity-specific. These are
questioning vocabulary, never evidence that an entity, system or control applies.
Entrilia and Allvue are possible systems, not assumed systems of record.
Distinguish the participant's normal route from an approved GPFS standard.
Ask their basis, and preserve unknown, disputed or client-only practice. A route
is gold_standard only when a participant describes general GPFS practice AND
independent written material or a second account corroborates that exact scope;
this is corroborated reported practice, not owner approval or legal verification.
Classify differences as structural, client_specific, presentation or unclassified,
with their reported source and substantive-versus-presentation nature. Keep
charging and removal constraints where relevant; never infer that a variant is
unnecessary or a review redundant. Record who interprets rules; do not interpret
contracts or decide which source ought to prevail.
"""

SELECTION = """
NATURAL DISCOVERY AND COVERAGE
Use the sixteen topics privately. Let the person finish, including hesitations;
a partial caption or listening cue is not an answer. Use the whole conversation.
If they described the stages already, ask about the missing decision at one stage
instead of requesting the walkthrough again. If they named the reviewer, ask what
that person compares only if the comparison is still unclear.

Respond to a direct question, correction or confusion FIRST. Find an earlier answer
if the participant says they gave it. Keep each fact tied to its event. Do not
repeat the question, apologise in a loop or prompt someone to finish a single word.

Start with the work they name. Narrow it once if broad. Follow an ordinary example
with ONE short, concrete question at a time. For a routing overview, learn how they
choose the detailed process that owns the finish. For a specific route, clarify the
unit and observable proof of finish. If a notice goes out, what tells them the case
can close? Ask about acceptance only when the account leaves that boundary open.

Prioritize answerable gaps that change an action, check, release, handoff or recovery.
If a missing rule is someone else's, ask about the participant's actual handling only
if still unclear: "What happens to those entries while Treasury decides?" Once they
have explained the affected route, what holds or proceeds, and where it goes, leave
the outside decision for owner review. An escalated exception may permit normal work
to continue; a blocked method can stop just that method. Follow what they reported.
If they cannot explain the handling either, retain that gap and move on. Never press
for an unknown again by asking who knows it. Keep a resolver or source when supplied.

Learn applicability, start, finish and dependencies from the story: "Does that
work the same across your funds?" For a client, method or country variation, ask
which step, approval or finish differs. Accept an unknown GPFS standard. A volume,
cost or archive detail can go to the owner when it leaves the route unchanged;
if a threshold selects the approver or a file unlocks release, prioritize it.

Use conditional modules only where relevant to this participant's work. Attach
rule questions to an actual calculation or decision: "Where do the investor
amounts come from?" or "What sets the payment date?" Never ask about "the main
rule", business-rule lineage, entity applicability or taxonomy in the abstract.
If the calculation is upstream, capture its output and how the participant knows it is ready.
Record mentioned documentation as existing, unreviewed material; an attachment
is not required to remember that it exists. Ask only for genuinely missing detail.

Briefly recap a useful stretch of the walkthrough or a material correction when
it helps the person check your understanding; avoid compulsory scoping recaps or
recapping the same facts repeatedly. After the route is clear, naturally fill
material gaps in rules, controls, connections, data, variants, volume, effort,
purpose, accountability, risk and materials. Avoid a questionnaire or a barrage
of new subjects. The background reviewers still assess every relevant dimension.
Unknown is not N/A, and a friendly conversation does not establish completeness.
Only the application owns the final omissions check, confirmation and completion.
"""

MODULES = """
CONDITIONAL MODULES (contextual signals, not a keyword checklist):
FUND: fund/LP/investor/NAV/LPA context suggests governing documents, side letters,
investor dimensions, allocation rules and notices where relevant to this work.
GP_CARRY: GP/carry/deemed contribution/fee waiver suggests partner economics,
commitment funding, related-party flows and GP-side approvals where in scope.
MANCO: management company/adviser/payroll/intercompany suggests fee and expense
flows, settlement, corporate approvals and accounting-policy sources.
MULTI_ENTITY: several reported entity types suggests whether logic actually
branches, where, why and whether differences are substantive or presentation.
CALCULATION: a calculated amount suggests inputs and origins, governing rule and
source, sequence/dependencies, investor/fund/entity dimensions, dates/periods,
mid-period treatment, prior-period inputs, rounding/tie-out, override authority
and recording, and amendments/corrections. Separate economic rule from its
implementation. Probe material missing details progressively, not all at once.
SPREADSHEET: workbook/model/macro suggests external rule versus logic existing
only in the sheet, logic ownership, re-keying, outputs and repeated calculation.
CLIENT_APPROVAL: reported client review/sign-off suggests exact approval point,
review versus approval, what is blocked, rejection/delay handling and evidence.
CLIENT_SPECIFIC: an actual reported client difference suggests GPFS standard
(if known), changed step, class/source, effort/controls/tools, charge and removal
constraints. A client name alone does not establish a difference.
Modules may overlap. Questions apply only to material unanswered slots within
the participant's boundary. An upstream calculation or approval is a dependency:
capture its source, output, owner and gap; do not expand into a different process.

When someone relies on a result, listen for what they can use, for what purpose,
what establishes it and what can still change. Ask one question in their words
only if a missing detail matters, such as how the team handles a later difference.
Distinguish the effective date or period from when the work happens if it affects
the result. Keep both stages of an actual change. If the speaker corrects what
they said, revise the misstated fact.

Ask a neutral exception question once if still unanswered: what most often stops
this work or sends it back? Accept an explicit absence. Frequent reported returns
belong in the main route without assuming every run fails.
"""

FACETS = {
    "entity_type": ["fund", "gp_carry", "manco", "feeder", "blocker", "holding", "spv", "co_invest", "enterprise", "other"],
    "applicability": ["single_entity", "multi_same", "multi_variant", "enterprise", "unknown"],
    "functional_area": ["capital_activity", "fund_accounting", "investor_reporting", "financial_reporting", "fees_and_carry", "allocations", "treasury_payments", "tax", "compliance_regulatory", "investor_services", "onboarding", "data_management", "hr", "it", "internal_operations", "other"],
    "process_level": ["process", "subprocess", "activity", "unknown"],
    "client_applicability": ["gpfs_standard", "client_specific", "multi_client_variant", "enterprise", "unknown"],
    "rule_source": ["lpa_governing_doc", "side_letter", "subscription_docs", "client_methodology", "gpfs_methodology", "accounting_policy", "regulatory", "tax", "system_configuration", "prior_period_practice", "spreadsheet", "institutional_knowledge", "other", "unknown"],
    "system": ["entrilia", "allvue", "excel_workbook", "email", "sharepoint_folder", "client_portal", "bank_platform", "other", "none"],
    "control_type": ["gpfs_operational", "gpfs_supervisory", "client_review", "client_approval", "system_enforced", "exception_escalation", "none_reported"],
    "variant_class": ["gold_standard", "structural", "client_specific", "presentation", "unclassified"],
}
RELATIONSHIPS = ["provides_input_to", "consumes", "hands_off_to", "requires_approval_from", "happens_after", "variant_of", "subprocess_of", "parallel_with", "shares_calculation_with"]

def obj(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}

TEXT = {"type": "string"}
REFS = {"type": "array", "items": TEXT}
TAG_FIELDS = ("facet", "value", "note", "evidence_turns")
TAG = {"anyOf": [obj({"facet": {"type": "string", "enum": [facet]},
    "value": {"type": "string", "enum": values}, "note": TEXT, "evidence_turns": REFS})
    for facet, values in FACETS.items()]}
CONNECTION = obj({"relationship_type": {"type": "string", "enum": RELATIONSHIPS}, "counterpart": TEXT, "condition": TEXT, "evidence_turns": REFS})
CLASSIFICATIONS = {"type": "array", "items": TAG}
CONNECTIONS = {"type": "array", "items": CONNECTION}
TAG_OPERATION = {"anyOf": [obj({"op": {"type": "string", "enum": ["add", "replace", "remove"]},
    "target_id": TEXT, **branch["properties"]}) for branch in TAG["anyOf"]]}

RELATIONSHIP_POLICY = """
Read each relationship from the interviewed process to its named counterpart. If Treasury receives
this process's file, this process provides_input_to or hands_off_to Treasury. If Fund Accounting supplies
this process's opening balance, this process consumes its output or happens_after its close.
requires_approval_from names the approver. variant_of and subprocess_of name the base or parent.
parallel_with and shares_calculation_with describe a peer. Never reverse a prior relationship without evidence.
"""

CAPTURE_POLICY = MODULES + RELATIONSHIP_POLICY + """
BACKGROUND CLASSIFICATION
Populate taxonomy from cited evidence, never ask participants to select taxonomy.
Emit tag_operations with facet/value from the supplied controlled vocabulary and
note preserving scope, qualifiers and reported versus documented provenance.
Use other with a note for an unlisted value. No source means no tag. Add with an
empty target_id; replace/remove only a supplied active tag ID with correction
evidence. Empty operations retain existing tags. A correction must also retire
contradicted tags. Never promote a client's normal practice to gold_standard.
connections_out adds or updates reported external process
dependencies. Preserve prior entries unless a newer participant turn corrects them. Cite that turn in remove_connections
and give the named target ID to withdraw an old relation. Remove a parked thread
only in resolved_parking_lot with its exact text and the participant source that resolved it. A name is
allowed when no submission ID exists. These are reported leads, not confirmed
cross-submission graph links. Do not imply counterpart evidence was checked.
Report active_modules as relevant module names; recap_due is scope_boundary,
walkthrough or none. Check prior assistant turns before marking a recap due.
"""

def legacy_defaults(value, schema):
    """Upgrade only newly added empty/unknown fields, never invent business facts."""
    if not isinstance(value, dict):
        return
    defaults = {"taxonomy": [], "connections_out": [], "tag_operations": [], "remove_connections": [], "resolved_parking_lot": [],
                "active_modules": [], "recap_due": "none", "control_type": [],
                "data_origin": "", "entry_mode": "unknown", "rule_source_ref": "",
                "entity_scope": [], "parent_process": "", "operating_details": [], "variant_class": "unclassified",
                "substantive_or_presentation": "unknown", "source": "", "standard_route_ref": ""}
    fields = set(schema.get("properties", {}))
    if {"owner_followups", "dimensions"} <= fields:
        value.setdefault("owner_followups", [])
    if fields == {"needed", "edits"}:
        value.setdefault("edits", [])
    if "discard_step_removals" in fields and "remove_steps" in fields:
        value.setdefault("remove_steps", [])
    if fields == {"text", "sources", "basis", "quote"}:
        value.setdefault("basis", "inferred")
        value.setdefault("quote", "")
    if "field_evidence" in fields and "route_support" in fields:
        value.setdefault("field_evidence", [])
    allowed = set()
    if {"op", "topic", "target_id", "evidence_turns", "support"} <= fields:
        value.setdefault("support", [])
    if {"memo_findings", "question"} <= fields or "memo_summary" in fields:
        allowed.update(("taxonomy", "connections_out", "active_modules", "recap_due"))
    if {"fact_operations", "topic_states", "base_revision"} <= fields:
        allowed.update(("tag_operations", "connections_out", "active_modules", "recap_due", "remove_connections", "resolved_parking_lot"))
    if {"id", "actor", "system", "input", "output", "handoff", "completion_criteria"} <= fields:
        allowed.update(("control_type", "data_origin", "entry_mode", "rule_source_ref", "entity_scope", "parent_process", "operating_details"))
    if {"applies_to", "difference", "reason", "cost", "charging", "removability", "boundary_reason"} <= fields:
        allowed.update(("variant_class", "substantive_or_presentation", "source", "standard_route_ref"))
    for key in fields & allowed:
        if key not in value:
            value[key] = copy.deepcopy(defaults[key])

def validate_metadata(value, valid_sources):
    """Provenance/value guards; semantic classification still needs review."""
    if len(value.get("taxonomy", [])) > 128 or len(value.get("connections_out", [])) > 100:
        raise ValueError("Too many classifications or external process connections.")
    for item in value.get("taxonomy", []):
        if item["value"] not in FACETS[item["facet"]]:
            raise ValueError("Unsupported taxonomy value for its facet.")
        if item["value"] == "other" and not item["note"].strip():
            raise ValueError("An other classification needs a descriptive note.")
    for item in value.get("taxonomy", []) + value.get("connections_out", []):
        if not item["evidence_turns"] or not set(item["evidence_turns"]) <= set(valid_sources):
            raise ValueError("A classification or process connection requires exact authorized evidence.")
        if "counterpart" in item and not item["counterpart"].strip():
            raise ValueError("A process connection requires a named counterpart.")
    for item in value.get("taxonomy", []):
        if item["value"] == "gold_standard" and len(set(item["evidence_turns"])) < 2:
            raise ValueError("A gold standard requires corroborating sources, not a single report.")

def ground_classification(item, turns, documents):
    """Keep the reported variation without assigning a standard uncorroborated by a file."""
    field = "variant_class" if "variant_class" in item else "value"
    if item.get(field) == "gold_standard":
        users = {t["id"] for t in turns if t.get("role") == "user" and not t.get("document_event")}
        docs = {d["id"] for d in documents or [] if not d.get("retained_only") and not d.get("provenance_only")}
        if not isinstance(item.get("evidence_turns"), list) or not all(isinstance(ref, str) for ref in item["evidence_turns"]):
            raise ValueError("Gold standard evidence must contain source identifiers.")
        refs = set(item["evidence_turns"])
        if not refs & users or not refs & docs:
            item[field] = "unclassified"
            if field == "value":
                if not isinstance(item.get("note", ""), str):
                    raise ValueError("A taxonomy note must be text.")
                item["note"] = (item.get("note", "") + " Independent documentary corroboration was unavailable.").strip()


def validate_corroboration(value, turns, documents):
    users = {t["id"] for t in turns if t.get("role") == "user" and not t.get("document_event")}
    docs = {d["id"] for d in documents or [] if not d.get("retained_only") and not d.get("provenance_only")}
    for item in value.get("taxonomy", []) + value.get("variations", []):
        if item.get("value") != "gold_standard" and item.get("variant_class") != "gold_standard":
            continue
        refs = set(item["evidence_turns"])
        # Several turns from one interview are still one account. A second
        # account is validated in the graph; this local path requires a document.
        if not refs & users or not refs & docs:
            raise ValueError("Gold standard needs participant testimony and independent documentary corroboration; multiple turns are one account.")
