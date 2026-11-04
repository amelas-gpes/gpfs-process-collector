# Interview intelligence — 0.25.0

**0.25.1 follow-up:** the detailed selection policy is now shared with GPT-Live and its delegated backend. The original 0.25.0 merge retained the broader live interviewing rules but omitted this newer policy from the live prompt. [Live prompt validation](LIVE_PROMPT_PARITY.md) records the correction and its separate measurements; the reviewed-turn evidence below remains historical.

Version 0.25.0 merges the local interview-intelligence candidate with upstream live-voice changes through 0.24.1. GPT-Live remains the default spoken interviewer; full managed-team captures update its notes and suggestions in the background. The question-only concurrent path serves typed and reviewed-turn interviews, and cannot intercept active live capture requests. Switching to live cancels pending concurrent capture work. Suggested process titles remain separate from source context; manual context changes invalidate pending responses and reviews.

The provider and browser measurements below describe the **pre-merge reviewed-turn candidate**, not the default live voice. They do **not establish acceptance of the immediate-conversation requirement**. Provider trials show useful improvements and remaining question-quality failures; reviewed-turn synthetic audio still has substantial silence. Physical participant testing and sustained, adaptive interview acceptance remain outstanding for the merged release.

## Verified diagnosis and changes

The previous fast path supplied context, chronological turns and action with a short generic question policy. It omitted the detailed curiosity rules, eleven-topic rubric, authorized excerpts and background gaps. A label such as “connects automatically” could therefore lead directly to another step. The richer background instructions did not govern the response the participant heard.

The question path now uses the existing `QUESTIONING_POLICY`, `CURIOSITY_POLICY`, `CORRECTION_SCOPE_POLICY` and `TOPIC_RUBRIC`, plus professional-context and selection guidance. It examines the whole latest answer for missing mechanisms, revisits volunteered branches, and widens to other topics when a local detail is understood or unavailable. Industry knowledge guides questions; it is not process evidence. Domain ambiguity, personal activities, targeted corrections, unanswered information and local “no” answers are addressed explicitly. The same rubric remains available to capture and final review.

Every ordinary question on the concurrent typed/reviewed path still makes **one** structured model call at low reasoning effort. Its input includes the full validated transcript and current server-authorized document selection. The response still cannot grant completion. Document-based openings use the excerpts instead of a canned starting-point question.

An optional, bounded analysis index comes only from the server's accepted capture, never client memo claims. It identifies the last analyzed turn and all later turn IDs, preserves parked threads and topic gaps, and is labeled fallible derived advice. An edited transcript prefix, context change, scope/revision change or changed excerpt selection suppresses it. Later answers and corrections take precedence. Missing or truncated advice is not evidence that a topic is complete. Ordinary questions never wait for capture or workflow generation.

Two further problems were exposed during validation:

- The standing foundation still demanded commercial variation fields for personal equipment setup. It and fact-capture guidance now make charging and variation-removal questions conditional on the actual activity. Unknown applicable information remains unknown.
- Transcript-only maps previously lacked the source audit used by document-based maps. They now receive a separate source-check request inside the bounded background worker, within the lead's existing two-call budget. Unsupported unpublished connections can be removed while known actions, prerequisites and explicit gaps survive. This adds background cost and checkpoint time; it adds no question-path call.

Shutdown also prevents late background responses from reopening document stores. The full regression run exposed a SQLite cleanup race; source reads are now drained locally when closing, without waiting for provider requests.

## Voice behavior and measurements

In reviewed-turn mode, an empty AI reader connection is prepared alongside transcription and question generation. No transcript or proposed question is sent to that connection before the existing speech authorization passes. Generated audio is still buffered and its returned text checked before playback. Cancellation, expiry, voice changes and failed preparation dispose of unused connections; fallback retains the existing playback path.

The app records at most 100 local timing records, with no audio, transcript, credentials or process names. **Settings → Save voice timings** exports them. Timings cover detected speech end, endpoint delay, recorder completion, transcription, question request, actual browser playback start and playback completion. Review acknowledgments do not count as meaningful responses. Failed/canceled turns retain unknown measurements rather than reporting zero delay. Browser events do not establish what a physical speaker emitted or how a participant experienced it.

The measured candidate used a 2.2-second silence detector. The merged reviewed-turn path inherits upstream's 1.8-second detector, noise-blip filtering and continued listening after an empty transcription (three consecutive empty transcriptions stop the session). Retained-audio retry remains available. Reviewed mode still uses turn-taking microphone behavior and full audio validation, without streaming recognition, semantic endpointing or spoken interruption. No new provider latency measurements have been made with this merged path; default GPT-Live behavior is separate.

Actual browser/provider rehearsals used installed Chrome 156, native MediaRecorder, existing fictional WAV fixtures, real transcription, the question service and real AI playback, with Chrome's physical output muted:

| Trial | Endpoint | Transcription | Question request | Playback preparation | Speech end → meaningful audio |
| --- | ---: | ---: | ---: | ---: | ---: |
| First successful prepared run | 2.202 s | 0.823 s | 1.441 s | 1.051 s | **5.528 s** |
| Preparation disabled, current question policy | 2.201 s | 0.675 s | 1.816 s | 1.752 s | **6.448 s** |
| Preparation enabled, current question policy | 2.217 s | 1.554 s | 2.266 s | 1.050 s | **7.092 s** |
| Correction/unknown answer | 2.203 s | 1.400 s | 4.447 s | 1.427 s | **9.489 s** |
| 23.5-second composite answer | 2.201 s | 1.686 s | 2.695 s | 0.900 s | **7.489 s** |

Recorder finalization adds 4–11 ms in these trials. Preparation shortened its own phase in the paired sample, but the prepared trial had **worse total latency** because transcription and question generation varied. These are individual samples, not a controlled performance estimate, reliability distribution or agreed definition of “instant.” They do **not** satisfy the brief's immediacy claim. All successful trials verified authorization/text agreement before playback, completion of playback, listening resumption, and microphone cleanup. The first rehearsal failed on a native timer binding error; that result is retained, the error was fixed, and the default timer binding has a regression check.

## Question-selection evidence

The explicit opt-in runner is `tests/evaluate_interview_intelligence.py`; importing it makes no provider calls. It retains inputs, outputs, failures and request times. All cases are fictional.

- Initial shared-guidance trial: candidate median 2.446 s versus previous 1.805 s across eight paired requests; the candidate still skipped important local mechanisms.
- Selection-priority refinement: candidate median 2.055 s versus previous 1.571 s. Drone readiness still failed in that sample.
- Medium-reasoning experiment: median 4.258 s, maximum 6.219 s across eight candidate requests. It improved some probing but imposed additional delay, so it was **not selected**.
- Final low-reasoning candidate: median 1.969 s, maximum 2.703 s across twelve requests; paired previous-policy median 2.462 s, maximum 6.641 s. Provider variability and other active validation work prevent interpreting this as a proven speed improvement.

The final candidate asked about usable connection signals, dispatch readiness, soil-watering need and Operations handoff. It honored a corrected reviewer, did not re-ask explicitly unknown battery voltage, used document excerpts without equating them with current practice, and did not request completion after a local “no.” Four additional cases concerned packing, irrigation, IT release and volunteer book loans.

Remaining failures are explicit: reconciliation and ambiguous-domain responses bundled two information requests; the damaged-book response may revisit an already described availability update instead of following the tray route. These observations prevent claiming consistently insightful questioning or a fully reliable one-request contract. The known drone example was used during refinement, so success there is development evidence, not held-out acceptance.

## Source-to-deliverable comparison

A fictional twenty-turn, ten-answer personal-drone transcript was replayed through actual question selection, background capture, audited workflow and draft generation. It is a scripted source replay, **not an adaptive human interview**. No private saved participant interview was sent. The final replay returned the question in 3.734 s, synchronized capture/workflow in 77.844 s, and generated/audited the requested partial draft in 152.422 s.

| Topic / source | Retained in final replay |
| --- | --- |
| Name and scope, `u1` | Personal garden drone setup; alternate name; flying outside scope. |
| Purpose, `u1` | Prepare to take garden pictures; no invented commercial result. |
| Trigger, `u2` | Participant decides pictures are needed; roughly monthly by choice; no fixed deadlines. |
| End point, `u6` | Live image, green bars, battery ≥40%, no cracks, kit carried outside before takeoff. |
| Accountability, `u6` | Participant owns the overall result; no handoff. |
| Flow, `u3–u6`, correction `u10` | Normal cupboard route retained; spare location corrected to lower drawer only. Spare continuation stays unknown. |
| Checks, `u4–u7` | Latch click/pull, image/link indicators, propeller inspection, battery reading and recheck, explicit stop routes; no invented approver or check records. |
| Variations, `u3`, `u5`, `u8`, `u10` | Missing-drone and low-battery changes retained in flow and variations. Personal billing non-applicability retained. |
| Pain, `u7` | Stiff latch and a few minutes' estimated effort, attributed as an estimate. |
| Risk, `u7` | Loose battery may disconnect and cause a fall during later flight. Other risks remain unestablished. |
| Materials, `u9` | Booklet mentioned, unavailable here and unreviewed; no invented document review. |

The first replay imposed a propeller-before-battery edge while also calling the order unknown, and asked about removing the spare. The revised replay removed that unsupported order and irrelevant removal question. Both final map and draft preserve the prerequisites in descriptions and leave precise ordering/connection gaps visible. Neither invents a spare-route rejoin.

The final draft remains partial for flow, checks, variations, risks and materials. Known successful conditions survive, but the diagram is not a complete executable route: check ordering, failed connection/latch handling, later restart and spare continuation remain unresolved. Automatic graph validation also adds generic missing-outcome questions. Their wording can be less precise than the source-specific gaps. Provisional capture statuses and independently audited draft statuses are distinct; neither grants participant confirmation or owner approval.

## Reproducibility and remaining acceptance

Pre-merge validation passed **618 Python tests and all 20 JavaScript suites**, including speech authorization, prepared-connection disposal, browser timer binding, meaningful-audio timing, source changes, lagging advice, correction boundaries, workflow auditing and shutdown races. The merged 0.25.0 code passed **642 Python tests and all 20 JavaScript suites**, including added live/concurrent routing, cancellation and title-context integration checks. Whitespace checks passed. These deterministic checks establish implementation contracts, not model comprehension or subjective voice quality.

Local evidence is under `work/interview-intelligence/`: all question trial receipts, failed and successful browser receipts, scripted source, initial and revised capture/draft files, Python results and frontend results. Merge validation is under `work/main-publish-2026-11-04/`. These files remain ignored by Git. Existing unrelated files, settings, saved work and databases were preserved. The provider measurements describe the locally validated candidate before publication.

The existing Python 3.12.14 and Node 24.22.1 were reused. Core additions use the standard library and browser APIs. The browser preflight found Playwright 1.62.1 but its browser registry searched only download-cache roots; installed Chrome was verified separately at its existing Program Files path and functionally exercised. No browser/runtime/package was downloaded, installed or copied. An attempted new local SAPI recording returned access denied, so the rehearsals reused the existing, source-documented fictional fixtures. No security setting was changed.

Before calling the assignment resolved, test sustained physical conversations across ordinary and long answers, pauses, corrections and long histories in the selected voice mode. Measure perceived delay through meaningful audio, sentence cutoffs, interruption needs, recognition errors and question relevance together. Independently score held-out domain interviews and their final artifacts against source facts, including secondary threads and unavailable gaps. Define an acceptance criterion with participants; this release does not invent one. The merged default live path changes the serial audio architecture, but its perceived quality and capture continuity still need direct acceptance testing.
