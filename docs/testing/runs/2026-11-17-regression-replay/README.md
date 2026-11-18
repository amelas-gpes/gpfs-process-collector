# Regression replay of Process Collector 0.32.0

The current GitHub build accepted every answer in the dedicated typed interviews and every test upload. A completed source check still allowed missing prerequisites and a reference note presented as work. The management-fee workbook also produced no map after a real provider timeout. People using these maps for operating procedures should review their handoffs and controls against the cited material.

The baseline was GitHub main at `dde4da1f4ebecba60bb0b43d0c482f92fe967995`, runtime build `9cd8c6ef8831c473b55a5ef99cd7d1a6383c66dd28362f7226328df800d35937`. The fixes were tested on branch `qa/collector-regression-2026-11-17`. Interviews, uploads, retries, and browser imports used separate local test stores. The dates below identify the original runs.

## Live replay

| Saved cases | What was replayed | Result |
| --- | --- | --- |
| November 16 typed interviews | All 21 original contexts and all 122 participant answers, in their recorded order, with fresh model replies | All 21 returned 16-topic notes and a workflow. Ten passed the background source check. The other eleven required an explicit **Update workflow**. Median question latency was 3.10 seconds, p95 was 5.52 seconds. |
| November 16 uploads, U1–U10 | Verified the original files by hash, indexed them, then uploaded them to live interviews | All ten returned a first question, notes and a source-checked map. The 24-page text PDF indexed all 24 pages and took 122.71 seconds to its first question. The shortest first question took 6.49 seconds. |
| November 17 typed stress, T01–T13 | All 76 participant answers across 13 interviews. T10, T12 and T13 were replayed after an initial local refusal | All 76 received fresh replies. All 13 finished with notes and a source-checked map, including retries. Median question latency was 2.73 seconds. |
| Five concurrent repeats of typed stress cases | 32 saved answers submitted to five simultaneous interviews, with recovery calls after budget refusals | All 32 received a fresh reply. All five maps passed the final source check, including retries. Two notes jobs still reported a local budget error, in T03 and T13. |
| November 17 file stress, F01–F10 | 11 documents across 10 workflows. All files received fresh review. F05, F08 and F10 resubmitted their intermediate answers. F08 received three fresh replies and one local 429. The other seven restored the saved participant transcript for Wrap up | All ten reached a question, including two fallback questions. F01’s fallback referred to the operational hold, and F04’s was generic. Nine returned notes. Five produced a map for the current transcript. Two of those had independently observed completion of the app's source check. |
| Recorded voice, V01–V04 | 20 original clips, 615.8 seconds of synthetic speech | Every clip was transcribed and received a follow-up. Comparison with the 1,902-word reference counted 20 edits (1.05%). The letter in “Signatory A” was lost. Budget guards limited downstream notes and maps. |
| Live voice, V05–V07 | 14 prerecorded participant utterances fed to three real browser voice sessions | All sessions returned captions and audio. Chrome reported zero page errors. Rapid playback could overlap the model. Physical microphones, speakers and acoustic echo were outside this replay. |

The baseline was used for the November 16 interviews, original upload inputs, file stress and voice. Some later typed and concurrent recoveries used the fixes already applied at that point (`09ae281` and `2c8f7a0`). Replays used the recorded participant evidence. Questions, timing, parallelism and model generations can vary between runs. A current draw, a completed background source check, and a successful manual update are reported separately. A citation check establishes that the referenced turn exists. A human comparison with the source is needed to establish whether an edge or an action is correct.

The original [process capture](../2026-11-16-process-capture/README.md) and [stress run](../2026-11-17-stress/README.md) contain the archived inputs. The new receipts contain timings, status, retry outcomes and per-case observations. [Typed interviews](typed-interviews.json) · [Uploads and typed stress](uploads-and-stress.json) · [File interviews](file-interviews.json) · [Voice](voice-interviews.json)

## Findings still open

| Case | Evidence from this replay | Effect |
| --- | --- | --- |
| F02, trial balance | Page 1 calls for confirming scope and rolling forward, then extracting the trial balance. The checked 26-step diagram gave these activities separate entries, with no route between them. | A reader can enter the extraction procedure without seeing its documented predecessor. |
| F03, bank administration | The checked diagram turned a staff-knowledge sidebar about Kyriba into an isolated “Validate Kyriba requirements” step. | Reference material appears to be a required action. |
| F05, management-fee workbook | The three workbook sections were reviewed and all 16 note topics were retained. The first map hit the local budget. A manual retry reached the real provider and timed out after 120 seconds. | The interview had notes but no current diagram. The timeout and the local refusal were separate events. |
| GP-03, allocation and carry | Method B correctly leads to a hold. Three schedule/carry steps remained unreachable from the declared start. On the fixed branch the app identified the gap and asked about it. A real bounded repair preserved the 22 steps and 24 edges and left the missing link unresolved. | The schedule and review path does not show the prerequisite zero-sum proof. [Repair receipt](gp03-source-review.json) |
| FA-04, legal clearance | A checked 11-step map had four edges. Legal clearance was detached from completion, although open questions acknowledged the missing relationship. | The diagram can be read as allowing completion before clearance. |
| FA-07 and FA-20, handoffs | FA-07 listed the same FA-05 equalization handoff twice. FA-20 retained a single Compliance Officer escalation and cited only the later of two corroborating statements. | The handoff count and the completeness of supporting evidence need review. |
| F01, long PDF | The 85-page file reached a question in 243.25 seconds, compared with 161.49 seconds in the archived run. The one-page F03 input took 9.05 seconds here. | Large-file intake can take several minutes. These are single-run measurements. |

F09's initial diagram mentioned a 90-day escalation but drew only the cleared-payment branch. F10 returned a connected, 24-step diagram where the archived run had no current map. A completed source check was unverified for both draws. F04, F06 and F08 encountered local map-budget limits. The shared test-server token limit and conservative per-request reservations affected the file run’s completion rate.

All 959 step and connection citation references across the November 16 typed cohort resolved to participant turns. All saved node IDs and edge endpoints validated. Of 23 logged route-repair attempts, eight connected the requested parts and fifteen left a gap open. The examples above show why correct references and a green status alone do not establish map fidelity.

## Fixes verified during the replay

| Change | Verification |
| --- | --- |
| Recognize an explicit request to stop before leaving for a meeting, while preserving descriptions of a reviewer leaving | The stop case reached the application pause. All 18 saved question-intelligence cases met their response contract on the repeat, including 17 fresh model questions. One secondary-thread question still asked about the trigger when the stored scenario favored clarifying the guest. |
| Preserve the local usage-limit explanation during document review and the HTTP 429 status at Wrap up | A deliberately capped replay of F09 kept the two unread visual pages visible and reported the local limit. The Wrap up HTTP regressions cover daily and per-interview limits and preserve the saved answers. |
| Flag branches unreachable from a single declared start and preserve full historical question registers | The fixed detector identified the disconnected GP-03 branch. Synthetic cases cover a supported repair, separate starts and a saved question list at its limit. |
| Retain each role, action and record in a short-register document review | On the baseline, the citations were valid but the detailed observations omitted the instructor and schedule. Three fresh reviews with the revised prompt included all required terms with valid references. |
| Interrupt non-streamed provider reads when cancelled on Windows | Local silent and fragmented provider fixtures exercise cancellation while reading headers or a body, and check complete on-time answers. |
| Correct the actor-attribution evaluator and cross-platform test fixtures | A saved model response correctly attributed filing to the registrar. The old evaluator interpreted “the filed waiver” as an action by the instructor. The corrected scorer passes that response and retains the explicit wrong-actor check. Fixtures also cover Windows path spellings, delayed directory handles and orderly worker shutdown. |

The registrar map and draft achieved operation and route precision and recall of 1.0 on their small benchmark. Both contradiction checks caught the planted conflicting owner, and the matcher left unrelated interviews unlinked. These figures apply to that fixture. [Supplemental results](supplemental-evaluations.json) · [Stored evaluation commands](../../../../tests/evaluate_analysis_replay.py)

## Repository tests and browser checks

On the untouched GitHub build, macOS passed 1,786 of 1,864 Python tests, with 78 skips. Windows found seven failures and two errors on its first full run. These included two real cancellation failures, five path-comparison differences and two temporary-directory cleanup errors. The fixes and follow-up runs also corrected races in test teardown. [Initial Windows run](https://github.com/amelas-dev/ai-process-collector/actions/runs/44207197710)

On `b2aff91d744e2db1f61199eff1f82c991fb41842`, macOS passed 1,793 Python tests in 134.07 seconds. The 78 skips comprised 75 platform or runtime checks and three absent private reference inputs. All 95 Node suites passed in 61.8 seconds, and all five Chrome programs passed on identical application code. The public runtime build ID for the fixes was `69c579cb951b4f5246de45fa7e3337da7822419a7cbb571d343fdedf2da98025`.

On the same commit, Windows passed 1,866 Python tests across three jobs, with five skips. Three private reference inputs and one optional PDF runtime were unavailable. One address-reuse test applies only to other operating systems. [Final Windows run](https://github.com/amelas-dev/ai-process-collector/actions/runs/44211435631)

The five real Chrome checks covered desktop and mobile notes selection, 36 navigation actions, a three-turn typed interview through its diagram, trace handling across tabs, and a hidden tab returning after the default 95-second delay. The updated build displayed the result 3.94 seconds after readiness, within the five-second limit. Importing and re-exporting all 21 archived November 16 interviews preserved all 250 turns, including 122 participant turns.

The export replay opened all 22 archived nonempty diagrams in Chrome. All 378 arrows met their source steps within one SVG unit. Two explicit **Update workflow** paths issued one request each and preserved the notes. Seven additional offline checks exercised 13 saved real-provider maps and the prototype's richer-map-on-Wrap-up case. The historical A/B/C timing and blind-judge study was not rerun. [Diagram baseline](../2026-11-17-diagram-review/README.md) · [Map scheduling baseline](../2026-11-17-map-lanes/README.md)

## API usage

The approved allowance was **$25**. Recorded text usage, transcription duration and the live connection windows give an estimated **$10.79**. A conservative calculation including reserves for interrupted or unmetered calls gives **$20.93**. These are estimates, and actual provider billing was unavailable. All paid QA listeners were stopped. [Per-cohort usage and assumptions](usage.json) · [Luna pricing](https://developers.openai.com/api/docs/models/gpt-6-luna) · [Terra pricing](https://developers.openai.com/api/docs/models/gpt-6.1-terra) · [Live voice pricing](https://developers.openai.com/api/docs/models/gpt-live-1) · [Transcription pricing](https://developers.openai.com/api/docs/models/gpt-transcribe)
