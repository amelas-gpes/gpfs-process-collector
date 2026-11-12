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
and workflow are separate background products; only matching current revisions
can be published. An append-only answer with compatible sources starts from the last accepted fact ledger and map. Edits to earlier testimony or changes of scope require a fresh baseline. Global worker limits keep this separate from the foreground
HTTP slots needed for transcription, questions and voice credentials.

The fast interviewer reads the conversation and chooses one neutral next
question. It does not wait for notes or workflow. Background capture may propose
a question internally, but that question is never added to the transcript or
played. Background coverage is provisional and cannot set readiness or completion.
The Notes panel reports working, caught-up, synchronization and failure states.

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
  transcript and waits for the current notes and workflow. Failed workflow work
  receives at most one retry per explicit wrap-up attempt. A question appended after capture is included before a review ticket
  is issued. Existing independent review, final omissions and confirmation gates
  remain authoritative. Opaque capture tokens are validated by Coordinator.
- A failed background operation preserves the conversation and prior displayed
  notes. Wrap up explicitly retries failed capture once; there is no automatic
  paid retry loop. Workflow failure is advisory and does not authorize completion.

Existing draft generation reads the complete current transcript and performs its
own evidence/coverage audits. A draft remains a review artifact, not a declaration
that the interview is complete. File intake retains its explicit review-and-baseline
phase before a documentary follow-up; this change does not bypass that boundary.

## Operational limits

Sessions and queues live in memory, expire when idle, and are bounded. Restarting
the app clears them; an exported/restored interview starts a new background session.
Original documents and saved interviews keep their existing local storage rules.
Provider calls already in flight can finish after cancellation; their obsolete
results are withheld. Background processing adds provider work and cost, and long
transcripts remain in the fast model input for conversational accuracy. No constant
latency or cost reduction is promised. The 1.8-second reviewed-voice silence threshold and
buffered natural voice playback remain unchanged.

## Historical validation (0.23.0)

Focused suites cover nonblocking questions, latest-snapshot coalescing, stale
publication, source mutation, media capacity, typed and voice routing, delayed
maps, final review/confirmation, reset, failure and restore. They use fake
providers and media boundaries. Live synthetic-provider timing and any rendered
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
