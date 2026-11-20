# Concurrent interview

Routine typed and voice answers now have an independent next-question path. The
foreground model returns only a short question or a request to enter final review.
It cannot return captured facts, completion, final confirmation or a draft.
Recorded voice still transcribes an answer before asking the next question;
playback retains the existing exact-text authorization gate. This is turn-based
audio with concurrent analysis, not full-duplex streaming or spoken barge-in.

## Work that happens alongside the conversation

`ConcurrentInterview` owns opaque, in-memory conversation capabilities. Each substantive answer queues a full source snapshot for background capture through the
existing authoritative Coordinator. Each session keeps at most the current work
and one latest pending snapshot. Pending intermediate versions coalesce. Notes
and workflow are separate background products. Notes of an earlier answer are
offered as a checkpoint; a map of an earlier answer is offered as the map through
that answer (see below). Global worker limits keep this separate from the foreground
HTTP slots needed for transcription, questions and voice credentials.

Background notes and maps continue from what the conversation last published;
they are not rebuilt from nothing on every answer. Each background capture is
given the capability of the session's own last capture, never one the browser
sent, marked for the Coordinator as ledger-only. The lead then receives the
private fact ledger and returns changes to it, so a fact that a later answer does
not restate stays in the notes, and an ordinary answer runs on the lead model.
The marker removes every other use of that capability: background work cannot
confirm a final check, replay a stored capture or hold a review. It joins the
capture family of the ledger it continues, so a review prepared before a newer
answer fails closed, as it does when the newer answer arrives with the browser's
own capability. Each background map is given the five baseline fields of the
session's map as it stands (map, memo, summary, focus and parked items) while
the transcript that map was drawn from is still the beginning of the current
one: untouched steps keep their IDs, titles and owners, and checked routes are
not reviewed again. The rebuild that Wrap up makes after a fast question
continues the same ledger. When Wrap up carries a capability the browser holds
(from a file follow-up, an earlier Wrap up or a review), that capability keeps
its full meaning for what may be confirmed or reviewed; the server names its
session's own last capture beside it, and the Coordinator continues the more
recently published ledger of the two, so an older capture in the browser does
not replace the conversation's latest notes.

Continuity never becomes a new way to fail. An edited earlier answer, a
capability that expired after thirty idle minutes or a restart start again from
the transcript. A baseline map that no longer validates against the request's
sources (a replaced file) is dropped and the map is drawn from the empty
baseline. When the application refuses what a model returned for the continued
ledger or map (a topic at the ledger's size bound, a removal of a step the map
does not hold, a revision that leaves an accepted handoff unverified), that
attempt fails as before and the next attempt starts from the transcript or the
empty baseline, as every attempt did before this continuity existed; the
published notes and map stay on screen meanwhile. A provider failure leaves the ledger and the baseline
in use. With reference files, the document selection of a new answer first
reads what the session's ledger and map cite, whether or not the browser has
applied those results yet.

## The map: drawn at once, checked beside it

The November 17 stress run found the diagram missing at the end of 14 of 27
interviews and present before the next answer for 7 of 139 answers. Four causes
were in this module and its callers, and each is changed:

- **A new answer does not cancel the map being drawn.** It used to (65 times in
  that run, with a participant answering every 45 seconds and a map that takes
  longer than that). The map being drawn is left to finish. When the account has
  only grown since (the same intake and files, its answers still the beginning of
  the conversation), the result is kept: the status reply offers it as
  `workflow_checkpoint`, the map through the answer it read, and the next map
  starts from it. A map of wording that was edited since is discarded. Only the
  map still waiting to be drawn is replaced by a newer one.
- **The map is shown as drawn; its source check runs beside it.** Every map used
  to be a draw followed by its source audit in one job, and the audit took longer
  than the draw (112 s against 41 s at the median). The draw
  (`Coordinator.workflow_draw`) returns a map that has passed every check the
  application makes without a model: schema, limits, source IDs, the wording of
  operating details, removal quotations, structure questions. That map is the
  `workflow_capture` of its revision at once, with `workflow_checked: false`. The
  check (`Coordinator.workflow_check`) runs in a lane of its own. It starts when
  no map is waiting to be drawn, never stands between an answer and the map on
  screen, and reviews only what changed since the last checked map
  (`server.workflow_delta`): what was checked before is not sent through the
  review again. A step or route that left the map travels with the participant's
  quotation the draw already verified. When that difference cannot be written as
  an update, or applying it does not reproduce the drawn map, the whole map is
  checked against the empty baseline. The check corrects the map and does not
  rearrange it: what it keeps stays in the order it was drawn in.
- **What a draw took from a file the check can no longer read stays as drawn.**
  A file excerpt that was read when a step or route was drawn may be out of reach
  when the check runs: the file was saved for later or removed, or the excerpt is
  outside what one request can carry. Such an excerpt may keep what already
  cites it and may support nothing new, and for a check "already" is the map as
  drawn, not the map as last checked: the check establishes nothing. Those steps
  and routes join the map the reviewer starts from, with the steps their routes
  need, and are not reviewed (`server.keep_unread_as_drawn`); the rest of the
  difference is. The diagnostics event `coordinator.workflow.check` counts them
  as `held_as_drawn`. Before this rule the check of such a map was refused
  before any request was sent, after every further answer.
- **A check that finishes after later draws is carried under them.** The later
  draws are applied to the checked map (`Coordinator.workflow_rebase`, no model):
  the check's corrections stay, a route it refused stays off, and the later
  answers stay. A later edit of a component wins over the check's version of it
  and is reviewed by the next check. That holds for a step the check took off
  the map as well: when a later answer stated it again it returns with its
  routes, and the next check reviews all of them. A step the check took off and
  no later answer touched stays off, and a later route to it is left out. When
  the later draws cannot be applied the result is left out, the map stays as
  drawn and its next check covers the same ground.
- **A check that fails leaves the map in place.** The status reply then carries
  `workflow_check_state: "error"` and `workflow_check_error` beside the unchanged
  `workflow_capture`. The check is not started again for the same map by itself;
  the next draw brings a new check, and Wrap up asks for one more. A check the
  application refused (a restated step that leaves an accepted handoff
  unverified, an omitted decision) is followed by a check of the whole map.
- **Work is taken one job at a time, the oldest first.** Notes, draws and checks
  each have their own workers. An interview has at most one job waiting in each;
  when it is done the interview queues its next one behind the others. One map
  worker used to serve the whole server and stayed with one interview for as long
  as it had work. `COLLECTOR_MAP_WORKERS` (default 2, 1 to 8) maps are drawn at
  once; checks use one worker fewer, at least one. `COLLECTOR_NOTES_WORKERS` (default 2, 1 to 8)
  notes are written at once; on a server shared by several people raise it, since
  with six interviews answering every 20 seconds two workers never caught up.

At Wrap up (action `close`) a map that was built answer by answer is compared
once with a map drawn from the whole account, because an incrementally updated
map came out thinner in one measured case (16 to 20 of 28 stated steps). The map
of the whole account takes its place only when it carries clearly more: it cites
an answer the other never cites, or has more than about a seventh more steps.
Otherwise the map on screen stays, with the checks it has passed. The map that
is kept is checked like any other; one that replaced another is checked whole.
Until that second look is done the status reply does not call the map checked
(`workflow_checked: false`, `workflow_check_state: "working"`), so the page keeps
asking and receives the fuller map if there is one.
The threshold is a judgement that has not been measured against the real
provider.

The map in a status reply carries the record of the models that made it
(`generated_by`, `app_version`), as a map from one request does: the latest
draw and the latest check, one row for each stage. The page files that record
with a saved interview and an export.

The background draw is given every rule of the map
(`server.WORKFLOW_MAP_INSTRUCTIONS`): the routing, component and step-detail
policies and the source check, without the memo rules, since it returns no memo.
From 0.30.0 it was given the full instructions cut at their memo paragraph, which
cut those policies as well; the source audit was then the first model to read
them and rewrote most steps of every map it checked.

The fast interviewer reads the conversation and chooses one neutral next
question. It does not wait for notes or workflow. Background capture may propose
a question internally, but that question is never added to the transcript or
played. Background coverage is provisional and cannot set readiness or completion.
The Notes panel reports working, caught-up, synchronization and failure states.

A fast reply is asked as written when it asks for something: one question, or a
short spoken request such as "Talk me through ..." as its last sentence, optionally
after a brief answer. Process vocabulary ("round up", "wrap up the month-end close",
"anything else you attach") is not closing language, and a brief answer may use the
same words about the work ("I have what I need on the trigger.", "Feel free to
estimate.", "You can review the draft notice in the portal."). A reply is not spoken,
and never fails the turn, when it closes or offers to close the whole interview in
the recognised wordings, when a statement in it says that the interview, its record
or the participant is finished, or points to the draft ("Consider this interview
complete", "We're done", "I'll draft it now", "Go ahead and create the draft"), when
a question in it asks whether the interview is complete or what was left out ("So
we're done?", "Is there anything we have not covered?"), when its only request hands
the next move back ("Tell me when you are ready"), when anything but a short
courtesy ("Take your time.") follows its last question, or when it asks nothing.

The typed path and the agent team's Coordinator share this one check
(`server.question_rejection`); the team path differs only in keeping one question
per turn. Its rules are constructions, not phrases. A completion wording is a claim
about the interview when it is the main clause of a statement and nothing ties it
to the work. It is asked as written when it is tied to an event in the work ("So
this call is closed once the funds arrive."), has the work as its object ("You are
finished with the first pass."), restates the answer after "So", "Right," or
"Understood," ("So the draft is ready. Describe who reviews it."), or is asked about
rather than asserted ("Do you check that the documentation is complete before
release?", "Describe how you know you are done."). The interviewer's own claims
("we're done", "I have everything I need") and the interview's own names ("your
account", "this interview") are never read as the work, and a question that offers
the next step ("Shall I draft it?", "Would you like to review it?") removes the
benefit of the doubt from the statement before it. "Tell me when you normally send
the notice." asks about the work; "Tell me when you would like to continue." does
not. Doubtful wordings are replaced: a replaced question costs one turn of quality,
a spoken closing tells the participant the interview is over. A closing remark in
other words that comes before the question or request is still spoken.

The participant then gets a follow-up question from the same single
provider call: a topic question when the stored capture already reflects every
answer and still has a section the participant can answer, otherwise a neutral
question that is never the one just asked. When that capture has nothing left to
ask and the reply was a closing, the turn returns `sync_required` exactly as it
does when the fast interviewer requests a review, so the coordinator decides.
These checks recognise English wording and are a guard on speech only; completion
is decided by the coordinator's own gate, never by them. The local diagnostics log
records `question_rejected` with a stage (`fast_question`, `team_question` or
`review_question`) and a reason code (`wrap_up_match`, `closing_statement` for a
statement or a request that closes or defers, `completion_speech` for a question
about completion or omissions, `no_question_mark`, `empty`, `too_long`, and on the
team path `several_questions`), never the wording. The team path keeps one question
per turn: a lead or reviewer reply with two question marks is replaced.

## Stop, retry and mode changes

A stop returns a partial pause. The transcript keeps the participant’s original words. If the same turn supplied a process fact before the stop, capture receives that prefix under the original turn ID. Otherwise only already-pending substantive notes and map work may finish. The browser retains the accepted memo while polling for that checkpoint.

The browser gives each logical turn or wrap-up a stable operation ID. Retrying a lost reply reuses that ID, including before the server returns the first session token. An intentional new action gets its own ID. Starting a new interview cancels the old session’s work and review authority. Switching between typing and live voice in the same interview preserves a valid pending review against the same evidence.

## Source and completion boundaries

- A source revision binds context, participant account, scope and server-retrieved
  document material. A trailing fast question does not change participant evidence.
- Polling pins the original retrieval query and citation preferences. Authorized
  files are still re-read and checked for changes; cached retrieval does not confer
  file access. Client-provided document excerpts are stripped at the HTTP boundary.
- New answers, corrections, context changes, resets or file changes prevent late
  observations from replacing current state. Old results do not append speech.
- Wrap up, or an interviewer request for review, synchronizes the actual complete
  transcript and waits for the current notes. The workflow is a separate product with
  its own status: Wrap up returns it when it is drawn or arrives within two seconds,
  and otherwise releases the notes with `workflow_state` (`queued`, `working` or
  `error`), `workflow_pending` and, for a failure, `workflow_error`. A map that is
  returned says whether it was checked (`workflow_checked`, and
  `workflow_check_state` while it was not). The page then
  polls the status of that revision and applies the map alone when it arrives or
  changes; a failed map, or one whose check did not finish, is shown in Workflow
  with **Update workflow**, while Notes says the notes are caught up. An explicit Wrap up still queues a map the revision lacks and
  one retry of a map that failed; neither is waited for, and a failed or queued map
  never fails Wrap up. A question appended after capture is included before a review ticket
  is issued. Existing independent review, final omissions and confirmation gates
  remain authoritative. Opaque capture tokens are validated by Coordinator.
- A failed background operation preserves the conversation and prior displayed
  notes. Wrap up explicitly retries failed capture once; there is no automatic
  paid retry loop. Workflow failure is advisory and does not authorize completion.
- A request to stop or pause is answered once and is never a capture. Coordinator's
  pause reply carries no notes, so the background worker settles that revision
  without replacing the session's capture, the status poll reports
  `capture_preserved` with no `capture`, and the browser keeps its notes, summary,
  coverage and classifications. The Notes panel then says through which answer the
  notes go instead of claiming every saved answer. An explicit Wrap up after the
  request captures the whole account rather than repeating the pause reply; the
  status poll then publishes that capture and no longer reports
  `capture_preserved`. Skip after the request asks the next question without a
  capture: the trailing pause reply adds no participant evidence, so the revision
  stays settled and the answer that follows is analysed as usual. An answer whose
  analysis was still running when the stop arrived is finished and paid for but
  not applied (the newest snapshot wins); Wrap up or the analysis of the next
  answer covers it.
- After the final check and after the completion line every reply goes to
  Coordinator with the capture token (`sync_required`), which answers a reply that
  adds nothing without a provider call and without a map (see AGENT_TEAM.md). A
  request to stop in reply to the final check gets the pause reply here and the
  review stays in place: Wrap up afterwards asks the same final check again. After
  the completion line a request to stop is a goodbye; it is not answered with the
  pause reply and the completed account is kept.

Existing draft generation reads the complete current transcript and performs its
own evidence/coverage audits. A draft remains a review artifact, not a declaration
that the interview is complete. File intake waits for the review of its files and then
asks the question those files raise through this same fast path (action
`document_followup`): the notes and the audited map of that revision are background work
like any other, and a file-only start is mapped as well. The question never requests a
review and never fails on the model's reply (see DOCUMENT_INTERVIEWS.md).

## Operational limits

Sessions and queues live in memory, expire when idle, and are bounded. Restarting
the app clears them; an exported/restored interview starts a new background session.
Original documents and saved interviews keep their existing local storage rules.
A cancelled request to the AI service is ended at once (its connection is shut,
wherever it waits), which frees its worker and its provider slot; whether the
provider stops generating and billing for it is the provider's matter. Only a
conversation that is discarded cancels its work; a new answer does not.
`COLLECTOR_PROVIDER_SLOTS` (default 24, 2 to 32) requests are in flight at once; a file's in-depth review sends up to 16 of its batches together.
Background work leaves two of them free, so that a question, a transcription or
a voice session does not queue behind notes and maps. Background processing adds provider work and cost, and long
transcripts remain in the fast model input for conversational accuracy. No constant
latency or cost reduction is promised. The 1.8-second reviewed-voice silence threshold and
buffered natural voice playback remain unchanged.

## Historical validation (0.23.0)

Focused suites cover nonblocking questions, latest-snapshot coalescing, stale
publication, source mutation, media capacity, typed and voice routing, delayed
maps, final review/confirmation, reset, failure and restore. They use fake
providers and media boundaries. `tests/test_map_lanes.py` plays the pacing of the
November 17 run at one five-hundredth of its durations with a stand-in coordinator
whose draw and check take as long as a test says; `tests/test_map_check_delta.py`
drives the real Coordinator and replays thirteen maps saved from that run through
the difference and carry-forward rules; `tests/test_provider_cancellation.py`
holds a loopback provider's answer back to show a cancelled request return within
a second. None of these measure a real provider. Live synthetic-provider timing and any rendered
browser checks are recorded separately in `work/`; synthetic audio is not a
physical microphone or subjective voice-quality test.

The full Python suite passed 601 tests after the concurrent synchronization
changes. The frontend suites include 13 concurrent-controller cases and six
actual-app integration cases in addition to the retained voice, UI, document,
workflow and export regressions. In one paired real-provider fictional sample,
the previous combined call took 7.750 seconds and the independent next question
took 2.047 seconds; background notes and workflow completed in 16.781 seconds.
This measures text request timing, excludes audio capture and playback, and is
not a statistically reliable latency forecast. A separate rendered browser turn
also returned a question, accepted another reply and updated notes/workflow.
