# Enhancement brief: make the workflow diagram fast, reliable and standard

Status: in progress. Evidence: [the November 17 stress run](../testing/runs/2026-11-17-stress/README.md). What has been built was verified with stand-in providers only: [the map-lanes run](../testing/runs/2026-11-17-map-lanes/README.md) lists what was checked and what still needs a run against the AI service.

| Part | Status |
| --- | --- |
| Phase 0, a baseline you can re-measure | The stand-in latency suite exists (`tests/test_map_lanes.py`). The replay against the AI service was not run. |
| Phase 1.1, keep the map being drawn | Done. |
| Phase 1.2, a full pass at Wrap up | Done as a comparison: the full map replaces the incremental one only when it carries clearly more. |
| Phase 1.3, map workers and provider slots | Done: `COLLECTOR_MAP_WORKERS`, `COLLECTOR_PROVIDER_SLOTS`, two slots kept free of background work. |
| Phase 1.4, draw allowance and one retry | Done. |
| Phase 1.5, Live voice map from a final caption | Done. |
| Phase 1.6, evaluate the audit model | Not done. It needs the AI service. |
| Phase 2, the map as a view of the ledger | Partly. The check is off the path between an answer and the diagram, reviews differences and is carried under later draws. A cause this brief missed is fixed: the background draw had lost the routing, component and step-detail policies (section 4.4 describes the symptom). Graph operations from the notes capture are not built; measure the audit's rewriting again first. |
| Phase 3, a presentation layer | Partly. Implied start and end markers and a gateway after a step with several exits are drawn from a picture derived in the browser; the evidence is untouched and exports exclude them. On the twenty maps of the run every picture has a start and no branch leaves an ordinary box. Not done: lanes, compact decisions, a straight main path, position stability, dead-end open questions on the canvas. No blind judging of structure was run. |
| Phase 4, push and a job runner | Partly. Jobs are taken one at a time, the oldest first, and a cancelled request is released. Pushed updates and streamed output are not built. |
| Phase 5, Live voice orchestrated by the server | Not started beyond Phase 1.5. The Live instructions now say one question per turn and no second request for a stated unknown. Transcription hints for Live sessions are not sent: the provider documents `prompt` and `keywords` for transcription sessions, not for a `gpt-live-1` session, and an undocumented field could stop voice from starting. Feeding stated unknowns to the Live model earlier needs a voice test. |
| Phase 6, files | Partly. The first question about a text-only file is asked after its first pass, and two files are reviewed side by side. Not done: parallel requests inside one file (the notes of each request build on the one before, and review quality could not be judged without the AI service), skipping the first pass's sections in the in-depth pass (nine suites pin that sweep; it saves at most one request per file), the 12-request stop and the coverage shortfall in Assets. |
| Phase 7, notes speed | Not started; it is the owner's decision. |

Sections 4 and 5 below describe the app at `04e6ee3`. Where a row above says done, the code no longer matches them.

You are picking up engineering work on **AI Process Collector** (`github.com/amelas-dev/ai-process-collector`, branch `main`, baseline commit `04e6ee3`, version 0.32.0 plus the "Unreleased" changelog entries). This document is your brief. It tells you what was measured, what is wrong in the design, what to build, in what order, and how to prove each part worked.

Read it fully before touching code. Then read `AGENTS.md`, `FOUNDATION.md`, `docs/WORKFLOW_DIAGRAMS.md`, `docs/WORKFLOW_UPDATES.md`, `docs/CONCURRENT_INTERVIEW.md`, `docs/AGENT_TEAM.md` and `docs/DOCUMENT_INTERVIEWS.md`. Those documents describe decisions that exist for accuracy reasons; you are expected to keep their guarantees, not to rediscover them by breaking them.

## 1. The goal in one paragraph

A participant describes a business process by typing, speaking or uploading a file. The app asks questions, keeps notes, and draws a workflow diagram. Questions, voice replies, transcription and notes are already fast enough. The diagram is not: in a 30-case test it was missing at the end of 14 of 27 interviews and almost never appeared while the person was still talking. When it does appear it is not laid out like a standard process diagram. Your job is to change the design so the diagram updates within seconds of each answer, never fails silently, and reads as a conventional process diagram, **without lowering fidelity to what the participant or the file actually said**.

## 2. Who you are working for

The owner is a non-specialist product owner, not a full-time engineer. Explain outcomes in plain language, lead with what changed for the participant, and report honestly: if a test fails or a step was skipped, say so with the output. His standing UI preference: a clean interface that guides through layout, **never by adding explanatory text**. One status line at a time, one place for each fact.

## 3. What was measured (2026-11-17)

Thirty distinct processes from the library in `docs/testing/process-library/IP1-export.pdf` (43 processes; section 8 of each is the step-by-step procedure) were played by source-grounded participants: 13 typed, 10 file uploads, 4 recorded-voice, 3 live-voice in a browser with synthetic speech. Real provider, isolated copies of the app, one interview per server unless stated.

| Area | Result |
|---|---|
| Next question, typed | 2.1 s median, 3.1 s p90, 5.2 s max (129 answers) |
| Live voice reply | 1.0–2.3 s after the speaker stops; captions begin about 1 s into speech |
| Transcription (`/api/transcribe`) | 1.8 s median; 129 s of audio in 5.6 s; word error 0–7% |
| Notes after an answer | 31 s median, 42 s p90 |
| Diagram before the next answer | 7 of 139 answers |
| Final diagram after Wrap up | 13 succeeded (215 s median wait), 14 failed |
| Small files (1–7 pages, CSV, XLSX, PNG, scanned PDF) | first question 7–24 s after choosing the file |
| 85-page text PDF | text read in 3.2 s, first question at 161 s |
| Live voice diagram | 100–318 s after the last spoken answer |
| Five interviews on one server | questions 2.5–5.2 s median; 3 of 5 had no diagram nine minutes after Wrap up; Wrap up up to 127 s |

Model stage timings from the raw trace (successful calls):

| Stage | Model | Median | p90 | Max | Median output tokens |
|---|---|---|---|---|---|
| `conversation_question` | gpt-6-luna | 2.1 s | 3.1 s | 5.1 s | 61 |
| `team_interview_capture` | gpt-6-luna (27 calls) | 14 s | 36 s | 59 s | 1,729 |
| `team_interview_capture` | gpt-6.1-terra (112 calls) | 33 s | 47 s | 88 s | 2,816 |
| `team_working_process_map` (draw) | gpt-6.1-terra | 41 s | 72 s | 135 s | 3,029 |
| `team_working_map_source_audit`, transcript only | gpt-5.4 | 140 s | 217 s | 231 s | 9,911 (8,804 reasoning) |
| `team_working_map_source_audit`, with files | gpt-6.1-terra | 97 s | 153 s | 176 s | 8,608 |
| `document_context_review` | gpt-6.1-terra | 11.9 s | 14.4 s | 14.9 s | 782 |

Throughput was steady at 75–86 output tokens per second, so these durations are output-bound, not a rate-limit artefact.

Structure of the 14 final maps: 6 had a start node, 1 had an end node, 9 were one connected flow, 12 had branches leaving an ordinary activity box, median 3 dead ends. Two blind judges per map scored structure 3–5 of 10 on every map they saw, and fidelity 6–8 of 10.

Raw material is in `docs/testing/runs/2026-11-17-stress/`: `cases/` (every interview with timed events, final notes and map), `timings.json`, `stages.json`, `evals.json` (participant evaluations), `judges.json`, `live_scripts.json` and `prototype.diff`. The reusable harness is in `docs/testing/harness/`. Some of these files contain absolute paths from the machine they were produced on; ignore them.

## 4. Why it is slow: verified causes

Line numbers are for `04e6ee3` and will drift; the symbol names are the anchors.

1. **A new answer cancels the map in flight.** `ConcurrentInterview._queue` calls `_cancel_map` when the revision changes (`concurrent_interview.py`). 65 map runs were cancelled in the test. The cancelled provider request keeps holding the map slot until it returns (59 s observed), because the abort is only seen once a response starts arriving.
2. **One map worker for the whole server.** `self._graph_slots = threading.BoundedSemaphore(1)` in `ConcurrentInterview.__init__`. Notes have two workers (`self._slots`), all provider calls share four (`OpenAIClient._provider_slots`), and foreground routes share four non-blocking `api_slots`.
3. **Every map is two full sequential model calls**, draw then audit, in `Coordinator.workflow` (`interview_orchestrator.py`), with optional `RouteRecheck` and `RouteRepair` calls after. The audit always runs on this path.
4. **The audit re-authors the map.** `WORKFLOW_AUDIT_INSTRUCTIONS` asks for "only a compact correction delta", but a step can only be corrected by re-sending the whole step. Measured over 28 audits: it re-sent a median 89% of the candidate's steps, 62% of its output. The field that differed was almost always `operating_details`.
5. **Timeouts and caps discard finished work.** Draw 180 s, audit 240 s in the background (`BACKGROUND_MAP_GENERATION_SECONDS`, `BACKGROUND_MAP_AUDIT_SECONDS`). 13 audits and 5 draws timed out. The draw is capped at 12,000 output tokens (22,000 with files); a long first answer hit the cap three times and the map was thrown away.
6. **The map is a second extraction.** Notes already keep a fact ledger updated by small operations (`capture_facts.py`: `FACT_DELTA_SCHEMA`, `fact_operations`, `apply_delta`). The map ignores it: `initial_workflow` in `Coordinator.workflow` sends the whole transcript and has a model write steps and connections again from scratch or from the last published map.
7. **Publishing is all-or-nothing and bound to a revision.** `_build_graph` publishes only when `session["generation"] == generation`. Anything else is discarded.
8. **Live voice starts a map on the first caption delta.** `scheduleWorkflow` in `web/app.js` sets a fixed 1 s timer from any participant caption change ("a bounded checkpoint, not a debounce"), so the first run is built from a few words and the real one queues behind it. Notes correctly wait for a final caption (`scheduleLiveCapture`).
9. **The browser polls.** `web/concurrent-interview.js`: 650 ms growing to 3.5 s; documents poll every 2 s (`web/documents.js`).
10. **File review is serial.** One `document-review` thread for the whole server (`DocumentService.__init__`), one request per batch of up to 8 chunks, and the intake waits for `analysis.phase == "complete"` (`web/document-intake.js`). The 85-page PDF made 12 calls of about 13 s each. After the quick pass the deep pass restarts at cursor 0 (`cursor = offset + settled if phase == 'deep' else offset` in `DocumentService._run`). A file estimated above 12 requests stops after the sample.
11. **Most note captures run on the slower model.** `Coordinator.interview` picks `process_reviewer` whenever `capture_facts.reconciliation_targets(...)` is non-empty: 127 of 163 answer captures.

## 5. Why the picture is not standard: verified causes

1. The schema (`WORKFLOW_SCHEMA`, `WORKFLOW_UPDATE_SCHEMA` in `server.py`) has step types `activity, decision, merge, start, end, parallel_split, parallel_join, wait, subprocess, document, data_store`, and connections with only `from, to, label, evidence_turns`. There is no edge kind, no default branch, no main-path marker, no lane.
2. The prompts forbid structure that was not stated: `WORKFLOW_COMPONENT_POLICY` and `GRAPH_ROUTING_POLICY` say start and end only when explicitly reported, connect alternatives straight to the shared activity, never add a plausible Yes/No, do not invent a fork or join. `docs/WORKFLOW_DIAGRAMS.md` states the diagram "does not claim to provide formal swimlanes" and is "not formal BPMN conformance".
3. The renderer (`web/workflow-graph.js`) draws exactly that evidence graph with ELK `layered`: one in port and one out port per node, so all branches leave one point; actor is coloured text inside the box from a six-colour hash; disconnected fragments are packed side by side; every update is a complete re-layout with no position stability.

The evidence-first policy is correct and must stay. The fault is that the **evidence model is also the picture**.

## 6. What has already been tried

`docs/testing/runs/2026-11-17-stress/prototype.diff` (against `04e6ee3`, never applied to the checkout) does two things: a newer answer no longer cancels the map being drawn, whose result becomes a checkpoint and the baseline of the next update; and the drawn, validated map is exposed (`workflow_provisional` in the status view) while its audit runs. Three previously failed interviews were replayed with identical answers at 45 s pacing:

| | Unmodified | Prototype |
|---|---|---|
| First diagram visible | never during the interview | 34–67 s after the first answer in 4 of 5 runs, 223 s in one |
| Final diagram | 1 of 3 | 4 of 5 |
| Update after a later answer | 37–41 s redraw | 16 s incremental (one measurement) |

Judged fidelity was 6–8 of 10 in both arms. **One prototype map was thinner**: it carried 16–20 of 28 stated steps where the unmodified map carried 28. Bolting incremental updates onto whole-map generation loses content. Treat the prototype as evidence and as a stopgap, not as the design.

Setting `WORKFLOW_AUDIT_MODEL=gpt-6.1-terra` produced all three final maps with similar judged fidelity. Three interviews is a signal, not proof.

## 7. What to build

Work in the phases below, in order. Each phase is shippable on its own and has its own acceptance checks. Do not start a phase until the previous one meets its checks or you have written down why it cannot.

### Phase 0. Baseline you can re-measure

1. Get the harness running on your machine (section 9). Start one isolated copy, replay `T03` and `T01`, and confirm you can reproduce the shape of the numbers in section 3.
2. Add a fake-provider latency test alongside the existing suites so the timing properties below are checked without paying for model calls: a fake client whose map draw and audit take configurable seconds, driven through `ConcurrentInterview`. `tests/test_concurrent_interview.py` and `tests/test_concurrent_http.py` show the pattern.
3. Record your baseline as a new dated folder under `docs/testing/runs/`.

### Phase 1. Stopgaps (small, measured, reversible)

These do not fix the design. They move the app from "often no diagram" to "usually a diagram, slowly" while the real work happens.

1. Stop cancelling the in-flight map on a new answer; keep its result as the baseline and as a labelled checkpoint. Start from `prototype.diff`. The browser needs the matching change: apply a checkpoint map the way `applyBackgroundCapture` already applies a notes `checkpoint`, guarded by `workflowEvidenceStillValid`, and say through which answer the map goes using the existing single status line in Workflow.
2. At Wrap up, when the last published map came through the incremental path, run one full map pass from the transcript before the final check, so the thinning seen in the prototype cannot reach a filed process.
3. Raise the map worker count from one, and size the provider slots to match. Make both settings, with tests for fairness between interviews.
4. Raise the draw output allowance so a long first answer is not truncated, and treat truncation as "retry once with a larger allowance", not as a failed map.
5. In live voice, start the map from the same trigger as notes (a final caption), not from the first delta.
6. Evaluate `WORKFLOW_AUDIT_MODEL=gpt-6.1-terra` for transcript-only maps on at least ten replayed interviews with blind judging before recommending it as the default.

Acceptance: on a replay of `T01`, `T02`, `T07`, `T11`, `V01`, `V03` at 45 s pacing, a diagram is visible within 90 s of the first answer in every run, every run ends with a final audited diagram, and judged fidelity (section 10) is not lower than the unmodified app on the same answers. No interview ends with a failed map and no visible explanation.

### Phase 2. The map becomes a view of one evidence ledger

This is the main project.

**Design.** Each answer already produces `fact_operations` against a private ledger. Extend that single capture so the same call also returns **graph operations**, small and individually cited:

- `add_step`, `amend_step` (field-level: only the fields that change), `remove_step`
- `connect`, `amend_connection`, `disconnect`
- `open_question`, `resolve_question`

Each operation carries its source IDs and, where it asserts order or a branch target, the verbatim passage that supports it. The server applies operations to a persistent graph held with the session's ledger. The graph is never regenerated from the transcript in the normal path.

**Verification moves from a second author to code.** The application already verifies quotations against sources and settles bad citations without a model (`settle_generated_citations`, the passage checks behind `RouteRecheck`, `apply_workflow_update`). Run those checks per operation. An operation whose quote is not in its source is dropped and named in the open questions, exactly as a bad citation is settled today.

**The model audit shrinks to what code cannot decide.** Keep `route_gaps` and `connect_detached_routes` (they are deterministic detection plus one targeted question). Replace the always-on whole-map audit with:

- a structural review that returns **verdicts and field-level patches only** (step ID plus changed fields; connection identity plus verdict), never a re-sent step;
- run once at Wrap up on the finished graph, and at most opportunistically in the background while the participant is idle;
- never on the path between an answer and the diagram updating.

**Rules you must preserve** (all exist today; find them in the prompts and in `docs/WORKFLOW_UPDATES.md`):

- Only a participant statement, an explicit intake fact or an exact supplied document excerpt supports a claim. Documentary facts stay distinct from participant confirmation.
- Unknowns stay unknown and become open questions, never edges.
- An ordering of answers is not an ordering of operations; an order stated inside one answer is.
- A gate, check or hold lies on the route it governs (finding 2 of the November 16 run: a map must not bypass a mandatory hold).
- An edited earlier answer, a replaced file or an expired capability falls back to a full rebuild from sources.
- A participant correction can withdraw a recorded step or route only with its quotation.
- Stale work never replaces newer state; old results never add speech.
- Client-supplied excerpts are stripped at the HTTP boundary; underscore-prefixed server keys cannot come from the browser.
- No automatic paid retry loops in the background.

**Migration.** Do not switch over blind.

1. Build the ledger-driven graph behind a setting, running in **shadow** beside the current pipeline: both maps are produced, only the current one is shown.
2. Log both per revision. Add a comparison report: steps present in one and not the other, connections likewise, type differences.
3. Replay all 27 harness cases plus the 21 saved interviews in `docs/testing/runs/2026-11-16-process-capture/interviews/`. Have blind judges score both maps per case (section 10).
4. Switch the displayed map only when the ledger-driven map is at least as faithful on the aggregate and not worse by more than one point on any single case, and the specific accuracy checks in `docs/testing/runs/2026-11-16-process-capture/README.md` ("Accuracy checks to retain") still pass: GP-03 Method B ends in hold and every path to calculation passes method selection; FA-20 connects identity to screening; FA-04 keeps legal clearance on the route.
5. Keep the full rebuild path as the fallback and as the Wrap up reconciliation until two releases have shipped without a regression.

Saved interviews (`schema_version` 1; see `tests/fixtures/compat/`) must still open. If the stored shape changes, add a compatibility fixture and a migration.

Acceptance: median time from answer accepted to the updated diagram being available is under 15 s and p90 under 30 s on the 27-case replay; no map run is cancelled by a later answer; a diagram exists after every answer that states a step; fidelity as above.

### Phase 3. A presentation layer between evidence and picture

Add a deterministic step, in the browser or the server, that turns the evidence graph into a presentation graph. The evidence graph is never altered by it.

- **Start and end.** One start event feeding the entry step(s); an end event after each terminal step. Where the participant did not state the start or finish, the marker is drawn as *implied* (visually distinct, for example a dashed outline) and is excluded from exports that claim evidence.
- **Gateways.** A step with conditional exits is drawn as the activity followed by a small diamond, with one labelled branch per exit leaving from distinct sides. A real `decision` step is drawn as a compact diamond with its label outside, not a 360-pixel box.
- **Main path.** Derive a spine (longest evidence-supported path from the entry, preferring unconditional and first-stated exits) and lay it out straight; exceptions branch off to one side and rejoin where the evidence says they rejoin.
- **Lanes by role.** Offer swimlanes keyed on normalised actor. Decide deliberately what to do with `UNKNOWN` actors and with more than about seven roles. Lanes are a view option, not a schema claim about responsibility.
- **Dead ends and fragments.** A dead-end exception is shown with its open question on the canvas edge, not as a silent stub. Detached groups are shown as detached, as now, with the existing one-line notice.
- **Stability.** When a map changes, existing nodes keep their relative positions where the structure allows; add ELK interactive or position hints, and animate only what changed.

`web/workflow-graph.js` holds the layout (`routingOrder`, the `elk.*` options, `orderedComponents`), `web/workflow-layout-worker.js` runs ELK, `web/workflow-exports.js` and the BPMN download in Review produce exports. Update `docs/WORKFLOW_DIAGRAMS.md` to describe what is evidence and what is presentation, and keep its statement of what the diagram does not claim.

Acceptance: on the 14 maps in the run's `cases/` plus the replay set, every rendered diagram has one start and at least one end, no branch leaves an activity box directly, and blind judges score structure at least 7 of 10 on the median with no case below 5. `tests/test_workflow_graph.cjs`, `tests/test_workflow_scenarios.cjs` and `tests/fixtures/workflow-scenarios.json` are extended, not weakened.

### Phase 4. Push updates and a real job runner

- Replace the in-memory thread-per-session workers and fixed semaphores with one bounded job runner that has per-interview ordering, fair scheduling between interviews, latest-wins coalescing per product, and cooperative cancellation that actually releases the provider request.
- Push notes and map results to the page (server-sent events over the existing loopback server, standard library only) and keep polling as the fallback. The CSP is server-owned (`APPROVED_BROWSER_CONNECT_SOURCES`); same-origin event streams need no widening.
- Stream the capture's structured output so a step can appear as soon as its operation is complete, if the provider's streaming of structured output allows it. Check current provider documentation rather than assuming.

Acceptance: five interviews on one server each get a diagram for every answer within twice the single-interview time; Wrap up under 15 s for each; no dead time above 1 s between a result being ready and the page showing it.

### Phase 5. Live voice orchestrated by the server

Today the browser joins the speaking model to the notes and map team with timers (`receiveLiveCaption`, `scheduleLiveCapture`, `scheduleWorkflow`, the coverage note sent with `session.thinking.append`). Move that orchestration behind the server so it sees final transcript turns and feeds notes, graph operations and guidance without the browser in the middle. Also in scope:

- Give live mode the same transcription hints reviewed mode has (`TRANSCRIPTION_KEYWORDS`, language). Observed slips: "so OFAC" heard as "SOFAC", "Signatory A" losing its letter, "Passthrough" heard as "PassThru".
- The live interviewer is not gated. It asked three questions in one turn about a step the speaker had just said they did not know. Tighten `LIVE_TURN_POLICY` and feed it stated unknowns promptly. `docs/AGENT_TEAM.md` records why the pre-audio gate was given up in live mode; do not reintroduce a gate that delays speech without the owner's agreement.
- The guidance note reached the live model only after the last answer in every test, because it is held while anyone is speaking. Find a safe moment earlier.

Acceptance: spoken reply latency stays within 0.3 s of today's (1.0–2.3 s); notes within 15 s of a final caption; diagram within the Phase 2 targets; no map built from a partial caption.

### Phase 6. Files

- Ask the first file question after the quick pass for text-only files. The question reads excerpts from the native index, not the review output. It does need the quick review's disposition (parked or needing a reason excludes a file) and, for scanned or image pages, the visual transcription. A transcription arriving later changes the source revision and would fail an issued question's binding check with a 409, so files with visual pages keep waiting for those pages.
- Run review batches in parallel with a bounded pool, across files and within a file. Batches depend on each other only softly (the prior summary, last questions and observations); decide how to merge and test that review quality holds.
- Do not re-send the quick sample's chunks in the deep pass.
- Reconsider the hard stop at an estimated 12 requests now that batches are parallel.
- The map of a large file received 50 of 86 indexed sections in one test; make the coverage shortfall visible in Assets in the existing separate-facts form.

Acceptance: an 85-page text PDF produces a grounded first question within 20 s and a complete review within 60 s; the ten file cases in the run's `cases/F*.json` still read and attribute content correctly; the U1–U10 acceptance checks in the November 16 README still pass.

### Phase 7. Notes speed (only if the owner wants it)

Notes take 31 s median because most captures use the stronger model for reconciliation. Options are a fast capture followed by a reconciliation pass, or narrowing `reconciliation_targets`. This trades against the self-consistency fixes of the November 16 run (findings 8 and 9). Measure contradiction rates before proposing a change.

## 8. Constraints

- Follow `AGENTS.md`. Preserve `.env.local`, `.local/` and `work/`; they hold private settings and saved work and stay out of Git. Reuse the existing Python and Node runtimes; do not install another.
- The server is standard-library Python. Do not add dependencies without the owner's agreement and the repository's resource preflight policy.
- Never print, log or commit the provider key. Never send interview content anywhere but the configured provider.
- Run integration tests in an **isolated copy** of the tree, never in the working checkout: some suites start the launcher and would touch a running app on port 8774.
- A release is a commit on `main` that raises `VERSION` in `server.py`, with a `CHANGELOG.md` entry; between releases, add to "Unreleased". Keep `docs/API_CONTRACT.md` current when routes or response fields change.
- Work on a branch. Commit or push only when asked. Do not merge to `main` yourself.
- Model names and provider behaviour change. Before relying on a parameter (streaming structured output, reasoning effort, token limits), check the provider's current documentation.
- UI: remove or merge before adding. No new explanatory copy to make a state clearer.

## 9. How to run and measure

`AGENTS.md` is written for the Windows machine. On the Mac used for this run:

- Python 3.12: `~/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3.12`, always with `-I -B`. Node: `~/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node`.
- App: `python3.12 -I -B launcher.py --no-browser`, `http://127.0.0.1:8774/`, stop with `launcher.py --stop`.
- Tests in an isolated copy (`rsync` the tree without `work/`, `.env.local`, `.local/`): `python3.12 -I -B -m unittest discover -s tests -p <file>` and `node tests/run_all.cjs`.
- Suites that fail on this Mac with untouched code (Windows-only or timing): `test_knowledge_graph.py`, `test_log_viewer.py`, `test_raw_journey.py`, `test_raw_pipeline.py`, `test_raw_trace.py`, `test_raw_trace_http.py`, two timing tests in `test_workflow_updates.py`; `test_rejected_requests.py` hangs until killed. Compare against these before blaming a change.

The harness in `docs/testing/harness/` (copy it to a scratch folder as `lib/`, with an empty `cases/` beside it; copy `docs/testing/runs/2026-11-17-stress/cases/` there too if you want to replay):

- `serve.py ENVFILE APPDIR PORT [KEY=VALUE ...]` starts an isolated copy of the app with the settings from `ENVFILE` passed as environment and `RAW_TRACE_MODE=content`.
- `pc.py` plays a participant: `start CASE --port P --name "..."`, `answer CASE "text" [--voice] [--think S]`, `skip`, `upload CASE FILE...`, `wrap CASE`, `waitmap CASE`, `show CASE`, `timings CASE`. `--voice` synthesises speech with macOS `say` and sends it to `/api/transcribe`.
- `replay.py THINK TAG CASE@PORT ...` replays the participant answers of finished cases at fixed pacing. Use it for every before/after comparison so the answers are identical.
- `stages.py SCRATCH` reads per-stage model timings and worker events from each copy's `work/raw-trace`. `agg.py` and `arms.py` tabulate cases and replay arms; adjust their paths.
- `shim.js`, pasted into the page, replaces the microphone with a Web Audio stream so recorded speech can drive live voice. The audio files must be same-origin; the test copy had a small test-only addition to `STATIC_FILES` serving `web/t/*.wav`. Never add that hook to the real app.

Real-provider runs cost money. Use the fake-provider tests for logic and timing properties, and keep real-provider replays to the acceptance checks.

## 10. How fidelity is judged

A faster diagram that is less faithful is a failure. For every comparison:

1. Write the transcript and the map to one file per map, with no indication of which variant produced it.
2. Give each file to two independent judges with this instruction: the transcript is the only source of truth; list the distinct steps, decisions, branch targets and orderings the participant stated; check each against the map by step ID; do not penalise the map for things never said; an open question is the correct handling of an unknown; report stated steps, steps present, share of stated sequence links drawn, invented items, wrong items, missing items, disconnected items, an accuracy score 0–10 and a structure score 0–10.
3. Compare variants on steps present, links drawn and invented items first, and on the scores second. `judges.json` in the run folder holds the baseline judgements.

The participants' own evaluations in the run's `evals.json` list concrete defects per case (wrong step type, dead-end exceptions, steps left disconnected although the sequence was stated, page furniture promoted to steps). Use them as a regression list.

## 11. What to hand back

For each phase: the branch, what changed for the participant in two or three sentences, the before and after numbers from the same replay, the judged fidelity comparison, test results with any failure quoted, what was not done or not verified, and the documents you updated. If a target in this brief turns out to be wrong or unreachable, say so and say what you measured; do not quietly lower it.

## 12. Known limits of the evidence in this brief

- Voice tests used a synthetic macOS voice, not real microphones or accents.
- Six interviews shared one provider account at a time.
- The prototype comparison is three interviews; the audit-model comparison likewise.
- The Phase 2 timing target rests on the notes path already working this way at 14–33 s with larger outputs, and on a single 16 s incremental draw. It has not been built or measured.
- The estimate that field-level audit patches cut audit time by more than half comes from output sizes, not from a run.
