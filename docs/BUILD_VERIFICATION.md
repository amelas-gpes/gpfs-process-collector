## Development checkpoint — 2026-11-04

This repository snapshot includes the managed interview team, private evidence-bound fact memory, conditional stronger-model reconciliation, completion gates, controlled voice, document source-freshness checks and interface recovery fixes. It retains version 0.22.0; this checkpoint is not a completed readiness assessment or a claim of a bug-free release.

Immediately before publishing, **571 Python tests and all 16 JavaScript suites passed**, including the completion/cancellation boundaries, document authorization, 141 UI-state checks and workflow-layout scenarios. These local regression suites use simulated provider/media boundaries. Existing Python and Node runtimes were reused without downloads or installs. Private test results remain in ignored local work directories.

Earlier real-provider evaluations demonstrated that a fully explained fictional account can pass review, confirm completion with zero additional model calls, and reopen when new uncertainty appears. They also exposed remaining question-priority and source-interpretation issues. The full 43-entry process-library evaluation and held-out acceptance pass are incomplete. Workflow and draft reviews still showed omitted source conditions and recovery duties; a targeted draft-audit repair remains unfinished and is not included in this snapshot. Passing structural and provenance checks does not establish semantic accuracy.

Rendered browser and synthetic-audio checks were performed during development, but no new browser rehearsal was performed for this publishing checkpoint. Physical microphone, speaker quality and room/device interaction remain unverified; the user was unable to perform that check. The [demonstration guide](DEMO_GUIDE.md) records the pending hands-on checks. Historical entries below describe their own tested builds and previews, not a source-matched running instance of this snapshot.

## 0.22.0 responsive interviewing and explicit completion review — 2026-11-03

Ordinary turns use one lead call and server-owned topic memory. Important current ambiguities and volunteered second issues take priority; otherwise the next untouched section is preferred. Candidate full topics remain visibly provisional. When all required sections appear explainable, one acknowledgment precedes the two parallel specialist calls. The application selects their useful follow-up or the fixed final omissions check without another lead call. An unchanged explicit answer to that actual check reuses the successful evidence-bound review with zero further provider requests. Required gaps, unsupported assumptions, failed reviews and new substantive evidence still block completion.

Opaque capture tokens and review tickets bind context, transcript and authorized document state. Repeated requests coalesce; explicit review retry retains the successful capture. Cancellation, changed files and overlapping newer answers invalidate stale results. Large-document HTTP tests verify stable retrieval across the acknowledgment and final confirmation while changed access or archive state blocks reuse. Managed coverage review can explicitly publish a fully cited corrected summary when the participant already supplied the omitted facts; missing testimony cannot be repaired by assumption. Reported materials can be explained without uploading them, with their unreviewed status preserved.

The interface shows reviewers on standby during ordinary turns, amber “Captured · awaiting review” topics, and actual review activity after the acknowledgment. The wait message is “Checking the recorded topics and process…” for typed and voice use. Ordinary workflow refreshes occur when Workflow is visible. Browser fixtures verified one acknowledgment before review, no background map/reviewer call on routine turns, no official covered-count flash, disabled premature wrap-up, and no duplicate review on final confirmation.

Validation passed **466 Python tests**, **16 JavaScript suites with 519 checks**, and **13 workflow scenarios across 26 ELK layouts**. Installed Chrome passed actual rendered checks at 1440×1000, 1280×720, 414×896 and 320×740, without page errors or horizontal overflow. Browser responses used explicit fictional fixtures. Physical microphone, playback quality and spoken end-to-end latency were not tested.

Eleven bounded real-provider requests used fictional process accounts only, costing an estimated **$0.035985** in standard text usage. The same ordinary local-“No” fixture fell from **56.187 seconds / four calls** to **6.797 seconds / one call** (87.9% lower observed elapsed time). Initial checks exposed a skipped current handoff, repeated testimony after summary compression, and unnecessary blocking on unattached materials; their failures were retained and the policies repaired. The corrected handoff question passed in 7.094 seconds. The final positive candidate took 12.688 seconds, the parallel review took 46.500 seconds, and exact final confirmation completed in 0.016 seconds with a provider callback guard proving zero attempted requests. All eleven sections passed; lifecycle/checks summary repairs carried explicit participant citations. These are individual observations, not a latency percentile, population accuracy estimate or guarantee that every interpretation is correct. The deliberate completion review remains a noticeable pause.

Existing Python, Node, document parsers, Playwright and installed Chrome were reused with no downloads or installs. The source-matched preview is `http://127.0.0.1:8894/` (build `625a13a0abb89b156399bbeb68dd4b5ee44030f959d993ec531d11d7170f7bca`). Private inputs, initial failures, final results, logs, screenshots and reuse receipts remain in `work/response-latency-2026-11-03/`, excluded from Git. See [agent architecture](AGENT_TEAM.md) for the current flow and evidence limits.

## 0.21.0 managed interview team — 2026-11-03

Three core roles now share an evidence-bound coordinator: the lead interviewer, coverage reviewer and process reviewer. An on-demand document analyst interprets authorized sources. Current and legacy HTTP interview routes use the same completion permit. Required dimensions, material process contradictions, incomplete reviews and stale results block closure. A final global omissions check and an explicit response are required for full completion. Explicit stops and evidenced unavailable-only gaps remain partial captures. Empty starts make zero provider calls and show reviewers on standby.

Controlled voice transcribes a recorded answer, reviews the next response and validates its authorization before reading it. The AI reader buffers audio and compares its returned transcript with the approved text before playback. Playback completion precedes microphone reopening; cancellation and changed evidence prevent stale speech. The direct-live HTTP session endpoint returns 409. The team panel displays actual role events, expandable descriptions and conditional document activity.

Validation passed 441 Python tests and all sixteen JavaScript suites (499 checks plus thirteen workflow scenarios in 26 ELK layouts). A final focused server run passed 73 tests after public-model metadata and diagnostic-stage updates. Actual Chrome checks passed at 1440×1000, 1280×720, 414×896, 320×740 and 740×390, with no horizontal overflow or page errors. Browser model responses were explicit fictional fixtures; physical microphone and speaker behavior was not tested.

Twelve paired model requests support Luna for interviewing and coverage, with Terra retained for process review after Luna's initial missed actor substitution. Terra for document analysis is a provisional capability choice; no document-model comparison was run. A separate four-call actual coordinator test preserved ten open topics after a local “No” and returned a focused follow-up. It took 56.187 seconds and an estimated $0.01039 in text usage, so latency remains a material limitation. Model assessments remain fallible despite schema and provenance checks.

Existing Python, Node, document parsers, Playwright and installed Chrome were reused with no downloads or installs. The source-matched local preview is `http://127.0.0.1:8893/` (build `1067b71167928762863b1f9fccfdc8fe43f8c0155877242212c4d72395d0a3cf`). Local evaluation inputs, logs, screenshots and runtime receipts are in `work/agent-team-2026-11-03/` and excluded from Git. Architecture and model evidence are described in [AGENT_TEAM.md](AGENT_TEAM.md).

## 0.19.1 document timeout recovery — 2026-11-03

The reported PDF had already uploaded, indexed all 17 pages and completed its background review. A later workflow request failed after 171,672 ms; the old generic transport handler did not retain enough information to establish the exact cause. Its timing is consistent with an audit timeout.

Document workflow generation now uses a 120-second socket timeout and its independent audit uses 240 seconds. The browser allows seven minutes for their combined request and 210 seconds for the two-call document follow-up. Timeouts return HTTP 504 and explain that retained files need not be uploaded again. DNS, TLS and interrupted connections have separate messages. Bounded local diagnostics retain stage, duration and failure category without source text or credentials. Status polling no longer silently retries a failed workflow or follow-up; explicit retry or a meaningful file change can resume it.

Validation passed 355 offline Python tests and 147 frontend checks. An isolated live-provider replay of the same 17-page PDF completed upload, all-page review, an audited workflow in 203.25 seconds, and a follow-up in 23.34 seconds. This was a fresh document-only test interview, not a replay of the original 71-turn interview. It verifies successful processing on that run, not a guarantee against future provider delays or a semantic audit of every resulting workflow item. The replay loaded the patched backend before the version label changed from 0.19.0 to 0.19.1; its logs retain that earlier label.

The canonical preview was restarted at 127.0.0.1:8774, verified against the current source build and refreshed while its browser interview was empty. Existing settings, saved interviews and document stores were preserved. Evidence is private under `.local/upload-error/`; the original PDF hash is unchanged. Existing Python, Node and parser packages were reused, with no downloads or installations.

## 0.19.0 coordinated file intake — 2026-11-03

An accepted upload now starts one coordinated intake. The app acknowledges once, stops live audio and releases the microphone, drains final captions, waits for the active files to finish reviewing, then audits and commits notes and workflow together. Only after that baseline is accepted does it request one source-grounded follow-up. Quick analysis no longer sends competing questions or repeated file-context batches into live voice. Continue talking starts a fresh session with the current authorized file scope once.

Overlapping uploads share the intake; new file versions, removals, parking, retries and interview changes invalidate obsolete work. A failed review or baseline retains the prior capture; a failed follow-up retains the new baseline. Error states offer Assets, retry and continuation with the current capture. Intentional request cancellation is distinct from a timeout, including late responses after intake finishes. The server independently requires reviewed scoped sources and validates the submitted baseline before allowing a document follow-up. Partial review coverage remains explicit.

Offline validation passed the full Python suite (344 tests), followed by the updated HTTP server suite (69 tests), including a new check that every deferred script in the real served HTML returns its actual JavaScript source. Frontend validation passed 412 checks across thirteen suites, another 38 usability checks, and thirteen workflow scenarios across 26 real ELK layouts. Coverage includes overlapping uploads, final-caption draining, baseline-before-question order, stale-response rejection, microphone-permission races, empty/parked/error recovery and scope-only voice continuation. These tests use simulated provider and media boundaries.

A real browser CSV upload confirmed one acknowledgment, a quiet review, an accepted eight-step/ten-connection baseline, then one follow-up. The first question repeated a supposed gap already partly answered by the file. A follow-up-only replay with stronger guidance still failed that semantic check. The final guidance makes exact source facts take precedence over derived gaps and distinguishes known actions/owners from unknown transfer methods; the document question audit now uses the configured workflow audit model. A second real replay passed by acknowledging Finance's documented recording role and asking only how it receives approval. A third replay in a separate QA-to-Warehouse scenario also preserved the stated owner/action and asked only how the release reaches Warehouse. The changed follow-up suite passed 13 tests and the server suite passed 69 tests. These replay results do not claim perfect questions for arbitrary files.

The final fresh browser upload passed the full review/capture/follow-up sequence on the final build. The transcript contained exactly one acknowledgment and one question, with eight documented memo topics and an eight-step/ten-connection workflow visible before continuation. The question acknowledged the documented approval prerequisite and asked about the unstated director-denial outcome. The saved session and rendered workflow retained the approval-to-Finance route. The progress UI was inspected in Voice and Transcript at 1280×720 and 414×896, with no horizontal overflow on the phone-sized view. Private test logs, synthetic inputs, failed and successful provider probes, saved interviews, browser screenshots and runtime receipts are retained under `.local/document-intake/` and excluded from Git. Existing Python 3.12.14, Node 24.22.1, installed document parsers and bundled ELK/browser assets were reused. No dependency or resource acquisition was needed. Physical microphone and speaker behavior remains unverified.

## 0.18.0 transcript workspace — 2026-11-03

Transcript now uses one readable conversation column with a compact header. Find opens on demand with contextual match navigation; Export offers Markdown and JSON in a single disclosure. File acknowledgements appear as compact activity, while interviewer questions and participant answers have distinct typography and spacing. Full message text, chronology, evidence IDs and export contents remain intact.

The reply card follows the last message instead of sitting at the bottom of an empty viewport. It supports typing immediately, an explicit first-message send, reviewed dictation and live voice. Opening Transcript alone does not start a session or call the model. Stop and Mute move into the fixed transcript header during live voice; the same control nodes return to the reply area afterward. Unsent text and focus survive view changes. Long histories offer Latest message immediately, and source-link round trips preserve the reader's location.

Browser checks covered an empty interview, the saved two-message payment interview, and a 26-message synthetic interview containing a 1,966-character response. Checks exercised search and keyboard dismissal, both real export downloads, source navigation/return, saved unsent text, view switching, and desktop/phone/landscape layouts at 1280×720, 414×896, 320×740 and 740×390. The payment conversation and reply fit without a conversation scrollbar at 1280×720 and 414×896. Long messages retained their full text with no horizontal overflow or clipped message boxes. A short viewport uses the single conversation scroll area.

All twelve JavaScript suites passed: 365 checks plus thirteen workflow scenarios across 26 layouts. New checks cover new-session replies, passive navigation, search/export focus, live-control reparenting, voice-stop focus recovery and long-history navigation. These checks used simulated voice state; no physical microphone, speaker or live model call was exercised. Private screenshots, browser metrics, downloads, saved-session fixtures and runtime reuse receipts are retained under `.local/transcript-redesign/`, excluded from Git. Existing runtimes and bundled assets were reused with no downloads or installs.

## 0.17.0 interview workspace — 2026-11-03

Voice, Transcript and Workflow now sit at the top right of the process workspace. Settings and Save copy are in the three-dot menu. The sidebar has Notes, Summary + Parked and Assets tabs, with a single upload/file-management surface and expandable file details.

Voice controls move with the existing controls and composer beneath the complete AI response. Switching views preserves unsent text, listeners and live-session state. Fixed response heights and fade masks have been removed; long text uses only the outer voice panel's scroll area. A new response begins at the top, while streaming the same response preserves the reader's position. Source loading and document polling preserve keyboard focus.

Browser checks covered the saved payment interview at 1280×720, 414×896, 320×740 and 740×390. The normal response and controls fit without voice-panel scrolling at the checked compact sizes. A 1,966-character synthetic response retained its complete text and ending, with one necessary outer scroll. Settings focus, Save copy download, unsent-text retention across views, expanded workflow, and sidebar access were exercised. No physical microphone or provider calls were used for these UI checks.

Final automated verification: 333 Python tests passed with no failures/errors, plus 351 JavaScript checks and thirteen workflow scenarios in 26 layouts. Earlier backend runs retained a Windows connection-reset error on rejected requests and two document-worker timing failures. The rejection path now discards only bounded fixed-length bodies before returning the unchanged 403, without parsing or routing unauthorized content. Four boundary checks cover that behavior; the final full run also passed both timing cases. Earlier results remain in the local receipts.

Evidence and screenshots are retained under `.local/header-refinement/` and excluded from Git. Existing Node and Python runtimes were reused; no dependencies or resources were downloaded.

## 0.16.0 document-led capture — 2026-11-03

The supplied interview identified a process in its uploaded file but repeatedly asked the participant to identify it again and left every memo topic unknown. Investigation found that workflow/draft calls did not receive document context, question auditing dropped that context, and evidence validators only accepted participant turns or intake context. A short voice summary was therefore not enough to populate the actual capture.

The revised pipeline carries exact scoped excerpts into interview, question audit, workflow, workflow audit, draft and draft audit. Documentary citations remain separate from participant answers through rendering, saved interviews, exports and knowledge review. Documented notes remain distinguishable from confirmed practice. File readiness can start capture before background review completes; unchanged review progress does not repeatedly rebuild the map. Late file-purpose/removal responses cannot overwrite current work.

Drag/drop uses the existing upload pipeline, validation and error UI. Offline cases cover nested drags, text drags, folder rejection, outside-workspace navigation prevention, reset, suspend, disabled upload and cleanup. The actual browser upload, automatic capture, source dialog and saved-session restore were exercised with the supplied PDF. The browser automation interface does not support an OS file drag; that physical gesture has not been exercised. Physical microphone/playback and end-to-end spoken behavior were not exercised in this run.

Local extraction delivered all 11 pages and 29,606 source characters. Provider replay exposed failures beyond transport: an incomplete model response, regional approval leakage, unsupported retry routing and an omitted completion signoff. Those failed artifacts are retained as failed evidence; stronger prompting alone did not establish accuracy. Document-led map updates now receive an independent source/scope audit before the accepted diagram changes. A full-map audit failed after its configured request time limit. The audit now returns corrections to the unpublished candidate instead of repeating the entire map; its separate token/time allowances account for deeper source review.

Final source-check probe: a fresh GPT-5.4 audit corrected the previously saved real-model candidate, removing the imported European approval, retaining required AFC-or-higher signoff in the closure activity/criteria, removing the unsupported resubmission destination, and restoring source-grounded manual-work observations. The corrected result has 21 steps, 21 connections and eleven documentary memo topics. This is a source-content test, not confirmation of actual operating practice or owner approval. The audit reused the saved initial candidate; it did not rerun initial generation. Its diagnostic input also contained the same source text in a display catalog, so its elapsed time is not a production performance benchmark. Earlier smaller-model results remain marked as failed semantic probes.

Automated verification: all eleven Node suites passed (328 checks, plus thirteen diagram scenarios in 26 layouts). The final Python run executed 329 tests: 327 passed and two deliberately cross-origin rejection tests hit intermittent Windows 10053 connection resets, with no assertion failures. Both affected HTTP suites passed a focused recheck (42 tests). The full-run receipt retains those errors; the rechecks are separate. Source/audit isolation, model separation, exact citation retention and atomic correction checks passed.

Validation receipts, private source replays and browser evidence are kept under `.local/document-experience/` and are excluded from Git. `runtime-reuse.json` there records the fresh read-only preflight and reuse of existing Python 3.12.14, pypdf 6.10.0, openpyxl 3.1.5 and Pillow 12.3.0. No dependency, browser or runtime download was needed.

## 0.15.0 workflow quality — 2026-11-03

The workflow schema, working capture, draft generation/audit, saved-session normalization, review
editor and renderer now preserve eleven component types. Alternatives merge independently of
all-branch synchronization. Extraction guidance distinguishes a wait's entry from its release,
early responses from deadline expiry, and reported rework from an unknown decision criterion.
Incomplete or contradictory routing produces open questions rather than invented dependencies.
The built-in and saved invoice example now demonstrate five types without changing their account.

The renderer measures and wraps titles, owners, systems and route labels before ELK layout. Shape
height grows with its content; decision/gateway text fits inside the diamond, and document connectors
meet the wavy boundary. Professional shape conventions, restrained component colors, graph-specific
keys and source-linked route details replace the earlier activity/decision-only presentation.
Navigation now supports dragging/pinching from nodes, full overview at the 80-node limit, initial
vertical layout on narrow screens, and clean exports without transient selection highlighting.
Missing assets or layout errors show full captured facts/routes with a local retry instead of a
misleading simplified diagram. Retry makes no model request and retains unsent interview work.

**610 automated checks passed: 305 Python and 305 frontend.** Frontend suites cover UI/recovery (86),
real-ELK renderer/interaction (47), Live controller (41), documents (32), knowledge (32), presence (26),
transcript export (13), memo (10), example (9) and voice frontend (9). Changed source syntax and diff
whitespace checks passed. Sixteen new Python checks cover component contracts and routing diagnostics.

**13 fictional process fixtures / 26 real-ELK layouts passed**, covering all eleven types, binary and
multi-way choices, nested decisions, all-branch joins, alternative merges, correction loops,
self-loops, early response/timeout, collapsed procedures, records/documents, disconnected fragments,
long Unicode labels and 80 components. Checks preserve every node/connection, route order and full
text; they detect node/label collisions and connectors crossing unrelated nodes or route labels.
The suite inspected 690 text blocks and 869 wrapped lines across both orientations.

**Real-browser acceptance: 130 layouts / 260 normal and expanded views passed.** The actual app and
bundled ELK were exercised in both orientations at five iframe presets: 1440×900, 768×900, 360×780,
320×568 and 844×390 (content viewports are two pixels smaller because of the test frame border).
Checks inspect actual SVG glyph bounds and shape containment, text preservation, topology/export,
horizontal overflow, the canvas portion visible through clipping ancestors, and access to controls.
The first expanded sweep found 28 genuine canvas-clipping failures on short phones and a gap-heavy
landscape case. Compact controls/header spacing and placing gap notices after the canvas resolved
those cases; the failed report is retained. Visual review also checks the controls and readable views.

**Model review: ten latest fictional cases passed their routing/component/source-attribution rubrics
after twenty real provider requests across refinements.** Earlier outputs exposed omitted rework,
incorrect wait transitions, unsupported ownership/recording details and alternatives miscounted as
ALL-join prerequisites. Those failures were retained and prompted the specific policy refinements.
Five latest cases used the final eleven-type policy; five unaffected earlier cases retain their
reviewed outputs and prompt fingerprints. The final scoped-removal check uses a clearly identified
equivalent synthetic baseline with an explicit merge; it preserves stable IDs, that merge and the
rework route while removing only the withdrawn desk branch. The model can use a faithful shared
decision instead of a redundant merge, so these checks do not claim it generated every shape.

Local evidence is in ignored `.local/workflow-quality/`: geometry, browser, Python/frontend and model
results, per-case semantic review, retained earlier attempts, screenshots and SVG proofs. Browser
fixtures are isolated from saved interviews and forbid provider calls. Provider checks used only
fictional text and existing configuration. No packages, runtimes, browsers or fonts were installed.

These checks establish the observed scenarios, not perfection for every possible process. Large
maps need pan/zoom or path navigation; fitting all 80 components on a phone is an overview, not a
reading view. The map is not a BPMN execution engine, formal swimlane editor or nested-subprocess
editor. Physical microphone/speaker behavior was not retested in this workflow-focused change.
See [workflow diagrams](WORKFLOW_DIAGRAMS.md) for the behavior and supported bounds.

## 0.14.0 purposeful curiosity — 2026-11-03

Review of the saved backlog interview and two documentary-simulation interviews found useful local
details that could have been explored before moving to another step or topic. Earlier policies
emphasized avoiding repetition but did not clearly distinguish naming an action from explaining its
mechanism. The question audit could keep a generic progression question simply because it was new.
These are opportunities at particular checkpoints, not a claim that every final account omitted
the details. Private transcripts and the detailed review remain local.

A shared curiosity policy now reaches typed interview generation, its question-only audit, direct
voice instructions and delegated assistance. The foundation mirrors it, and voice instructions carry
a concise eleven-topic guide. The audit ranks an unanswered local information need against its
candidate, with medium reasoning. A named initiating event is retained as partial understanding when
its mechanism is unknown. No-repeat, unavailable-detail/resolver, stopping, correction-scope and
documentary-provenance protections remain active. See [policy and examples](INTERVIEW_CURIOSITY.md).

**466 offline checks passed: 289 Python and 177 frontend checks** (75 UI/recovery, 41 Live-controller,
38 real-ELK graph, 10 memo and 13 transcript-export). Five new Python checks verify shared prompt
wiring and question-only mutation boundaries; eight fictional fixtures define information-need
rubrics. Source syntax and diff whitespace checks passed. Independent source review found no
material blocker. Runtime/packages/resources were reused without installations or copied runtimes.

**Final real-model review: 14/14 outputs passed** against their information-need rubrics: eight
question audits, two full interview-generation/audit flows, and four text replays of the Live prompt.
They cover unexplained waking mechanisms, already-volunteered facts, shorthand checks, exception
outcomes, unavailable detail and resolver, irrelevant trivia, targeted corrections and explicit stops.
For example, the final questions include “What usually wakes you up?” and “What do you check in the
file?” The initial iteration had one vague mechanism question and one missed-depth audit; its
outputs were retained, the audit priority was strengthened, and the final set was independently
reviewed again. Schema validity alone was not counted as question quality.

The final questioning replay used 16 provider requests. Including its first iteration and four
passing workflow model regressions, this refinement used 36 real requests with fictional fixtures.
The workflow regressions still capture the initial four steps, preserve four after a first-step
correction, retain three after a targeted deletion, and allow an explicit full withdrawal.
Local inputs/outputs, prompt/source fingerprints and semantic-review reasons are in ignored
`.local/curiosity-review/`; earlier workflow evidence is retained separately.

These samples do not establish perfect questioning or exhaustive capture. Live-prompt replays used
the configured text model; they are not actual GPT-Live conversations or physical audio tests.
The provider/model identities, eleven-topic readiness gate and evidence contracts are unchanged.

## 0.13.2 progressive live updates and server lifetime — 2026-11-03

The follow-up demo exposed a gap in the earlier verification: individual model updates passed, but
continuous caption growth was not tested end to end. Every new user delta invalidated a completed
capture, and final-only/debounced scheduling could postpone the next one. Medium reasoning increased
the time window for this starvation. Both the map and memo could stay empty while speech continued.

The app now starts bounded checkpoints on nonfinal captions, with one request in flight and one
latest update queued. It can publish a completed checkpoint when its source text still exists as
an unchanged prefix, then catch up with later answers. Rewritten/removed evidence and prior-session
responses remain rejected. Map and memo publish atomically, pending state remains visible, and
readiness is suppressed until the latest evidence is processed. Background failures produce a
deduplicated notice visible in Voice.

The local service was also unavailable during investigation. Its earlier exit reason was not logged;
the aborted-socket traceback was confined to a request thread and does not establish a main-process
crash. Windows probes confirmed that tool-launched children inherit nested kill-on-close jobs; the
permitted breakaway flag did not remove the outer lifetime restriction. No job/security settings were
changed. The launcher now offers `--foreground` for an intentionally retained managed execution
session. Ordinary desktop behavior is unchanged. JSON/asset writes handle disconnected clients
without attempting a second response. Bounded, payload-free lifecycle/workflow metrics are saved
under ignored `work/server-lifecycle.jsonl`, with one rotated previous file.

**284 Python checks passed**, including seven new disconnect/diagnostic cases and the foreground
launcher regressions. **164 frontend checks passed:** 75 UI-state/recovery, 41 Live-controller, 38
real-ELK workflow and 10 memo checks. Changed source syntax and diff whitespace checks passed.

**Real browser + HTTP integration passed:** 39 synthetic caption revisions streamed for 11.428s;
the first real SVG diagram rendered at 3.136s, while captions were still arriving. Five delayed local
HTTP checkpoints retained the prior map, used a maximum of one concurrent request, and converged to
all three actions plus the memo at 15.227s (`applied` = `revision` = 39). This harness used the actual
app script, DOM and locally bundled ELK, with a delayed fictional model adapter and isolated stores.
Its control exists only in the test response, not in the production app. The owned test server and
tab were closed afterward. Evidence and screenshot: ignored `.local/realtime-recovery/`.

**Real-provider HTTP smoke check passed:** the running 0.13.2 service returned HTTP 200, three workflow
steps and all eleven memo topics for a fictional invoice account in 13.281s. One provider request was
made in this follow-up. This measures one request, not a latency guarantee. Physical microphone and
speaker behavior were not exercised. The previous correction/removal safeguards remain included.
The canonical preview was reopened, with the server retained in a managed foreground session.

## 0.13.1 targeted workflow corrections — 2026-11-03

The saved backlog-refinement account confirmed a scope error: a first-step correction to getting water
also discarded later idea prioritization, updates and Jira/Confluence references. Workflow generation
previously received no current graph and returned an unrestricted complete replacement.

The workflow-only request now includes a detached, validated previous capture. The model returns
explicit upserts/removals; omission preserves existing graph components and memo topics. Removals need
an existing target, reason, participant evidence and exact source quote. Stable IDs, disjoint edits,
incident-edge cleanup, no invented rejoin and atomic merged validation are enforced locally. Shared
interview instructions scope corrections to affected details. The workflow call uses the existing
configured model with medium reasoning effort. See [the update contract](WORKFLOW_UPDATES.md).

**450 offline checks passed:** all 275 Python tests; 73 UI-state/recovery, 41 Live voice-controller,
38 workflow/real-ELK, 10 memo and 13 transcript-export checks. Changed JavaScript syntax and Git
whitespace checks passed. Thirteen dedicated Python regressions cover targeted replacement, omitted
facts, stable IDs, branch/parallel-edge removal, explicit full withdrawal, changed caption text,
invalid evidence/quotes, atomic rejection and memo withdrawal. The UI regressions verify prior-capture
allowlisting, deep detachment, workflow-only requests and cleared-session isolation.

The existing overlapping-acknowledgment voice test had a stale single-caption expectation. Its
assertion now checks that the entire participant sentence and both fragments survive across the
separate chronological captions. No voice-controller code changed.

**Final real-model check: 4/4 fictional scenarios passed** with `gpt-5.4-mini`: initial capture (4
steps), first-step correction retaining later work/materials (4), removal of only the named action
without an unsupported rejoin (3), and explicit whole-account withdrawal (0). Earlier prompt iterations
included conflicting model edits/removals caught by validation and an incomplete initial extraction;
those attempts remain saved separately. Across the three iterations, ten real provider requests were
made using fictional fixtures. The final four use the shipped prompt and medium reasoning setting.
The key stayed in the existing local configuration and was never printed or sent to the browser.

Local model inputs, outputs and attempt history are in ignored `.local/workflow-correction/`; the
bounded runner is `.local/check-workflow-model.py --live`. A new preflight reused the existing Python
3.12 runtime and installed parser packages, with no downloads, installations or copied runtimes.
The canonical server was restarted and the existing empty preview reloaded. This does not establish
physical microphone/speaker quality or guarantee correct interpretation of every ambiguous correction.
Prior-capture payloads still share the normal bounded request limit; oversize/invalid updates fail
without truncating or replacing the accepted capture.

## 0.13.0 transcript review exports — 2026-11-03

Dedicated transcript Markdown and JSON downloads are available before a draft exists, via the compact Transcript toolbar and More menu. They retain all stored turn IDs, roles and text; distinguish file-context events from participant evidence; and include the eleven-topic memo snapshot, closure status, parked/open questions and AI review guidance. The explicit sharing allowlist omits private session capabilities, provider settings, unsent text and document bodies. The private Save format remains separate. Exports do not mark the interview saved or make a provider request. See the [format and usage guide](TRANSCRIPT_EXPORT.md).

**198 focused offline checks passed, 0 failed, 0 skipped among executed checks:** 13 new transcript-export groups; 31 non-voice UI/recovery, 9 complete-example, 10 memo, 32 document UI, 30 Admin UI, 61 server and 12 launcher/portability checks. The new suite runs the actual export functions against synthetic states: pre-draft/offline export, all eleven unknown topics, normalized uncertainty, explicit not-applicable status, file receipt versus file-related question, 400 turns, exact Unicode/multiline/fenced content, private field omission, detached/read-only snapshots, capture-in-progress flags, stale draft questions, empty guards and both MIME/filename download paths. Syntax and whitespace checks also pass. Voice-specific suites and real provider calls were excluded.

Browser verification used the built-in fictional example in a separate updated preview at `http://127.0.0.1:8782/`, preserving existing interview tabs. The actual downloaded Markdown (14,857 bytes) and JSON (18,098 bytes) retained all 26 messages exactly and all eleven memo topics. The More-menu Markdown path downloaded correctly and returned focus to the menu toggle. Export was disabled for an empty transcript. Desktop plus 390×844, 320×568 and 844×390 layouts had no page overflow; the internal transcript remained visible and export controls stayed within the screen. Browser console warnings/errors were empty. Local screenshots and downloaded copies are in ignored `work/transcript-export/`.

No new interview answers, voice sessions, microphone/speaker access or paid AI requests were used. Physical devices and screen-reader certification were not tested. Memo assessments are last-recorded snapshots, not historical per-turn evaluations or proof of completeness, and live captions may be provisional. This change provides material for later human/AI review; it does not automatically analyze or train on exports.

## 0.12.0 bounded Admin and completion audit — 2026-11-03

All fifteen usability recommendations are implemented, with the final reliability/accessibility audit fixes. Admin now requests server-paged metadata and lazy selected details rather than a whole-store snapshot. Histories, aliases, members, related routes and entity/process choices have independent pages. Exact source excerpts still open the complete originating transcript and restore focus on return. Oversized graphs require refinement instead of hiding topology. The launcher detects an older running build without interrupting an existing interview.

The completion review also fixed selected graph filters leaking neighbors, confirmed temporal direction, containment source references, malformed saved-file state replacing the current interview before validation, Unicode search offsets, reduced-motion navigation and keyboard/modal focus. Mobile Admin navigation keeps its selected tab visible after resize. Independent reviewers repeated the source pass after these fixes and found no further concrete defects in the reviewed scope. This does not establish that the application is bug-free.

**368 offline checks passed, 0 failed, 0 skipped among executed checks:**

| Suite | Passed |
|---|---:|
| Server routing/evidence/lifecycle | 61 |
| Documents, service and HTTP | 51 |
| Knowledge core, bounded Admin, AI adapter, HTTP and example isolation | 71 |
| Launcher/portability/build identity | 12 |
| GPFS asset/API | 4 |
| Non-voice UI and recovery | 31 |
| Document UI | 32 |
| Admin UI | 30 |
| Memo UI | 10 |
| Workflow with real local ELK | 38 |
| Complete example | 9 |
| Deterministic GPFS visual component | 19 |

Python commands use the existing runtime with `-I -B -m unittest discover -s tests -p PATTERN`, with patterns `test_server.py`, `test_document*.py`, `test_knowledge_*.py`, `test_portability.py`, and `test_gpfs_api.py`. Node commands are `tests/test_ui_state.cjs --usability-only`, `test_documents_frontend.cjs`, `test_knowledge_ui.cjs`, `test_memo_ui.cjs`, `test_workflow_graph.cjs`, `test_example_complete.cjs`, and `test_gpfs_presence.cjs` in the tests directory. Changed JavaScript syntax and diff whitespace are checked separately. Voice-specific suites were excluded; deterministic visual levels do not use audio hardware or a provider.

Bounded backend regressions include 107 long accounts, 100 group members, 74 aliases and 703 review records, exact selected details, literal/Unicode filters, same-revision system matches, both graph limits, selected-process scope, cyclic downstream and targeted document validation. The real HTTP regression proves page/detail requests do not invoke the legacy full-store snapshot and rejects invalid paging/filter/revision types. No retained records are truncated.

Browser QA used a disposable fictional 33-process store on a separate port and the actual updated app at `http://127.0.0.1:8780/`. It verified second submission/process-choice pages, complete 11-step/11-memo/26-message details, exact source highlight/return focus, independent review-history and alias pages, a 2,145-node graph refusal, and a complete selected 65-node/78-link graph. Desktop and 390×844 layouts had no page horizontal overflow. The final app stayed at one screen on desktop; resizing an open memo detail to phone returned focus to the visible memo button, with all eleven topics accessible. Resizing Admin kept the active Graph tab visible without changing focus. The actual 20,214-byte Markdown download retained all 26 messages verbatim and all eleven step titles without search markup. Screenshots and the downloaded artifact copy are local in ignored `work/bounded-admin-ui/`.

No new interview answers, real provider requests, microphone/speaker access, voice sessions, or actual business-process test data were used. Original tabs and unsaved interviews were preserved; only owned disposable previews were restarted. Full screen-reader certification, live model quality, physical audio, production hosting/identity and disaster recovery remain unverified. Offset pages may shift under concurrent writes; lists/related histories use the explicitly disclosed last recorded source status, with selected connection/detail/graph/review revalidation. Already-running parser/provider callbacks remain non-cancelable. See the [audit](APPLICATION_AUDIT.md) and [Admin contract](ADMIN_API_CONTRACT.md).

## Application audit, first reliability batch — 2026-11-03

Version 0.11.0 includes fixes from independent HTTP/launcher, document, knowledge, and frontend audit passes. [Audit scope, architecture, findings and remaining work](APPLICATION_AUDIT.md) keep the full active objective visible.

Fixed bounded HTTP connections/header/body reading/upload admission, graceful HTTP drain before stores close, startup cleanup, strict evidence and finite-JSON validation, immutable request-intent receipt recovery, retry/worker races, snapshot query batching, large-workbook formula handling, document cursor/completeness/error-worker bugs, browser cache restoration, conflicting file actions, session import locking, stale file-purpose capture, and stale submission/Admin callbacks. Title-only edits no longer schedule paid extraction. Source-proven Live send/timer/callback/chronology defects were corrected by static review.

**324 checks passed, 0 failed, 0 skipped among executed checks:** 175 Python checks (61 server, 51 document, 51 knowledge, 8 portability, 4 asset/API); 130 frontend checks (22 non-voice UI, 32 documents, 19 knowledge UI, 10 memo, 38 graph, 9 complete example); and 19 deterministic GPFS visual checks. The visual component uses synthetic levels, not audio hardware. Live/voice-specific test suites were excluded. The changed Live controller received syntax and source review only; these results do not validate physical voice behavior or the provider contract.

Regression evidence includes real temporary SQLite stores and local HTTP sockets, source drift/archiving/restart lost-response recovery, two SQLite instances racing one idempotency key, trickle-body deadlines, queue supersession, error-persistence failure, interrupted batch preparation, complete rereading after Revisit, unindexed chart tabs, BFCache late responses, old file-purpose questions, and immutable submission retries. Four document regressions were also run against the previous implementation and failed as expected. Snapshot SELECTs fell from 98 to 10 for 40 synthetic submissions, with all records preserved and query count constant after adding more submissions.

No real provider requests, voice sessions, microphone/speaker access, or user business-process data were used. Browser checks use the built-in fictional example in a separate preview. Existing interview tabs were preserved. Local screenshots are in ignored `work/architecture-audit/`. No hosted deployment is included.

The audit remains active. In particular, full Admin history payloads still grow with retained data; pagination/lazy detail and another integrated recovery/accessibility pass remain to be completed. Already-running parser/provider callbacks remain non-cancelable, although late analysis publication is suppressed.

## Usability and workflow improvements — 2026-11-03

Implemented the fifteen recommendations from the application UI review within the existing visual system:

1. Actionable next memo topic with explicit clarification guidance.
2. Literal transcript search, match navigation, and a return-to-latest action.
3. Source jumps with highlights, return navigation, and restored keyboard focus.
4. Readable workflow starting views and reported-path navigation with explicit branch choices.
5. Readable Admin process summaries, detailed steps, controls, variations, memo, and full transcript; optional technical record.
6. Labeled Save action and an unsaved indicator.
7. Visible Not applicable memo status without changing completion rules.
8. Sticky report contents and search, including report and section headings.
9. Named layout orientation and SVG export controls.
10. Mobile step navigation, path choices, touch controls, and focus layout.
11. Compact applied Admin filters, counts, removable chips, and a larger graph workspace.
12. Exact interview excerpts and highlighted originating answers in Admin graph/detail navigation.
13. Concise file stages/progress, visible purpose label, and Review now / Saved for later states.
14. Persistent inline errors and retry actions after three-second notices dismiss; diagram retries reuse captured data locally.
15. More readable functional copy, larger phone controls, visible focus states, and path status announcements.

Verification uses existing runtimes and fictional data. **111 focused offline checks passed, 0 failed, 0 skipped:** 16 non-voice UI/navigation checks, 38 real-ELK graph checks, 28 document UI checks, 11 knowledge UI checks, 9 memo checks, and 9 complete-example checks. The targeted UI invocation is `node tests/test_ui_state.cjs --usability-only`; it stops before the legacy simulated voice cases. These checks cover search clearing and literal text preservation, source return/focus, local layout retry, branching/correction loops, topology-preserving exports, file retry persistence, batched filters, and exact evidence navigation.

The real browser was exercised with the bundled fictional example at desktop, 390×844, and a short landscape viewport. Checks included memo gap navigation, transcript search, Review path controls, report title/heading search and clearing, source → transcript → return with step focus, applied Admin filters/chips, readable submissions, and exact Admin source highlighting. The actual Markdown download retained all 11 steps and all 26 turns without search markup. No new interview answers, file uploads, voice sessions, microphone/speaker access, provider calls, or AI credits were used. File failure/retry states were tested offline. Screenshots are retained locally in ignored `work/ux-implemented/`.

The original browser tabs and unsaved interviews were preserved; verification used a separate tab. No server schema or credential settings changed. Full screen-reader compliance, physical audio, live provider behavior, and actual large-file processing were not tested in this update. Existing hosting, identity, and operational limitations still apply.

## Complete fictional example — 2026-11-03

The built-in and saved examples now show the same fictional invoice-approval process: 26 interview turns, eleven captured memo topics, eleven fully detailed workflow steps and fourteen evidence-backed connections. They include duplicate closure, mismatches, correction loops, approval decisions, a high-value variation, risks, controls, existing materials and Treasury handoff. Empty question and parking registers now say that no items are recorded, without implying independent approval.

The real app's example, normalization and Markdown functions passed nine focused check groups. Another 101 non-voice offline checks passed (31 server, 30 graph, 24 document UI, 9 memo and 7 knowledge UI), with no failures or skips. The saved JSON passed server draft/evidence validation. In a separate browser with synthetic data, each of the eleven workflow details was opened and all six owner/system/input/output/completion/handoff fields and source references were verified; the report showed 11/11 captured. The actual Markdown download contained every turn and step, the empty-register wording and the synthetic label. No provider, voice or user data were used. The example is fictional and remains a draft requiring owner review, not a verified company procedure.

## Local company knowledge graph — 2026-11-03

Implemented a local SQLite graph with immutable process submissions/revisions, reported entities and relationships, exact employee/document-source proposal evidence, review history, retryable jobs and reviewed canonical groups. Admin APIs use a server-owned authorization boundary; local-owner access requires explicit development configuration. Submitted evidence is never used as an instruction, and proposals require review before appearing as confirmed. The status capability permits only a submitter's own revision status and is retained in explicit saved-interview JSON. See [architecture and limits](KNOWLEDGE_GRAPH.md).

**184 offline checks passed, 0 failed, 0 skipped:** 36 knowledge core/API/adapter tests, 42 document tests, 31 server evidence/routing/closure tests, 5 portability tests, 7 knowledge UI checks, 24 document UI checks, 30 graph checks and 9 memo checks. Synthetic fixtures include two roles, actual SQLite and HTTP, restart/readback, exact document sources, spoofed roles, cross-scope denial, capability isolation, review, staleness, rejected-claim retry, canonical unmerge, parallel paths, corrections, conflicts and graph direction. They use fake analyzers and no provider calls. Voice tests were not run.

The actual Admin UI was inspected with two synthetic local submissions on desktop and at 390×844; a synthetic connection was reviewed, the graph inspected, and a canonical grouping created and corrected with history. A separate fictional interview was submitted through the UI and its status refreshed to completed using the synthetic analyzer. The isolated test data were discarded. The separate owner-mode preview at port 8776 uses the real local store and begins empty; the existing port-8775 interview was not reloaded or modified.

This is not a hosted shared graph or production identity system. The model adapter and current structured-output contract have not been exercised against a live provider in this update; its quality, costs and behavior with actual company data remain unverified. Candidate and source excerpts are bounded and non-exhaustive; document source drift is detected on administrative snapshot or review, not continuously. The system does not establish semantic truth, automatic contradiction resolution, production backups, encryption at rest, multi-user hosting or operational-event ingestion.

## Synthetic complex-process stress review — 2026-11-02

Ten fictional process scenarios were evaluated with the real configured text model. Five included small CSVs through isolated document extraction and quick/background review: three relevant and two unrelated, with the unrelated files clarified and parked. The initial run used prewritten multi-turn transcripts followed by one model interview question and workflow snapshot per scenario. A continuation then supplied that actual question and a synthetic participant answer saying they did not know. All ten unanswered topics, controls and owners remained incomplete and none reported readiness. The initial 112 coded checks and 50 continuation checks passed; these counts do not establish semantic graph correctness.

Independent review found an isolated supplier-risk exception and missing parallel dependencies, a missing software rollback-to-review connection, and an unconfirmed recall investigation return rendered as an edge. A maintenance deferral edge may also infer an unsupported route. Three follow-ups repeated a question after the participant said they did not know, and one combined two information requests. Initial workflow results predate the subsequent routing-prompt update. Disconnected nodes now receive an explicit question and visible workflow warning without inventing edges; this structural check cannot detect all missing or inferred routes.

Memo prompts and local guards now downgrade captured/not-applicable findings with explicit uncertainty in the finding or cited participant answer. Later cited clarification can resolve the topic. This is conservative and can block a mixed-topic answer, while implicit uncertainty or an uncited contradiction can still be missed; it does not prove semantic certainty. Quick document relevance is retained consistently with its retrieval disposition during background review.

The live exercise used 42 text Responses calls and 188,534 total tokens, with no provider errors. It did not test voice or send real user data, PDFs, PNGs or workbooks. Separate local evidence and the complete synthetic report are in ignored `work/process-stress-report.md`, `work/complex-process-stress-results.json` and `work/complex-process-followup-results.json`. Relevant offline checks passed: 31 server, 13 document-service, 9 memo/workflow frontend, 30 graph and 24 document frontend checks. The existing open preview was not restarted; save the interview before restarting to load server changes.

## Codebase review — 2026-11-02

Reviewed the local codebase without starting voice, entering data in the user's app, or contacting OpenAI. Fixed malformed CSV quoting being accepted into an index; memo findings claiming coverage without a meaningful answer; stale workflow layouts surviving invalid replacements and camera/selection remaining after a clear; and the launcher reporting a successful shutdown while the server is still responding.

**128 non-voice offline checks passed, 0 failed, 0 skipped:** 41 document Python tests, 24 document frontend checks, 28 server evidence/routing checks, 30 workflow graph checks and 5 portability checks. These use synthetic fixtures and mocked providers, not the user's data or live services. An initial server-test invocation failed because isolated Python could not locate the test module; the corrected invocation passed. No microphone, speaker, voice session, voice-specific tests or real provider calls were run.

Static review noted that a live-voice data-channel send may throw if the connection closes at the same moment. Voice behavior was left unchanged because the requested scope excludes voice testing; this remains unverified. The user's existing preview was not reloaded or restarted, so unsaved interview state is preserved; the currently running server must be restarted to load backend fixes.

## 0.10.1 shape-only GPFS logo — 2026-11-02

Removed the company lettering from the animated conversation mark, header and initial fallback. The five original symbol paths, colors and audio-driven movement remain intact; the full official SVG stays in source only for provenance. The header and fallback use a local shape-only SVG.

**82 checks executed and passed, 0 failed, 0 skipped:** 19 existing GPFS component checks, 4 existing asset/HTTP checks and 59 UI-state checks. A fresh browser load confirmed the shape-only header asset and five-part conversation mark, no lettering SVG and no page overflow. The open preview received only the visual update without reloading; its seven turns, title, unsent answer and file references were verified unchanged. No audio/provider behavior changed or was retested against physical hardware.

## 0.10.0 GPFS living vector presence — 2026-11-02

The official GPFS symbol replaces the orb entirely. Its exact five source paths retain copper and taupe fills, with controlled surface illumination, small inward listening movements and outward speaking articulation. Original company lettering stays still. The header uses the original full lockup. [Asset provenance and motion design](GPFS_ASSET.md) record the source, hash, geometry, colors and integration contract.

Microphone and AI playback now supply separate measured envelopes. Captions alone cannot imply speaking. The output meter accounts for the media element's actual playback, mute/volume, buffering and track state. Noise gating, attack/release and a brief phrase hold prevent jitter, while interruption releases the speaking posture into listening. Muting the microphone still allows actual AI playback to speak. Idle and quiet states stop animation once settled; hidden panels suspend visual rendering. Reduced motion uses static state lighting and avoids repeated audio-frame paints. Auxiliary typed-question or installed-voice playback uses actual playback events for a composed speaking posture without inventing amplitude measurements.

The four requested decorative lines were removed from initial, resumed and active conversation rendering. Existing process titles, uploads, memo, transcript, workflow and review behavior remain in the shared conversation state.

### Executed verification

**316 executed, 316 passed, 0 failed, 0 skipped:** 136 Python, 59 UI-state, 41 Live controller, 24 document-frontend, 9 playback, 28 workflow-canvas and 19 GPFS component checks. These are offline fixtures with mocked providers/media, local HTTP servers and the real bundled ELK layout engine. New HTTP checks cover exact asset bytes/MIME, same-origin restrictions, allowlisting and passive SVG content. Application-source whitespace checks passed; the unmodified upstream ELK bundle retains eight original trailing-whitespace lines to preserve its distribution bytes. Aggregate local receipt: ignored `work/gpfs-offline-verification.json`.

**A 28-second browser motion exchange passed all 16 checks.** The real Live controller and Web Audio analysers received separate synthetic microphone/output streams. The sequence covered idle, connecting, participant speech, pause, AI response with a phrase gap, interruption, continued participant speech, actual media waiting/playing events, return to listening, mute and end. Rendered frames were observed during the exchange; 138 timed pose/audio samples verified inward versus outward posture, actual playback gating, separated envelopes and continuity. Cleanup closed the controller/context and ended every synthetic track. No provider call, physical microphone capture or audible output occurred. Evidence: ignored `work/gpfs-motion-verification.json` and captured frames.

**Twelve populated-view layout cases passed without outer-page overflow:** Voice, Transcript and Workflow at 1280×720, 390×844, 320×568 and 844×390. Desktop and mobile rendered screens were inspected, including the compact 320px voice view and landscape workflow. A separate fresh mobile entry screen was checked. Actual browser reduced-motion emulation produced static geometry and no repeated paints when only audio levels changed. Browser console inspection returned no errors or warnings; temporary viewport/media overrides were reset. Evidence: ignored `work/gpfs-layout-verification.json` and screenshots.

### Delivery and boundaries

Version 0.10.0 runs at port 8775. Its previously empty entry tab was verified to contain no title, conversation turns, unsent answer or files before refreshing. The participant's existing port-8774 interview remains open and untouched. All completed 0.6–0.10 source, tests, documentation and vendored assets are included in this release; local credentials, document originals/databases and verification artifacts remain excluded from Git. Publication scanning found no actual configured credentials or unexpected secret patterns in the candidate files.

Physical microphone sensitivity, audible speaker quality, acoustic echo cancellation and a real participant interruption remain **unverified** for this update. The simulated exchange establishes controller/render behavior, not physical audio quality. No new provider calls were required for this visual change; the 0.9.0 real-provider receipts below remain historical. Large-document analysis and production-hosting boundaries below still apply. This is a private source release and local preview, not a hosted production deployment.

Earlier receipts below remain historical, including their original publication status.

## 0.9.0 conversation-first titles and document context — 2026-11-02

The interview starts without a process-name form requirement. GPT-Live greets the participant and asks what work they want to walk through; the working capture proposes a title from participant answers. The header stays editable. Manual title edits survive subsequent capture updates and JSON save/reopen. Typed startup follows the same unnamed-conversation path.

PDF, PNG, XLSX/XLSM and CSV files can be added during a conversation. Originals and extracted sources are retained in a private local document workspace. A quick relevance review can offer a timely question; unclear purpose is asked once, and unrelated material is thanked and parked. A bounded background sweep records further sourced observations and questions. Late findings stay in Files when a newer question or unsent answer would be interrupted. File receipts do not replace the active voice-stage question or count as numbered questions. File claims remain unconfirmed reference material until the participant supplies evidence. They cannot directly complete memo items or become workflow facts.

The file tray distinguishes extraction, relevance review, deeper review and errors, exposes exact page/cell sources, and preserves typed purpose text during polling. Source navigation focuses its heading inside the tray. Review and Markdown include document summaries, limitations, exact references, observations and questions, separately from participant evidence. Saved interview JSON includes local scope references and metadata, not the original binaries. See [document design and official research](DOCUMENT_CONTEXT_DESIGN.md) for storage, parsing, retrieval, scope isolation, provenance and limits.

### Executed verification

**280 offline checks passed, 0 failed, 0 skipped:** 132 Python, 56 UI-state, 24 document-frontend, 31 Live voice, 9 playback and 28 workflow-canvas checks. These use mocked providers, temporary local servers, simulated browser/media APIs, and the real locally bundled ELK layout engine. Large extraction fixtures included a 100-page PDF and a 50-tab workbook with 1,205 rows per tab, including exact later-row retrieval. Scope isolation, hostile containers, formulas/macros, retained originals, archive/restart recovery, stale async results, source constraints and saved-session recovery were covered. This is full accepted-fixture indexing evidence, not full large-corpus model analysis.

**Four small synthetic document cases passed across nine real OpenAI Responses calls** using `gpt-5.4-mini`: a two-page PDF including a scanned page, a PNG, a two-sheet workbook, and an unrelated CSV followed by purpose clarification and parking. All final responses completed, cited only supplied sources, and used `store:false`; there were no final provider/schema/service errors and no automatic retries. Scanned-page and PNG interpretation was stored explicitly as unverified AI transcription. The CSV asked for purpose once, remained parked after the explanation did not establish relevance, and was excluded from active interview retrieval. Evidence: ignored `work/document-provider-smoke.json`.

Seven earlier provider calls exposed a validation issue: the model supplied visual transcription in text-only follow-up batches. The request schema now constrains `extracted_text` to an empty string when no visual input is present, while service-side validation remains enforced. Initial failed evidence is preserved in `work/document-provider-smoke-initial.json`. A browser CSV that had paused was successfully retried from its retained original after the repair and server restart.

**A separate real GPT-Live protocol probe passed.** The actual `CollectorLiveVoice` class used silent synthetic WebAudio input and a non-playing output sink. The session started with `gpt-live-1`, sent the opening greeting exactly once, received its acknowledgment, produced the expected opening question transcript, and received inbound audio packets. A queued document update was sent solely through `session.thinking.append` and acknowledged without restarting the session. Cleanup closed the connection and ended the synthetic input tracks. No physical microphone, audible speaker, interruption-quality or real participant conversation claim is made. No provider rejection occurred; rejection recovery remains offline-tested only. Evidence: `work/live-context-provider-smoke.json`.

### Browser, export and preservation evidence

The browser verified unnamed typed startup, automatic naming from the first answer, manual-title preservation after subsequent capture, mid-conversation file receipt and a relevant follow-up, retained-error recovery, exact `CSV!A1:C7` readback, and saved-interview/document-reference restoration after restart. Document sources remained distinct from participant evidence in the generated ten-step report.

**24 layout cases passed without outer-page overflow:** empty and populated Voice/Transcript/Workflow views, file/source review, and the detailed Report at 1280×720, 390×844 and 320×568. File review used contained scrolling; the 320px dialog retained a 342px scrolling content region. Temporary viewport overrides were removed. This does not establish every device, browser, large graph or assistive-technology combination.

The actual Markdown download was checked independently: 17,680 bytes, all seven conversation turns, ten procedure steps, nine connections, the supporting-files appendix and exact cell references. Its local document scope token was absent. Seven artifact checks passed. Evidence is retained in ignored `work/report-0.9.md`, `work/report-0.9-check.json` and `work/browser-0.9-check.json`.

The participant's existing port-8774 interview was left open and untouched during final testing. The updated version runs separately on port 8775, with a fresh conversation entry screen. This is local, uncommitted work; no remote push or hosted deployment was performed.

### Remaining boundaries

Physical audio was not tested. The 100-page and 50-tab fixtures were fully indexed offline, but were not fully reviewed by the real provider; provider coverage used the smaller fixtures above. Mixed text/image PDF pages currently take the text extraction path, so embedded diagrams can be missed; image-only pages and PNGs receive visual review. Workbook formulas are not recalculated, macros are not executed, and charts or embedded drawings are not interpreted. Legacy XLS requires conversion. Local lexical retrieval and bounded background review do not guarantee exhaustive understanding; hosted File Search, workbook analytics, Claude, encryption at rest, user-managed permanent deletion and multiuser hosting remain unimplemented. These limits are documented in the interface/design rather than presented as completed capabilities.

Earlier receipts below remain historical.

## 0.8.0 complete capture and workflow canvas — 2026-11-02

The current local update removes interview duration controls, clocks and planning targets. Current interview/provider snapshots, saved sessions and Markdown exports omit interview timing metadata; legacy timing fields are accepted only for compatibility and ignored. Reported deadlines, cadence and processing times are still process evidence. The interview continues until the participant decides to finish, subject to the existing explicit size and provider/context limits.

The enough-detail notification now requires exactly one complete finding for each of the eleven memo topics: `captured` or explicit `not_applicable`. Partial, unknown and missing findings cannot trigger readiness, regardless of the model's `ready_for_draft` flag or contradictory coverage indicators. Explicit findings determine the displayed circles. Repeated complete snapshots do not keep re-announcing readiness, and a correction that reopens a topic clears the prior readiness notice. This is capture coverage, separate from participant confirmation, owner approval and independent verification. Notifications dismiss after three seconds; a newer notice cancels and resets the timer.

Review opens a detailed read-only Report alongside the six editable/supporting sections. It organizes supplied context and objectives, the overview, all eleven memo findings, every procedure field, reported connections, lifecycles, full variation details, controls, exceptions, gaps, parked topics and the full interview evidence. Returning to Report reflects current reviewer edits. Complete Markdown exports retain the same detailed information and source references without modifying the interview or edited draft. The standalone memo includes the full open-question register and detailed process/evidence appendix; it no longer truncates after five questions.

### Automated verification

**92 Python tests + 44 UI-state checks + 9 playback checks + 11 Live voice checks + 28 workflow-canvas checks = 184 passed, 0 failed, 0 skipped.** These automated suites use mocked providers and temporary local servers or simulated browser/media APIs. UI checks cover three-second dismissal/reset, all-eleven readiness gating in typed and live-capture paths, repeat suppression and withdrawal after correction, complete Markdown content, Report detail and refresh after reviewer edits, scrolling, modal focus and recovery. Graph-adapter checks reject errors from old generations/controllers, refresh or close source-specific step details after corrections, and disable SVG export while layout is pending or failed, without falling back to a stale visible SVG.

### Live synthetic provider evidence

A direct synthetic routing fixture completed draft generation and its evidence-audit stage with **17 checks passed**. The final result included all eleven memo topics and sourced step detail; supported outage entry without an invented return; the client-specific approval entry and rejoin; an explicit bypass for other clients; terminal duplicate closure; and only reported rework/recheck self-loops. Evidence is retained in ignored `work/final-draft-0.8-routing-final.json`.

Earlier synthetic routing attempts exposed ambiguous conditional routing, including an absent other-client bypass. Those observations prompted a tighter shared routing policy before the successful final fixture. An additional full-circle draft/audit policy was appended afterward and was verified only by the offline suite; it was not exercised in that successful live result. The seventeen checks establish the observed synthetic result, not a semantic guarantee for future model output. No real business interview was used for this provider check.

### Browser and artifact verification

The browser layout matrix covered **15 cases**: Voice, Transcript and Workflow at **1280×720, 1024×768, 390×844, 320×568 and 844×390**. None had horizontal or vertical page overflow. The shortest landscape workflow retained a **143-pixel** canvas with visible nodes. Browser checks also verified exact camera retention across representation switches, keyboard panning, orientation switching, three-second notification dismissal and access to all eleven memo topics in the mobile sheet. These are the observed viewport/interaction results; they do not establish every graph, zoom level, device or assistive-technology combination.

The actual downloaded example Markdown was copied byte-for-byte to ignored `work/report-0.8.md`, with independent checks in `work/report-0.8-check.json`. It retained all **seven source turns** (three participant and four interviewer) verbatim, sixteen major sections, eleven memo topics, six procedure steps with all detail fields, five connections and all four open questions. Unknowns and review boundaries remained explicit; no interview timing metadata appeared. A complete SVG containing the example's **six nodes and five edges** was downloaded separately.

A further browser fixture combined the final audited routing with the original conservative partial memo findings (clearly labeled synthetic). Review rendered thirteen sections and fourteen detailed steps; the memo remained 9/11. The actual 23,218-byte Markdown download retained all eight participant turns, fourteen steps, connections and all open questions, with no interview timing metadata. The SVG download contained all fourteen nodes and sixteen edges in its intrinsic `0 0 3978 718` viewBox. Step-source navigation closed the detail dialog and highlighted the exact third answer in Transcript. Browser console checks returned no errors or warnings. Safe evidence is retained in `work/branching-workflow-session-0.8.json`, `work/detailed-report-0.8.md`, `work/branching-workflow-0.8.svg` and `work/final-export-checks-0.8.json`. This UI fixture does not change the raw provider results or establish that all memo topics were complete. Report viewport checks at 1280×720, 390×844, 320×568 and 844×390 also kept the document within the screen, with scrolling inside the Review section.

Physical microphone capture, speaker quality, interruption timing and an extended real voice interview were **not rerun** for 0.8.0. Earlier microphone-free GPT-Live connection evidence remains historical and establishes protocol/account access rather than physical audio UAT. No remote push or hosted release was performed.

### Workflow diagram design decision

AI extraction and diagram layout have separate responsibilities. The extraction request produces reported steps, connections and participant-source references; schema and evidence checks validate that data before it reaches layout. Later participant corrections may replace, edit or remove working graph elements. Review edits remain separate. Layout only computes positions and routes for the accepted graph; it cannot invent steps, branches, approvals or exception-resolution paths to make the picture look complete.

[Mermaid AI's official editing guide](https://mermaid.ai/docs/build-and-edit/add-and-edit-with-ai) describes natural-language diagram creation and edits with a proposed-change review. That is a useful content-editing reference, rather than a layout engine or a service used by this prototype. Here, corrections come from the conversation and update the validated working graph; exported/reviewed material remains subject to process-owner review.

[React Flow's layouting guide](https://reactflow.dev/learn/layouting/layouting) separates graph viewing from external node-layout and edge-routing libraries, and identifies ELK as supporting varied node sizes and edge routing. This application retains its existing browser/SVG architecture rather than adding React Flow. It uses a local ELK.js bundle for layout and an application-owned SVG canvas for viewing. [ELK's project overview](https://eclipse.dev/elk/) explains that ELK computes coordinates rather than rendering diagrams; [ELK Layered](https://eclipse.dev/elk/reference/algorithms/org-eclipse-elk-layered.html) documents layered graph placement, orthogonal routing, labels and cycle-related options.

The 0.8.0 canvas uses distinct activity/decision nodes, routed and labeled branches, pan/zoom/Fit controls, keyboard navigation, a minimap where space permits, source-backed step detail and complete SVG export. The locally bundled ELK.js version, package integrity and license are recorded in [vendor provenance](../web/vendor/elk.PROVENANCE.md). No runtime CDN or third-party diagram service receives interview content. The graph remains bounded to eighty steps and 150 connections. These design decisions are implementation context; the observed graph, browser and export evidence is recorded above and does not imply semantic correctness for every generated process.

## 0.7.0 full-window conversation workspace — 2026-11-02

The interview now fills the window with contained scrolling for the transcript, working workflow and memo. Compact conversation controls remain available while switching Voice / Transcript / Workflow. The same live connection and capture state are retained across those representations; switching does not start or stop voice, submit a question, schedule a provider request, discard unsent text or reset the transcript reader's scroll position. The eleven-topic memo is visible as a rail on wider screens and moves into a modal sheet on narrower screens. It uses the same memo state and source links in both layouts.

The gradient orb's scale and halo respond to measured microphone and output audio levels. Its slow gradient rotation is decorative; an animated orb alone does not establish microphone capture, audible playback or voice quality. The controller retains explicit listening, speaking and muted states, immediate microphone release on End, and a bounded final-caption drain. Physical microphone behavior and speaker quality were not retested for this layout update.

One structured provider snapshot now returns both the working map and all eleven memo findings, plus the factual summary, current focus and parked topics. Canonical coverage indicators derive from the validated findings. Both map and memo apply participant corrections; assistant questions are excluded from evidence. Reported findings require a participant source or explicit intake context. Generation/revision guards reject stale snapshots, and the complete new snapshot is validated before it is applied. Capture refreshes do not overwrite the editable review draft. Accepted typed answers remain retained if preparing the next question fails.

Current automated evidence: **86 Python tests + 30 UI-state checks + 9 playback checks + 11 Live voice checks = 136 passed, 0 failed, 0 skipped**. These suites use mocked providers and temporary local servers or simulated browser APIs. The Python suite was rerun after the final source-schema repair. UI checks include same-session representation switching, preservation of transcript scrolling and unsent text, mobile memo/foundation dialog focus, combined memo/map updates, stale-response rejection and protection of review edits. Browser layout verification for 0.7.0 is being recorded separately; this receipt does not claim new viewport results.

Two direct synthetic provider calls using **gpt-5.4-mini** accepted the combined snapshot schema and returned eleven findings and eleven coverage entries. Every reported finding carried valid participant evidence. An explicit correction removed manager approval and rejection, changed the map from six steps to four, and updated the lifecycle memo using the correction's source. Overall accountability remained unestablished. Safe local evidence is retained in ignored `work/combined-capture-smoke.json`; no real business interview was sent for this check.

A subsequent browser observation found source IDs in the parked-topic prose list. The request-schema builder had preserved Python aliases when copying shared string-array schemas, allowing evidence restrictions to affect unrelated lists. It now materializes an independent JSON schema tree before applying evidence constraints. A regression checks Interview, Draft and combined capture schemas with both short and 400-participant histories: ordinary text lists remain unconstrained strings, while only evidence fields receive complete participant-source enums or shared references. Existing server evidence validation remains in place.

One final direct synthetic **gpt-5.4-mini** call exercised the repaired schema with the corrected request process and an explicit separate topic to park. It returned the four-step receive/log/assign/complete map, eleven valid findings and eleven coverage entries, and the prose parked item “Travel reimbursement is separate and should be handled in a later interview.” Manager approval remained absent and every reported finding retained participant evidence. The call completed without a retry and used **1,102 output tokens, including 228 reasoning tokens**, against the configured **12,000-token** output allowance. That establishes headroom for the observed example; the largest supported captures were not live stress-tested. Safe local evidence and usage are in ignored `work/combined-capture-final-schema-smoke.json`. No real user data, physical microphone input or browser session was used for this final check.

Earlier version receipts below remain historical evidence. The 0.6.0 microphone-free GPT-Live connection probe established account access and protocol setup, not physical audio UAT for 0.7.0. Runtime code still uses Python's standard library, credentials remain server-side, and loopback, Host/Origin/CSRF, request-size and concurrency boundaries remain in force. No new runtime or package installation, hosted release or remote push is claimed here.

## 0.6.0 conversation-first local update — 2026-11-02

Implemented a single conversation stage with directly accessible Voice / Transcript / Workflow tabs. The default orb reacts to live audio level and state, honors reduced-motion settings, and keeps mic Mute / End controls visible across these views. Memo foundation and supporting capture detail moved to Review. Review navigation is blocked while voice is active so the mic controls cannot disappear. Microphone access requires Start live voice; keys stay server-side, and no new package/runtime was installed.

GPT-Live 1 uses the official JSON WebRTC `/v1/live/sessions` contract. A separate stateless structured request regenerates the working workflow after participant answers/caption pauses. New maps replace old working maps, including removals and corrections, without replacing user edits in Review. Generation/revision guards reject stale responses. Accepted typed answers survive next-question failures; explicit Retry never duplicates them. Workflow updates can proceed from retained answers even when next-question preparation fails. Both browser and server retain evidence validation. Per-request structured schemas restrict sources to participant IDs/context and require sources for reported findings.

Executed local checks: **82 Python tests + 39 Node checks = 121 passed, 0 failed, 0 skipped**. Node groups: 9 playback, 19 UI/integration, 11 Live protocol/lifecycle. No provider calls occur in those automated suites. `git diff --check` passed.

Live-service evidence: a real browser-generated, microphone-free SDP connection returned HTTP 200 and `session.started` with `model=gpt-live-1`; it was then closed. Two direct synthetic workflow calls verified initial generation and removal of manager approval following an explicit correction. Browser checks exercised entry, Transcript/Workflow switching, typed first-question/answer capture, workflow rendering, and session JSON download/reopen with the unsent correction retained. A narrow viewport check found no horizontal page overflow. Two typed correction attempts revealed invalid/empty memo evidence; both were rejected with the answer preserved. Request-schema constraints and accepted-answer recovery were strengthened in response, with regression tests. The final browser retry then succeeded: the next question appeared and the displayed map replaced manager approval with purchase-order matching. The saved QA JSON and screenshots are in ignored work/.

Physical microphone capture, speaker quality, interruption timing and an extended real conversation were not exercised. The connection probe proves project access and protocol setup, not physical audio UAT. Reconnection preserves history or rejects clearly when the full initial Live history cannot fit; it never silently discards prior turns. Existing loopback binding, Host/Origin/CSRF controls, bounded requests and concurrency limits remain in place. This remains a single-user local prototype with explicit JSON persistence, not a shared hosted release. No remote push was requested or performed.

Official references: [GPT-Live WebRTC](https://developers.openai.com/api/docs/guides/voice-webrtc?api=live), [Live conversations](https://developers.openai.com/api/docs/guides/live-conversations), [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

# Publication verification

Verified on November 2, 2026, against the version 0.5.0 repository publication copy.

- **64 offline Python tests passed:** the original 45 prototype regressions, 4 portability checks and 15 voice/provider API tests. A synthetic injected identity provider works without an OpenAI key attribute; unsupported browser connection origins are rejected before binding. OpenAI responses were mocked; HTTP traffic stayed on temporary local servers.
- **9 offline Node checks passed:** simulated Realtime event sequencing, PCM/WAV framing, speech-transcript mismatch rejection, cancellation, incomplete responses, audio-size limits, unrelated acknowledgments, Stop cleanup and unsupported provider/transport rejection before any socket is created. No browser or audio hardware was exercised by these tests.
- Live Realtime checks generated the same requested preview sample with Marin and Cedar using `gpt-realtime-2.1-mini`. Returned transcripts matched; audio durations were approximately 5.65 and 6.05 seconds. These results establish provider generation, not browser playback or subjective voice quality. The other eight AI choices were not live-tested individually.
- A browser preview reached “Speaking · Cedar” and completed without console warnings or errors; the selector switched back to Marin. This was an observed UI flow, not a physical listening or subjective voice-quality test.
- Python3.12.14 from an existing compatible installation was reused. Runtime code uses only Python's standard library; no package installation or environment creation was needed.
- The portability checks verify repository-local environment lookup, process-environment precedence, rejection of unrelated ancestor settings, and logs staying inside the repository.
- JavaScript syntax was checked using an existing Node installation. Node is not required to run the application.
- The voice configuration exposes ten selectable AI voices with Marin as the default and Cedar as an alternative, plus explicit installed computer voices and a Preview voice control. The server requests a 60-second Realtime client token; only that short-lived token reaches the browser. Tests reject unsupported voices and malformed token responses and verify that the project API key is not returned.
- After the 0.2.1 provider separation, the installed application loaded its provider-supplied data notice and service configuration state. Marin preview reached Speaking and completed with no console warnings or errors. This confirms the current adapter still connects; it does not test an Azure provider.
- The Azure handoff records the intended Foundry/managed-application direction and separates current functionality from pending identity, persistence, provider and hosting work. The reference repository's main-branch README and architecture were read at commit `01eff3bf7739e8c45496ebdc40cbed87873a0a9e`; no reference repository or Azure resource was changed.
- The source, example and documentation publish list was checked for actual credential-shaped values, host paths, setup-account metadata and organization-specific branding. The `.env.example` key value is empty. Test-only fake sentinels are not usable credentials.
- Local key files, account setup history, credit information, machine inventory and preflight receipts are excluded from publication.
- No automated package/runtime download or CI setup workflow is included. Future CI setup should apply the owning environment's reuse policy rather than assuming the development host's resources exist there.

Earlier live synthetic API and browser checks apply to the earlier prototype behavior; the voice-upgrade checks are listed separately above. See [VALIDATION.md](../VALIDATION.md) for the full limits. Publication testing does not establish production readiness, reliable exhaustive capture, physical listening or subjective voice quality, physical microphone behavior, or Teams integration. No real business-process interview is included in the fictional example.

The source memorandum's requirements are preserved in [MEMO_REQUIREMENTS.md](MEMO_REQUIREMENTS.md) and the [standing foundation](../FOUNDATION.md), using neutral language. The original branded document is retained locally and is not part of the repository.

## Interface checks in 0.3.0

The monochrome workspace was observed on desktop and at 320px/390px widths without horizontal document overflow. Checks covered required-field disclosure/focus, live interview start, natural voice preview, all eleven expandable memo topics, edits and source navigation, session save/open, and complete memo/procedure/SVG exports with collapsed review details. No console warnings/errors were observed. The original memo source hash was unchanged. See [validation](../VALIDATION.md) for scope and limits.

## Interview completeness 0.20.0 on November 3 2026

The canonical Windows checkout passed **385 Python tests and all 13 JavaScript suites** after adding independent topic explanation assessment, final-response closure checks, silent live coverage feedback, provisional imported coverage and explicit review retry. Node syntax and Git whitespace checks passed. Existing Python 3.12.14 and Node 24.22.1 were reused; there were no installations or downloads.

Six synthetic provider requests used gpt-5.4-mini. They rejected premature closure and shallow claimed coverage, preserved a supported purpose, and accepted a fully explained eleven-topic account. One unavailable-detail prioritization case was initially mixed, then passed after a targeted prompt revision. These individual behavioral samples do not establish statistical reliability. Private validation receipts are under work/interview-quality-2026-11-03/.

HTTP smoke verification matched the running 0.20.0 source build and updated HTML/JavaScript on port 8775; the existing port 8774 session was preserved. Physical microphone/speaker behavior, rendered browser interaction, direct-live compliance and final-confirmation speech were not tested. The direct audio stream has no deterministic pre-audio content gate. Model semantic judgments remain fallible even when dimension and provenance validation passes. See [the completion design](INTERVIEW_COMPLETENESS.md).

## Focus and navigation checks in 0.4.0

The 64 Python regressions and 9 voice checks passed. Six additional built-in Node UI-state checks cover exact turn partitioning, pending-question stability, evidence navigation, read-only reported findings, modal focus and review/context jumps with zero provider calls. Actual browser checks confirmed unique turn placement, topic details, Escape/close focus, source jumps, section navigation, preservation and restoration of an unsent answer, current-question narration, and 320px/390px reflow without document horizontal overflow. No console warnings/errors were observed. See [validation](../VALIDATION.md) for the observed scope and limits.

## Review workspace checks in 0.5.0

64 Python tests, 9 Node voice checks and 9 Node UI-state checks passed using existing runtimes. Browser checks confirmed persistent review edits, keyboard tab activation, save/open restoration, complete memo/procedure/SVG downloads with panels hidden, original SVG geometry after map zoom/Fit, and direct Marin preview. The 320px/390px layouts had no document horizontal overflow; temporary viewport overrides were reset. Print-media emulation exposed all panels and closed memo bodies; physical print pagination and long-text clipping were not established. No console warnings/errors were observed. See [validation](../VALIDATION.md) for the exact observations and limits.
