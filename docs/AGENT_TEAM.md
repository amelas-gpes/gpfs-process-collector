# Managed interview team

The application uses three core roles to capture and review a process account, with a fourth role for supplied documents. Only the lead interviewer addresses the participant. Application code controls completion and speech release; a model's proposed closing sentence cannot authorize either.

This describes the local implementation on 3 November 2026. It is not a claim of production deployment, process-owner approval, or verified physical microphone and speaker behavior.

## Roles and execution

| Role | Current default model | Responsibility | Authority limit |
| --- | --- | --- | --- |
| Lead interviewer | `gpt-6-luna`; configured process model for reconciliation and maps; document model for baseline rebuilds | Maintain the capture and ask one grounded question during information gathering. Also prepares working process-map updates on demand. | Cannot declare the interview complete by itself. |
| Coverage reviewer | `gpt-6-luna` | Independently assess all eleven topics and every required dimension against participant evidence. | Can reject an overclaim; cannot manufacture missing facts. |
| Process reviewer | `gpt-6.1-terra` | Compare proposed actors, actions, connections, outputs and exception routes with their cited sources. Identify material contradictions or gaps. | Cannot rewrite source evidence or mark topics complete. |
| Document analyst | `gpt-6.1-terra` | Review authorized excerpts or visual sources on demand; audit document-supported map changes. | Documentary content is not confirmation of current practice. No arbitrary file access or file-management tools. |

[`agent_team.py`](../agent_team.py) supplies the immutable evidence snapshot, role contracts, execution events, provenance validators and completion permit. It does not call a provider or persist interviews. [`interview_orchestrator.py`](../interview_orchestrator.py) supplies bounded provider callbacks through the existing `OpenAIClient` in [`server.py`](../server.py).

Task-local settings or environment variables can override the four defaults with `AGENT_INTERVIEW_MODEL`, `AGENT_COVERAGE_MODEL`, `AGENT_PROCESS_MODEL` and `AGENT_DOCUMENT_MODEL`. The existing credential is reused; a separate key is not required for each role. Public configuration reports model identifiers, not the credential.

An ordinary interview turn uses one lead call. Server-owned capture state supplies known explanations, prior gaps and conversation focus. Important current ambiguities, corrections and second volunteered issues take priority; otherwise the lead moves to an untouched topic. Its proposed full topics remain provisional until reviewed. The application blocks closing language while required coverage is unresolved. The lead's response is streamed and its question is the first field, so the typed interface can show the question as a preview while the fact transaction finishes; nothing is committed to the transcript or spoken until the whole response validates and passes the same boundary. The working-map request starts alongside the lead call rather than after it, and a prior completion review reaches the lead as its open gaps and reviewer questions rather than the full assessment text.

The lead returns changes to a private fact ledger rather than rewriting the entire memo on every answer. Application-assigned fact IDs preserve unmentioned details. Additions and explicit replacements or removals carry source references and a reason; a revision-bound schema separates edits to known details from resolving a gap. Public topic explanations are assembled from the retained facts. The ledger and its capabilities are not included in saved sessions or exports. A reopened session rebuilds from its full authorized evidence in one lead request.

Each open gap or fact containing unresolved wording that the latest answer could affect — the answer or its question uses that topic's words, or shares two content words with the claim — receives an explicit reconciliation in that same response. Untouched claims keep their exact prior wording and need no row; the lead may still resolve one with an explicit operation when the testimony answers it. Keeping a fact requires a cited basis; changing it requires its exact targeted operation. There is no automatic removal merely because a new answer arrived. A single canonical citation list governs each edit. That same focus decides the model for the turn: a turn that touches an open claim uses the configured process model for reconciliation, because paired real prefixes showed that cheaper-model responses still retained stale uncertainty or inferred an actor from passive wording; a turn that touches none stays on the ordinary lead model. These are bounded evaluation findings, not a guarantee that every interpretation is correct.

A substantial new document baseline or long-history rebuild uses the configured document model in the lead role for that one request. Later changes use the ordinary lead model unless existing uncertainty needs reconciliation. Authoritative file revisions prevent a different search query from repeatedly triggering the expensive baseline route. This changes the model for one role; it does not add a second interviewer or an extra ordinary-turn agent call. The activity panel reports the model actually used.

The HTTP layer pins private fact citations through the current scoped document store. Selecting another excerpt from an unchanged file cannot silently erase an earlier cited fact. A source budget that cannot retain the required evidence produces an explicit recoverable error; a changed or removed source invalidates its old authority. The handler rechecks the same source selection before releasing a delayed response, map or draft.

When all eleven candidate sections appear complete and document work is ready, the application returns one fixed acknowledgment: “Let me check that I have everything before we finish.” The browser displays it, or finishes playing it in voice, before requesting `/api/agent-team/review`. The process reviewer and the coverage reviewer examine independent copies of the same evidence concurrently. The coverage review itself runs as three concurrent topic groups (9, 12 and 11 dimensions); each sees the whole transcript and every candidate finding but assesses only its own topics, and the merged result passes the unchanged whole-account validation. Code selects their grounded follow-up or the fixed final omissions check; there is no additional lead call simply to phrase that transition. The specialists' observations are fallible interpretations, not new source evidence.

| Transition | Provider calls |
| --- | ---: |
| Empty opening | 0 |
| Ordinary information gathering | 1 lead (streamed) |
| Advisory pre-check of newly captured topics | 1 coverage call in the background, display-only |
| Completion review after acknowledgment | 1 process reviewer + 3 concurrent coverage groups |
| Unchanged explicit final confirmation | 0 |
| Working-map update | 1 lead, plus a document audit when document evidence is present |

After an ordinary turn that marks topics captured, the browser asks `/api/agent-team/coverage` to pre-check only those topics with one coverage call limited to them. The result is display-only: a topic shows “Captured · pre-checked” or “Captured · gap noted” (with the noted gap and a suggested question in its detail), bound to the exact captured answer, and it never counts toward official coverage or the completion permit. The completion review still re-assesses every topic against the actual run.

Document intake has its own bounded analyst run for each requested review batch or phase. Ordinary map refreshes start alongside each lead turn, whichever view is open, so the diagram and the notes update together; the map still waits for document intake and for a completion review. These are transition budgets, not a fixed price or total call limit for a conversation. The manager prevents duplicate execution and does not run an open-ended agent discussion.

On-demand working maps use the configured process model in the lead role, with the document audit when file evidence is present. Standalone drafts use `DRAFT_MODEL`, defaulting to the configured process model, for generation, evidence audit and any required coverage assessment. Those explicit artifact requests are separate from the ordinary conversation budget. Their bounded stage timeouts are not latency targets. Browsing the prepared fictional example makes no model request.

An empty start with no participant account or active documents uses a deterministic opening and no provider requests. Reviewers remain on standby: the interface does not claim that work is queued or reviewed before evidence exists.

Role contracts reserve conservative output budgets; provider callbacks also set output and timeout limits. The public budget describes call counts and reserved maximum output, not actual usage or a billing meter. The run registry is ephemeral and bounded. Cancellation discards a run's results; it does not guarantee that an already accepted provider request stops being billed.

## Evidence and official coverage

An `EvidenceLedger` encodes the context, chronological turns and authorized document sources, then hashes that snapshot into a revision. Accessors return copies. Duplicate source IDs are rejected. Assistant questions, document notifications and previous AI summaries do not become participant evidence. Archived or retained-only documents do not remain active evidence. Browser-supplied document evidence is discarded; the server retrieves the authorized scope itself.

The explanation test in [`interview_coverage.py`](../interview_coverage.py) is the governing standard: a section is covered only if a colleague could explain its relevant facts from the supplied evidence without filling a material gap by assumption. A tool name, a generic assertion of review, a polished memo or a long conversation is insufficient.

| Topic | What must be explainable |
| --- | --- |
| Name | Everyday name, the work it identifies, and other names or their explicit absence. |
| Purpose | The result delivered to the client or firm. |
| Trigger | Initiating event, who detects it, cadence and applicable deadlines. |
| Completion | Observable finish, required delivery or closure, and downstream boundary. |
| Accountability | The role accountable for the overall result, distinct from individual performers or reviewers. |
| Lifecycle | Items and stages, ordered actions and decisions, performers, systems and relevant locations, handoffs, exceptions and returns. |
| Checks | Actual checks, responsibilities, release conditions, failed-check rework and retained proof. |
| Variations | Applicable differences, changed work, reasons, effort, charging and constraints on removal. |
| Pain points | Manual work or friction and its practical effect, preserving attributed estimates. |
| Risk | Concrete failures and their consequences, rather than merely naming the person responsible. |
| Materials | Existing references, availability and location where supplied, and whether they were actually reviewed. |

Each supported or non-applicable dimension needs substantive detail and participant evidence references. “Unknown,” “not asked,” “skipped” and “unavailable” are unresolved states, not reasons to mark a topic non-applicable. Non-applicability requires an explicit basis. The materials section may explain the reported inventory, location, availability and honest unreviewed state without requiring an upload. A mentioned document is never represented as read.

Managed completion review can explicitly repair a compressed candidate summary when the participant already supplied every required fact. It must publish the corrected answer, validated participant citations and `capture_repairs` metadata, with every dimension supported and no factual gap. This avoids asking the participant to repeat evidence omitted by the lead's summary. It cannot promote a partial or unknown candidate, invent an actor or branch, or substitute documentary claims for participant evidence. Legacy assessment remains demotion-only.

Question selection should follow the most useful remaining gap, preserve volunteered second issues, and avoid repeating facts or precise details the participant cannot provide. A local “No” answers its local question; it does not close the whole interview. Unavailable details remain visible gaps while the interviewer explores answerable and untouched sections. An explicit request to stop preserves a partial account without another probe or a completion claim.

The process reviewer checks the candidate map as well as the transcript. In particular, a correct actor elsewhere in the account does not excuse an unsupported actor on one step. Corrections apply within their stated scope. A written procedure must not become an actual control without participant confirmation, and an unreported hypothetical exception must not become a compulsory blocker.

## Completion belongs to the application

`completion_permit` requires successful, fresh results bound to the actual run, all eleven topics complete under the dimension validator, and no material process-review blocker. Pending document review also prevents a final check. A completed role means its work returned a usable result; it does not mean the account passed.

Only after those requirements are satisfied can the application ask its global final omissions check. Full completion additionally requires an explicit participant response to that actual check. “Yes” to whether anything remains means there is more to add. A local “No,” an answer with a new correction, a stale result or a replacement clean assessment cannot satisfy confirmation. New information is reviewed again. Process findings also conservatively reopen the published lifecycle status so the visible topics do not imply universal coverage while a material route remains unclear.

Review failures preserve the capture and block completion. Participant confirmation, topic coverage, draft availability and process-owner approval are separate states. A partial draft may be useful, but is not a completed interview. See [interview completeness](INTERVIEW_COMPLETENESS.md) and [memo requirements](MEMO_REQUIREMENTS.md).

Opaque capture tokens and review tickets bind saved state to the actual evidence, context, authorized sources and issued final check. The bounded cache expires after thirty minutes and is not saved or exported. Duplicate review requests share one in-flight execution; an explicit failed-review retry retains the successful lead capture. Unchanged final confirmation reuses successful assessments. New substantive facts, changed source contents or authorization, cancellation and superseding requests invalidate stale authority. Source retrieval retains the original query for known non-evidentiary acknowledgments and confirmation while rechecking current document access and contents.

This is whole-account freshness, not an assertion that unchanged citations prove every topic is unaffected by a new answer. A correction about who reviews a file can affect lifecycle, checks and accountability. New candidate facts therefore remain awaiting review until the next completion review. Previously captured explanations still guide the lead so it does not ask the same questions again.

An application-checked unavailable-only pause is possible without pretending the interview is complete. Every open topic must have actual participant evidence of unavailability, specific unresolved dimensions and no useful remaining question; material process findings must also be tied to that evidence and have no answerable question. An untouched topic, missing audit, pending document or blank reviewer question alone does not establish unavailability.

When only explicitly unavailable topics remain, the acknowledgment is “Let me check what we have and keep the unanswered parts open.” That partial review cannot authorize full completion. Typed review offers Pause and Resume; cancellation and retries preserve the account while invalidating obsolete review authority.

These checks enforce source identity, structure, freshness and the completion contract. They cannot prove that a model's confident interpretation of a valid citation is correct. Independent semantic review and task-specific evaluation remain necessary; Structured Outputs constrain a response's shape, not its truth. [OpenAI Structured Outputs guidance](https://developers.openai.com/api/docs/guides/structured-outputs).

## Documents join when needed

The existing document pipeline owns uploads, originals, extraction, source locations, scoped retrieval and review phases. The analyst receives only that authorized material. Text observations cite permitted chunk IDs; supported visual inputs use the relevant supplied page or image. Text-only analysis cannot invent a new visual transcription. File instructions are treated as source content, not instructions to the agents.

Mentioning a document is distinct from reviewing it; reviewing it is distinct from confirming that people follow it. Conflicts between a procedure and the participant's account remain explicit. The analyst can suggest a useful question, but only the lead asks it. A workflow containing document evidence receives a separate source audit. Working-map updates remain provisional and do not authorize interview completion.

The team has no autonomous folder scanning, moving, renaming, deleting, publishing or messaging capability. Existing user-driven file actions and persistence remain in the application. See [document interviews](DOCUMENT_INTERVIEWS.md).

## Activity interface

[`web/agent-team.js`](../web/agent-team.js) renders real server execution metadata in the Interview team panel. The three core cards are present; the document card appears when analyst activity is supplied. Queued, working, done, waiting and issue states come from actual run events. The view does not invent timed milestones, percentages, reasoning traces or evidence of a successful review.

Cards disclose their responsibilities and bounded status details. Completed reviewer cards explicitly say that a finished check can still leave open topics. Recent completed work contains at most three actual completion events. Older polls and retired runs cannot overwrite a newer display. Collapsible native controls, polite status announcements, narrow-screen layout and reduced-motion styling are implemented. This is an implementation description, not a completed assistive-technology or visual acceptance audit.

During ordinary turns, reviewers remain on standby. Candidate topics say “Captured · awaiting review” and do not increase the official covered count. Actual completion-review waits say “Checking the recorded topics and process…” in both typed and voice status. Reused results are identified as prior work rather than a new provider invocation.

## One reviewed voice

The active team voice uses this sequence:

1. Browser microphone capture produces a recorded answer segment.
2. `/api/transcribe` returns text, which is added to the participant transcript.
3. The managed interview endpoint performs one capture call; at completion readiness, its acknowledgment precedes the separate specialist review.
4. The browser verifies `speech_authorization`, matching approved text, completion flags and the unchanged source snapshot.
5. The selected reader plays that approved response; listening resumes after playback finishes.

[`web/controlled-voice.js`](../web/controlled-voice.js) uses local speech activity detection with a 1.8-second silence interval and a 90-second capture bound. A segment with less than a quarter second of voiced audio (a cough, a breath, the echo tail of playback) is dropped locally without a transcription request, and a transcription that returns no words keeps the microphone listening with a short notice; only three empty answers in a row stop the session. The reader's short-lived token is requested while the lead is still working, so approved playback can start as soon as the response is authorized; a token older than forty seconds is replaced. Silence alone does not create transcription requests. Capture is disabled during review and playback. Mute, stop, page exit and failed operations clean up recording and pending work. This is turn-based voice, not simultaneous full-duplex conversation or spoken barge-in. Review latency is therefore part of the participant experience.

Natural playback uses `gpt-realtime-2.1-mini` as a text reader, with no interview tools and a short-lived client credential. The project API key stays server-side. Audio is buffered before playback; the provider's returned speech transcript must match the approved text after Unicode normalization, case folding and removal of non-letter/non-number characters. A mismatch withholds audio. This checks the returned transcript, not independent acoustic verification of what the speaker emits. Installed computer voices are also available through browser speech synthesis.

The specialist models do not speak directly. Stale, cancelled, malformed or unapproved controlled-voice responses are not applied or played. Review and playback failures retain already accepted transcript text, but audio that failed transcription cannot be claimed as a saved answer. Physical microphone capture, sound quality, real interruptions and end-to-end spoken latency still need a hands-on test.

The HTTP `/api/live-session` route rejects legacy direct-live requests with status 409 before provider work. The current browser uses reviewed turns. The older client implementation remains for legacy code/tests, but that HTTP route cannot issue a direct-live session.

Both `/api/interview` and `/api/agent-team/interview` route through the authoritative coordinator for the application's OpenAI client and its subclasses. Older text clients therefore receive the same completion gate. Isolated test adapters can still be injected at the server boundary; no browser parameter selects or weakens that adapter.

## Model choice, cost and validation

The API identifier is `gpt-6.1-terra`. Both it and `gpt-6-luna` support Responses, Structured Outputs, text output and image input; they do not themselves provide audio output. Standard short-context list prices verified on 3 November 2026 are below, per million tokens. Cache reads/writes, longer contexts, regional options, audio and tools can have different charges. [Luna model](https://developers.openai.com/api/docs/models/gpt-6-luna), [Terra model](https://developers.openai.com/api/docs/models/gpt-6.1-terra), [API pricing](https://developers.openai.com/api/docs/pricing).

| Model | Ordinary input | Output | Selection evidence |
| --- | ---: | ---: | --- |
| `gpt-6-luna` | $0.10 | $0.50 | Lower-cost starting choice for lead and coverage on the tested cases. |
| `gpt-6.1-terra` | $1.00 | $5.00 | Retained for process review after detecting a key actor error Luna initially missed. Document use is provisional. |
| `gpt-5.4-mini` | $0.75 | $4.50 | Earlier app baseline; not rerun in the same controlled comparison. |

Transcription and playback add separate cost: `gpt-transcribe` is listed at approximately $0.0045 per minute. `gpt-realtime-2.1-mini` lists audio input/output at $10/$20 per million audio tokens, plus applicable text charges. The active team chain uses transcription and approved text playback; the older GPT-Live price of $0.05 per minute plus backend charges is not a price estimate for this chain. [Current pricing](https://developers.openai.com/api/docs/pricing).

A bounded comparison made twelve real Responses requests using fictional museum examples only, six per model at medium reasoning effort. It did not transmit the supplied interview or documents. Both models passed the complete eleven-topic case, adversarial shallow coverage, and four focused next-question situations. Luna initially missed a substituted reviewer role in the process map; Terra caught it. Both initially proposed an unnecessary hypothetical exception. After the process-review policy was tightened, both detected all seeded process errors and accepted a separate complete process without inventing blockers. The initial failure remains part of the evidence.

Estimated text cost across those six requests was $0.01163 for Luna and $0.07714 for Terra, including reported cache writes: $0.08876 combined. Mean elapsed time was 25.35 seconds and 19.89 seconds respectively. These are individual component-call observations, not interview prices or production latency promises. Luna was cheaper, not uniformly faster. Cache writes are priced separately and reasoning tokens are already included in output usage. [Prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching), [reasoning usage](https://developers.openai.com/api/docs/guides/reasoning).

The local comparison, raw responses, request ledger and corrected cost calculation are retained privately under `work/agent-team-2026-11-03/`. There was one sample per case and one prompt-revision rerun, with no statistical reliability claim. The cases used component prompts; they did not benchmark full browser orchestration, the document analyst, images, long contexts or physical audio. The final conversational response uses its configured application reasoning setting, so the medium-effort comparison is not a controlled measurement of every deployed call. Terra's document assignment is a capability-based starting choice, not a document-benchmark win.

A separate four-request smoke test of the **0.21.0 pipeline** then exercised one actual `Coordinator.interview` turn with the same fictional local-“No” account. The configured models ran each expected stage once, returned valid results, retained ten incomplete sections, and asked “What starts the regular packet preparation?” Only the supported purpose section was captured. Speech was authorized as a question and completion remained blocked. The test used the application's actual low-effort lead and medium-effort reviewer settings. Sanitized evidence is retained as `coordinator-smoke-result.json` and `coordinator-smoke-review.md` in that private work directory.

That coordinator turn took 56.187 seconds and an estimated $0.010391275 in text charges. The coverage call took 46.250 seconds and dominated the wait despite the two reviewers running concurrently. This is a material conversational latency limitation, not a smooth-voice performance result. The smoke test called the coordinator directly; HTTP/browser behavior, transcription and physical playback were not part of that provider run. The twelve-call model comparison and this separately authorized four-call smoke test are distinct evaluations.

The **0.22.0 pipeline** reduces request count, keeps independent final checks parallel, and uses deterministic code for constrained acknowledgment/confirmation transitions. This follows current [OpenAI latency guidance](https://developers.openai.com/api/docs/guides/latency-optimization). Prompt caching can reduce repeated-input work but cannot substitute for evidence-bound review freshness. [Prompt caching guidance](https://developers.openai.com/api/docs/guides/prompt-caching).

Eleven additional fictional-only requests tested the revised flow. The same ordinary case took 6.797 seconds with one call, an observed 87.9% reduction. A complete positive account reached its acknowledgment in 12.688 seconds; the parallel completion review then took 46.500 seconds. Both reviewers passed, with explicitly cited lifecycle/checks summary repairs. Final confirmation took 0.016 seconds with zero provider attempts, enforced by a callback that would fail the test if invoked. The eleven requests cost an estimated $0.03598495. Initial handoff-priority, summary-repetition and unattached-materials failures are preserved alongside their fixes and follow-ups in `work/response-latency-2026-11-03/`. These individual samples do not establish latency percentiles or population accuracy; final review remains a noticeable deliberate pause. [Current build verification](BUILD_VERIFICATION.md) records the full automated and browser checks.

Focused automated suites cover the local boundaries:

- [`test_agent_team.py`](../tests/test_agent_team.py): evidence immutability, source authorization, budgets, truthful events, cancellation, stale results, dimension completeness and confirmation.
- [`test_interview_orchestrator.py`](../tests/test_interview_orchestrator.py): premature closing intents, process blockers, new corrections, explicit stops, review failures, document-source authority and HTTP endpoints.
- [`test_agent_team.cjs`](../tests/test_agent_team.cjs): status-only rendering, old-run rejection, safe text, conditional document role and the distinction between finished work and complete coverage.
- [`test_controlled_voice.cjs`](../tests/test_controlled_voice.cjs): fake microphone/recorder/playback boundaries, authorization, stale response rejection, cancellation, silence, failed transcription and retained accepted text. These are not physical-audio tests.
- [`test_agent_experience.cjs`](../tests/test_agent_experience.cjs): actual app routing, status ownership, controlled-voice selection, exact reader-transcript checking, playback completion and cancellation across the app/media boundary.

Real Chrome rendering was checked at 1440×1000, 1280×720, 414×896, 320×740 and 740×390. The checks exercised actual served assets, an empty start, queued/running/completed team states, role disclosures, reduced motion, a blocked final-check control, and horizontal overflow. The model response boundary was a declared fictional fixture; that browser run did not send provider requests or test physical audio. Local evidence is retained in `work/agent-team-2026-11-03/browser-verification.json` and the adjacent screenshots.

Broader held-out evaluation should retain both hard negatives and complete positive accounts: the system must reject assumptions and still allow a sufficiently explained interview to finish. Evaluate precise findings and questions, not only the final blocked/allowed boolean. More expensive models or additional agents do not replace those checks. [OpenAI evaluation guidance](https://developers.openai.com/api/docs/guides/evaluation-best-practices).
