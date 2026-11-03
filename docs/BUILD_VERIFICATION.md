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

## Focus and navigation checks in 0.4.0

The 64 Python regressions and 9 voice checks passed. Six additional built-in Node UI-state checks cover exact turn partitioning, pending-question stability, evidence navigation, read-only reported findings, modal focus and review/context jumps with zero provider calls. Actual browser checks confirmed unique turn placement, topic details, Escape/close focus, source jumps, section navigation, preservation and restoration of an unsent answer, current-question narration, and 320px/390px reflow without document horizontal overflow. No console warnings/errors were observed. See [validation](../VALIDATION.md) for the observed scope and limits.

## Review workspace checks in 0.5.0

64 Python tests, 9 Node voice checks and 9 Node UI-state checks passed using existing runtimes. Browser checks confirmed persistent review edits, keyboard tab activation, save/open restoration, complete memo/procedure/SVG downloads with panels hidden, original SVG geometry after map zoom/Fit, and direct Marin preview. The 320px/390px layouts had no document horizontal overflow; temporary viewport overrides were reset. Print-media emulation exposed all panels and closed memo bodies; physical print pagination and long-text clipping were not established. No console warnings/errors were observed. See [validation](../VALIDATION.md) for the exact observations and limits.
