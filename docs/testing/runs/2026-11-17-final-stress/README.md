# Final stress run, November 17 and 18, 2026

Thirty-four processes from the [process library](../../process-library/README.md) and the built-in example were run against Process Collector at commit `dde4da1` (0.32.0) through typed, file, recorded-voice and simulated live-voice interviews, each ending in Wrap up and Create draft. No participant answer was lost, and questions came back in about three seconds. Nine defects were found and fixed during the run. On November 18 the eleven things that run had left open were taken up one by one ([round two](#round-two-november-18)): Create draft now waits about a third as long after Wrap up, the draft agrees with the map and notes the participant saw, and Wrap up says what is saved. What is still true after both rounds is listed under [what remains](#what-remains).

This folder is a record. A new test does not need it; use it as a baseline or to replay a case.

## What was run

| Cases | Mode | Build | Variation |
| --- | --- | --- | --- |
| T01–T08 | Typed | `dde4da1` | Agent participants: everything in one answer, step by step with branches, vague then precise, middle of the process only, out of order with a correction, terse, rambling, exceptions first |
| T09–T14 | Typed | `dde4da1` | Scripted participants: two steps per answer, one step per answer, mostly unknown with two skips, two answers then Wrap up |
| F01–F08 | Files | `dde4da1` | Agent participants: 4-page and 24-page PDF, 47-page PDF, small CSV, workbook with a hidden sheet, PNG image, scanned PDF, two files at once |
| F09–F11 | Files | fixes | Three-row CSV added after two answers, a file with one short answer, a file followed by a correction that contradicts it |
| V01–V04 | Recorded voice | fixes | Synthetic speech at 170 to 235 words a minute through `/api/transcribe`, including two monologues of over two minutes |
| L03, L04 | Live voice, simulated | fixes | Two transcripts replayed one exchange at a time through the routes the page calls after each spoken answer |
| C01–C05 | Typed | fixes | Five interviews at once on one server |
| X01 | Typed | fixes | The built-in example's thirteen answers given to the live interviewer |
| D-*, E-*, R-* | Replay | fixes | Draft retries of the cases whose drafts failed or diverged; the answers of F02 and F08 replayed for their questions |
| Browser | Typed and a file | both | The example, a typed interview, a file added in Assets, Wrap up, Create draft, every Review tab, Submit process, the recovery copy |

Agent participants answered from the library and left open what it marks unresolved. Scripted participants narrate section 8 of a process without an agent ([`scripted.py`](../../harness/scripted.py)). The real provider was used throughout, in isolated copies of the app, one interview per server unless stated. Live voice in a browser with a microphone was not run; see the device check in the [demonstration guide](../../../DEMO_GUIDE.md).

## Results

| Area | Result |
| --- | --- |
| Next question | 3.1 s median per case, 7.0 s at most (23 interviews, 157 answers on `dde4da1`); 2.5 s median with the fixes |
| Notes after an answer | 29 s median per case, 10 to 35 s |
| Map during the interview | Shown from the first answer on; 12 of 23 final maps on `dde4da1` were one connected flow, 1 had an end node |
| Wrap up | Replies at once with "N of 16 are open" in every case; 50 to 90 s with five interviews on one server |
| Create draft, `dde4da1` | 20 succeeded in 98 to 434 s (336 s median); 3 failed on every attempt |
| Create draft, with the fixes | 21 drafts succeeded in 86 to 545 s (264 s median), including the three that had failed (481 s, 513 s and 421 s) and the 60-step interview once more on the applied build (545 s, of which the audit took 323 s). The one failure is the cut-off draft described under fix 9 |
| File to first question | 5 to 82 s; 5 to 21 s for files of up to seven pages |
| Transcription | 26 to 148 s of audio in 1.4 to 5.7 s; word error 0 to 5% |
| Live voice, simulated | Notes 13 to 41 s after a spoken answer; the checked map 62 to 161 s after it; all 11 updates succeeded |
| Lost answers | None: every one of 239 answers in 41 interviews is cited by the notes of its case, and no name or number from the scripted answers is missing from notes, map and draft |
| Five interviews on one server | All five finished with a connected map and a draft; no provider call failed |
| Server restart mid-interview | The next answer was accepted after one automatic retry and the notes caught up |
| Test suites with the fixes | Python 126 of 131 files and Node 95 of 95; the five failing Python files also fail on `dde4da1` on this computer |

Agent participants scored their own cases from 1 to 5: questions 2 to 5, notes 4 to 4.5, map 2.5 to 3.5, draft 3 to 4, speed 2.5 to 4.

## Fixed during the run

| # | Defect | Fix |
| --- | --- | --- |
| 1 | After the example and Start your own, Add files stayed disabled with "Choose Start your own before adding a real file." The file list is redrawn before the example flag changes and not again. | `web/documents.js` `syncAttach()`, called from `updateControls()` |
| 2 | The draft audit had a fixed 240 s while it writes the whole draft out again. Drafts of about 20,000 tokens (two interviews of 2,100 and 2,600 words) and a 14,400-token draft from a seven-page file timed out on every attempt, after four to eight minutes of waiting. | `server.py` `draft_audit_timeout()`: 240 to 540 s by the size of the candidate; the browser waits up to 990 s |
| 3 | Generated routing questions ("Does any incoming route start S7 …") led Questions for the process owner, ahead of the questions the draft calls its priority ones. | `add_workflow_questions()` appends them |
| 4 | Nothing moved on screen during the minutes a draft takes. | A running time beside "Building your draft · usually 3 to 6 minutes" |
| 5 | The report and the Markdown export showed a step's rule source as an internal id (`t002`). | `sourceCaption()`, as for every other source |
| 6 | After a complete written procedure was uploaded, five of six questions asked the participant to explain a step the file states. The reviewed-turn instructions forbade that; the fast question policy, which asks most questions, did not. | `QUESTION_POLICY`; two of six on replay, the others about gaps |
| 7 | A question the participant skipped was asked again two answers later. Skip adds no turn, so the question model was never told. | `skipped_questions` in the question model's input: a question followed directly by another question. A question that a file notice or a Wrap up reply displaced is not listed |
| 8 | A question reply that spent its 600-token allowance on reasoning failed the turn with HTTP 502. Seen once, on a file case, after fix 6. | 1,000 tokens, one more request with 2,400 if cut off, then a deterministic question |
| 9 | The draft re-derived the map and came out different from the one shown during the interview: 8 of 34 steps kept their id and title in one case, a 27-step map became 5 steps in another, connected maps came out in pieces. | The draft keeps the working map's supported steps and routes when the map has up to 40 steps; the audit still removes what the sources do not support. 24 of 24, 27 of 28, 33 of 34 and 27 of 27 steps kept on replay. A larger map keeps the earlier instruction: told to keep a 60-step map, the draft ran past its output allowance |

An independent review of the patch found five things, all corrected before it was applied: the skipped-question list read turns from which file notices had already been removed, the question model no longer saw any routing question once a map had twelve others, a Wrap up reply could make the question before it count as skipped, the Markdown export named a rule source differently from its evidence section, and a draft candidate was kept for less time than its longest audit.

The patch is `fixes.patch` in this folder. Each fix has a test: `test_documents_asset_states.cjs`, `test_draft_time_budget.py`, `test_open_question_order.py`, `test_ui_state.cjs`, `test_question_repeats.py`, `test_draft_keeps_working_map.py`.

## Round two, November 18

Each item below was open at the end of the first round. Every change was checked against the AI service on isolated copies, and the page itself in a browser.

| # | Was open | Now |
| --- | --- | --- |
| 1 | Create draft took two to nine minutes: a draft, then a source check that wrote the whole draft out again. | The check returns its corrections and the server applies them (`draft_audit.merge`); it wrote 3,500 to 8,900 tokens where it had written 13,000 to 27,000, and still corrected steps, routes and topics. The page asks for the draft's first half when the participant wraps up (`prepare_only`), so Create draft waits only for the check. The topic review after the check runs as four groups at once. Timings below. |
| 2 | A draft could not exceed 22,000 output tokens (about 57 steps). | The allowance follows the map and the account up to 40,000, with the time to write it. The 60-step interview, which was cut off when told to keep its map, wrote a 77-step draft in 442 s. |
| 3 | One map of 23 had an end node; maps came out in pieces. | A stated start and a stated finished condition are drawn as start and end nodes. The example's thirteen answers gave one start and two end nodes (none before) and one unconnected step (two before). A step nobody connected is still left unconnected, with a question: no route is drawn without a source. |
| 4 | Wrap up said “N of 16 are open” after any interview, and a complete capture was never reached. | “Your account so far is saved. 6 of 16 topics are complete and 10 are partly covered; the Notes list shows what is missing. You can create a draft from what is here, or keep answering.” See [what remains](#what-remains) for the complete-capture test. |
| 5 | The notes and the draft gave one topic different statuses (134 places in 45 drafts, about three a draft). | The draft writes its topic notes from the interview's notes: nine drafts then differed from their notes in 0 to 2 topics, most often a process name that the source check still marked partial. The check is now told not to lower a status for a detail nobody raised. |
| 6 | Reviewer notes read like a log; “UNKNOWN” 44 to 74 times a draft. | Notes say what to look at again in a reader's words and begin with one statement that the draft is AI-generated. In Review, a step's unreported details are named on one line (“Not captured: Control type, Entry mode, Rule source”); the exports keep a line for each. |
| 7 | A hidden workbook sheet was quoted like a visible one. | Its excerpts are labelled: “workbook.xlsx · Notes!A1:C4 · hidden sheet”. |
| 8 | A rule sentence from a file could become a step of its own. | The map rules say a rule, limit or definition stays with the step it governs. |
| 9 | Occasional double questions (9 of 442); a terse participant kept on two subjects. | A second request joined on with “, and …” is cut from the question; the interviewer is told to ask one thing and to leave a subject after two thin answers. The browser check then found the same question asked twice word for word after an answer about something else; that is now replaced, and the interviewer told to follow what was said. A 45-answer interview showed the interviewer staying on one exception branch for some twenty questions while three topics were never asked about: every so often a question is now given the open topics to turn to (see round three for the form this took). |
| 10 | Transcription slips that change meaning. | The process name and the names, acronyms and codes of the answers so far go to the transcriber as spelling hints. A dictated answer is still shown for checking before it is sent. |
| 11 | `/api/workflow`, the compatibility route, cut its reply off in four of six calls. | Its first reply spent its whole 12,000 tokens on reasoning. It is asked once more with 32,000 and its check is given the time a large map needs: a whole fourteen-turn transcript in one request returned 23 steps and 26 routes, in 430 s. The page does not use this route. |

### Create draft, before and after

| Interview | `dde4da1` | Corrections only | With the head start: wait after the click |
| --- | --- | --- | --- |
| 27-step map, 5 spoken answers | 260 s | 204 s | 76 to 106 s in four runs (head start 89 to 117 s) |
| 28-step map, 10 typed answers | 358 s | 271 s | 141 s (head start 146 s) |
| The example's 13 answers, 32 steps | 339 s | | 155 s (head start 151 s; topic review not yet grouped) |
| 60-step map, 12 typed answers | 545 s, or cut off | 442 s | not run |
| A seven-page procedure and one answer | failed on every attempt; 421 s after the first round | 296 s | not run |
| A workbook and one answer, 10 steps | | 217 s | not run |

The head start runs while the participant reads the Wrap up reply. A click that comes before it has finished waits for it and does not write a second draft: in the browser, a 12-step draft was ready 89 s after a click made 50 s after Wrap up. It costs one draft generation for a Wrap up that is not followed by Create draft; `DRAFT_PREPARE=off` turns it off.

Test suites with both rounds applied: Python 128 of 133 files and Node 96 of 96; the five failing Python files fail on `dde4da1` on this computer too.

Three reviewers read the round-two patch independently, one each for the draft path, the interview path and the page. They reported ten defects, all corrected before the patch was applied. The ones that mattered: a draft made from files alone could not have a step removed by its check (the wire schema allows no `remove_steps` without a participant turn, so the fields are named `drop_steps` and `drop_connections`); a candidate whose merged draft failed validation was kept and failed the same way on every retry; the question trimmer could cut a question down to its opening clause (“When the invoice arrives?”); the head start was started before the answer to the final check, for an account that was about to change; and the status line promised a short wait for a first half the server no longer held.

## Round three, November 18: the questions themselves

The owner's concern was that questions were sometimes generic or asked for something already said, and that the interviewer should read as a subject-matter expert, with the immediacy of the live voice kept. It had not been fixed, and it was measured before anything was changed.

**Typed interviews.** Three participants, each given a library process and a persona (a precise fund accountant, a terse senior associate who sidesteps twice, a team lead who starts with what goes wrong), answered ten to twelve questions and graded every one the moment it appeared: strong, acceptable, generic, repeat, off target or double, with an expert score from 1 to 5. They were told to grade strictly.

| Run | Strong | Acceptable | Generic | Repeat | Off target | Average score | Question, median |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `b502e29` | 4 | 14 | 14 | 2 | 1 | 2.5 | 2.4 s |
| First change (expert follow-up test) | 9 | 13 | 9 | 2 | 2 | 2.8 | 2.4 s |
| As committed | 7 | 17 | 8 | 2 | 1 | 3.0 | 3.1 s |

The generic questions of the first run were the opener, “what happens next” questions, and stock topic questions (“Which role is accountable for the overall result?”), several of them produced by the rule added in round two that pointed every third question at an open topic. What changed: the question model tests its own question last (specific to the latest answer, not already answered, never a stock question); a question that only asks what comes next is put back to it once (ten of 233 earlier questions had that form); the open-topic rule starts at the eighth answer, runs every fourth question, offers up to four topics and requires the question to contain a specific from the account; skipped questions are named in the instructions; and a rule the participant says does not exist is recorded as a gap. Three of the eight generic questions left are the opener, which the graders marked generic in any wording. The typed interviewer is better and still not uniformly expert: about one question in four is a plain follow-up that strings the participant's words back.

**Live voice.** `gpt-live-1` was run in the built-in browser on an isolated copy with `getUserMedia` replaced by a WebAudio stream of synthesized speech, so the page, WebRTC, the live model and its captions were the real ones. On `b502e29` it answered within a couple of seconds and stayed on the thread, but greeted with “What work would you like to walk through together?” although the name was typed, followed the last thing said (“who do you call at the bank?”) past a manual workaround and a rule nobody enforces, and its “Okay.” and “Sure,” became numbered questions. As committed, with a compact form of the same test at the end of its instructions: the greeting names the work, and in three sessions every follow-up (thirteen) was specific; it picked up the excuse rights handled in a spreadsheet, a late email from legal, default interest that is never charged, a tracker kept on one desktop and a matching rule nobody wrote down. Replies were complete within the nine seconds allowed after each spoken answer in every turn; the latency itself was not measured more finely than that.

**Bug pass.** A spoken interview was taken through Notes, Workflow, Wrap up, Create draft (ready 115 s after the click, eight steps) and Review; typed and file interviews through the harness; the example in the browser. Found and fixed: the draft's head start never fired after a spoken interview (it waited for a map that takes a minute or more to catch up), and “[inhale]” appeared in a caption. Noted, not changed: after Stop talking, Wrap up stays disabled for about twenty seconds while the notes catch up.

Test suites as committed: Python 128 of 133 files and Node 96 of 96.

## What remains

A complete capture was still not reached. One participant answered 45 questions in full and never said “I don't know”: 13 of 16 topics were complete, with a start node, an end node and one connected map of 40 steps, but the interviewer had not asked about the three topics left open (see item 9 above for the change this led to). The completion review that follows a complete capture has therefore still not been seen with the AI service.

1. **Create draft is still a wait of one to four minutes** when the head start has not finished or is switched off, because the draft itself is 6,000 to 27,000 tokens of writing at about 88 a second. The head start hides most of it; it does not remove it.
2. **The notes are long by design.** Each of the sixteen topics is written to be read on its own, so a fact that bears on three topics appears under each. This was left as it is.
3. **A map shows only what was reported.** A participant who never says how two parts connect gets two parts and a question, not a guessed arrow.
4. **Live voice with a microphone was not tested by this run.** Its server routes were (11 of 11 map updates succeeded); the microphone, speaker and WebRTC connection need the device check in the [demonstration guide](../../../DEMO_GUIDE.md).
5. **A model can still mishear a word it has never met.** Hints help with terms that recur; the first mention relies on the participant checking the text.

## Backend design notes

- **Allowances are fixed numbers while the work grows with the interview.** The draft's generation timeout was made to follow the account earlier; its audit timeout, the question reply's allowance, the draft's output ceiling and the compatibility map route's allowance had the same fault and now follow the input or have a second attempt. Every place a participant waits on a model should have an allowance that follows the input, one retry and a deterministic fallback.
- **An allowance includes the model's reasoning.** Two failures were replies whose whole allowance went on reasoning before a word was written (a question at 600 tokens, a map at 12,000).
- **Two maps are generated and checked separately.** The working map is drawn and source-checked during the interview; the draft then writes a map of its own and checks that. They are now aligned by instruction, and the draft's check returns corrections only. Having the draft take the checked working map as given, and write only what the map does not hold, would shorten the draft's first half as the check was shortened.
- **A draft is three requests in a row**: the draft, its source check, and a topic review when any topic is complete. The first can now start at Wrap up and the third runs as four groups at once; the second is the wait that is left.
- **The page owns the interview.** Transcript, notes, map and draft live in the page; the server keeps only the conversation's background work in memory. A server restart was survived mid-interview. A page reload is not, unless the recovery copy is on, and it is off by default.
- **Readers of the open-question register depend on its order.** The question model takes twelve entries and the owner brief the first five, so where generated questions are placed decides what the interviewer and the owner see. The map's leads also pull the interviewer towards the branch in hand, which is why a turn that must change subject is given none of them.
- **A control whose state depends on the page must be refreshed by the page.** Add files was redrawn only with its own list (fix 1). `updateControls()` is where such state belongs.
- **A field name can carry a rule.** The wire schema caps anything named `remove_steps` at zero items until a participant has spoken. A new reply shape that reuses a name inherits its rule.
- **One server carried five interviews** on the default six provider slots; Wrap up then waited 50 to 90 s for the latest notes and map.

## Files

| File | Contents |
| --- | --- |
| `cases/` | One JSON per case: context, transcript, every timed event, final notes, map and draft. Session tokens are removed. The sixteen cases of round two have `"build": "round2"`. |
| `timings.json` | Per-case question, notes, map, Wrap up, draft, file and transcription timings, map shape and failures. |
| `fixes.patch` | The nine fixes of the first round and their tests, against `dde4da1`. The second round is the commit that added this section. |

Run a scripted case with the [harness](../../harness/README.md): `scripted.py CASE PORT FA-17 narrate --per 2 --max 5`.
