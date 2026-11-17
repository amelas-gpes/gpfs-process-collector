# Map lanes with stand-in providers, November 17, 2026

This run records what was verified for the first part of the [diagram brief](../../../enhancements/diagram-speed-and-layout.md) and what was not. **No request was made to the AI service**: the environment the work was done in had no provider key. Every number here comes from a stand-in whose draw and check take as long as the test says. It shows how the app schedules and publishes maps. It says nothing about how long the provider takes or how faithful a map is.

The baseline for comparison is the [November 17 stress run](../2026-11-17-stress/README.md) at `04e6ee3`.

## What changed in the app

| Finding of the stress run | Change | Verified by |
| --- | --- | --- |
| 1. A new answer cancels the map being drawn, and the cancelled request keeps its slot | The map being drawn finishes and is kept as the map through its answer. A cancelled provider request is ended within a second. | `tests/test_map_lanes.py`, `tests/test_provider_cancellation.py` |
| 2. The source audit takes longer than the draw and re-sends most steps | The drawn map is shown at once and checked beside it, on the difference since the last check. The background draw is given the map's rules again (they had been cut from its instructions since 0.30.0). | `tests/test_map_lanes.py`, `tests/test_map_check_delta.py` |
| 3. Timeouts and the output limit discard finished work | A failed check leaves the drawn map in place. A cut-off draw is asked for once more with a larger allowance. Longer background limits. | `tests/test_map_lanes.py`, `tests/test_map_check_delta.py` |
| 4. One map worker serves every interview | Two maps are drawn at once by default (`COLLECTOR_MAP_WORKERS`), one job at a time, the oldest first. Background work leaves two provider slots free for questions. | `tests/test_map_lanes.py`, `tests/test_provider_cancellation.py` |
| 5. Live voice starts a map from a partial sentence | The map starts from a finished caption. | `tests/test_ui_state.cjs` |
| 6. File review is serial and the first question waits for all of it | The first question about a text-only file is asked after its first pass. Two files are reviewed side by side; one file's requests stay in order. | `tests/test_document_review_lanes.py`, `tests/test_document_intake.cjs` |
| 7. Diagrams lack start and end nodes and branch from activity boxes | The diagram draws a picture of the evidence with implied start and end markers and a gateway after a step with several exits. | `tests/test_workflow_presentation.cjs`, and a render in headless Chromium |
| 9. The Live interviewer asked three questions about a stated unknown | Its instructions say one question per turn and no second request for a stated unknown. Wording only. | `tests/test_live.py` |

## Simulated pacing

The stress run had an answer every 45 s, a draw of 41 s and a check of 112 s. The stand-in runs about five hundred times faster: an answer every 90 ms and a check of 220 ms, with ten answers per case. Durations vary by a few milliseconds between runs.

| | Draw faster than the answers (60 ms) | Draw slower than the answers (140 ms) |
| --- | --- | --- |
| Map of the latest answer on screen before the next answer | 10 of 10, 64 ms after the answer at the median | 0 of 10 |
| Map on screen just before each answer goes through | the latest answer, every time | no map before the second answer, then one or two answers behind |
| Maps drawn for ten answers | 10 | 7 |
| Source checks during the interview | 4, each on the difference since the last | 4, each on the difference since the last |
| Maps cancelled by an answer | 0 | 0 |
| Map of the last answer | on screen when the last answer was sent | 75 ms after the last answer |
| That map checked | 197 ms after the last answer | 296 ms after the last answer |

In the stress run the diagram was there before the next answer for 7 of 139 answers and 65 maps were cancelled. The second column is the case to expect with the real provider at that pace: a draw took nine tenths of the answer interval there, and it will write more now that it is given the step-detail rules.

Five interviews on one server each got their map with two draw workers; the test allows three rounds of one draw plus a second for a loaded machine.

## Cancellation and slots

A loopback server stands in for the provider and holds its answer back for five seconds, the way a request that is not streamed behaves.

| | Before | After |
| --- | --- | --- |
| Cancelled request returns | when the provider answers (5.03 s in the reproduction; up to 240 s in the stress run) | within a second, as `cancelled` |
| Request past its time limit | at the limit only if the provider was silent at the socket level | at the limit |
| Provider slots for a question while three background requests wait | none guaranteed | two kept free |

## Real maps through the new rules

Thirteen final maps of the stress run that have no file evidence and validate against their own transcripts (`A-T01`, `B-T01`, `C-T01`, `C-T07`, `C-T11`, `STRESS-T06`, `STRESS-T09`, `T03`, `T04`, `T09`, `T13`, `V02`, `V04`) were used as material. For each, at four cut points, the difference between an earlier state and the full map reproduces the full map when applied; a removed step or route needs its quotation; and draws made during a check are carried onto a checked map that corrected one step and took another off. The eight file cases could not be used: their document excerpts are not in the run folder.

## In a browser

`tests/browser/typed-map.cjs` plays three typed answers in the real page, in headless Chromium, against a synthetic provider that takes 0.4 s to draw a map and 3 s to check it. It is optional and not part of `tests/run_all.cjs`, because it needs Playwright and a browser.

| After | The Workflow line showed, in order |
| --- | --- |
| the first answer | “Updating the map for your latest answer…”, “Updated through the latest answer · check pending”, “Updated through the latest answer” |
| the second answer, watched for 1.8 s | “Updating the map for your latest answer…”, “Updated through the latest answer · check pending” |
| the third answer | the same three lines as after the first |

The diagram then showed the three reported steps between an implied start and an implied end, with no page errors. The same run found that the page stopped asking once the notes of an answer had failed, so a map whose check finished afterwards stayed on “check pending”; the page now keeps fetching the map in that case. Saved maps from the stress run were also drawn in Chromium with and without the picture: no boxes overlapped and a layout took 60 to 300 ms.

## Not verified, and how to verify it

1. **Timings with the AI service.** Replay `T01`, `T02`, `T07`, `T11`, `V01` and `V03` at 45 s pacing with the [harness](../../harness/README.md) and compare with the stress run: time to the first diagram, the wait after each answer, and the final diagram. `stages.py` now also has `worker.workflow.checkpoint`, `worker.workflow.check_started`, `check_finished`, `check_error`, `check_discarded` and `worker.workflow.checked` to read.
2. **Fidelity.** Judge the maps as section 10 of the brief describes. Two things changed what the models are asked: the background draw now receives the routing, component and step-detail policies, and the check reviews differences instead of whole maps.
3. **How much the audit still rewrites.** The brief measured 89% of steps re-sent. That should fall now that the draw has the rules the audit was applying. Measure it again before deciding whether field-level audit patches are still worth building.
4. **The Wrap up comparison.** A map of the whole account replaces the incremental one when it cites an answer the other does not, or has more than about a seventh more steps. That threshold is a judgement.
5. **Windows and macOS.** Ending a request by shutting its socket was run on Linux only. The existing code already relied on the same call on those systems for replies in progress.
6. **Live voice.** The page-level rule is covered by its suite. No voice session was run.

## Suites

On Linux with Python 3.13 and Node 22, in a copy of the tree: all Node suites pass (94). All Python suites pass except three that fail the same way on the untouched `c60592a`: `test_knowledge_graph.py` (Windows-only process checks), two tests in `test_workflow_updates.py` that compare a computed time limit with an exact number, and `test_rejected_requests.py`, which does not finish.
