# Conversation repair — 0.26.1

Implemented in the canonical checkout on November 5, 2026. This review supersedes
the conversational acceptance conclusions of the 0.26.0 review. Evidence is local
under `work/conversation-repair/`; provider rehearsals use fictional facts.

Automated QA and agent-led acceptance rehearsals are complete. The canonical local
app is running 0.26.1 at `http://127.0.0.1:8774/`; its build ID matches the final
source (`b9f9c1171ec9f4cffbd1c7194d37090a3e224dc6b7c0c9ceb2862294ae6c1ac3`).
Human microphone/speaker and participant acceptance remain pending.

## Observed failure and repair

The supplied Capital Calls transcript exposed repeated information requests,
abstract scope/rule questions, confusion between starting and finishing emails,
and an apparent abandoned-word prompt after the person had completed an answer.

Local replay identified three interacting causes:

- An interviewer listening cue finalized the participant caption. Continued speech
  could become a separate answer even though the person was still explaining it.
- A background request could analyze a short prefix, then publish against the
  mutated answer and mark its full text captured. This suppressed needed catch-up.
- Background notes supplied first-person next-question instructions alongside the
  live model's own question selection. Rigid opening phases compounded the effect.

Participant and interviewer caption streams now remain independent. Listening
cues and pauses preserve the participant's answer; an actual question or information request
separates the next answer. Microphone activity holds quiet caption checkpoints.
Punctuation-only deltas remain attached to their source.

Capture requests retain detached source snapshots. A response must still match
the exact participant text, generation, live instance, context and document revision
before it changes notes, progress or completion. A stale response schedules catch-up.
Already-sent completion reviews have the same check. A late diagram-only response
cannot cancel a completion review of newer evidence.

The spoken model owns ordinary follow-ups. Background capture sends compact,
current progress labels only, at a quiet point. It supplies no next-question script.
No extra synchronous question-selection request was introduced.

## Conversational behavior

The sixteen topics remain the completeness guide. They no longer dictate opening
question order. The interviewer invites the named work's walkthrough, learns scope
and dependencies in context, and asks one concrete information request at a time.
It uses volunteered facts across topics, briefly acknowledges corrections, keeps
starting and finishing events distinct, and records mentioned materials as existing
but unreviewed. It parks an unknown rather than immediately asking how to find it
or who could resolve it. Useful recaps replace mandatory scope ceremonies.

Independent evidence/coverage review, explicit applicability, correction and source
authorization, final confirmation and owner-review distinctions remain required.
Unknown does not become N/A or completed coverage.

## Automated QA

- **654 Python tests pass**: `python-release.txt`.
- **22 JavaScript suites pass**: `javascript-qa.json` and `javascript-release.txt`.
- The new conversation regression suite exercises cue/fragment accumulation,
  microphone activity, immutable capture/catch-up, context/document/session changes,
  stale completion reviews, late diagram results and quiet progress-only updates.
- Real Chrome checks preserve sixteen topics, eleven example steps and metadata
  through save/reopen. Reopened confirmation is false. Desktop 1440 × 1000 and
  mobile 390 × 844 have no page errors or horizontal page overflow. The report
  screenshots were visually inspected. See `browser-qa.json` and the PNGs.

An initial browser automation attempt timed out waiting for the example report;
the diagnostic replay and complete repeated browser rehearsal passed. The failed
attempt remains in `browser-qa.txt`; it is not counted as a successful check.

## Provider rehearsal

Eight fictional question-selection cases use the actual wired typed policy:
named and broad work, an unknown payment date, a repeated completion question,
mentioned documentation, enterprise HR/IT, already-supplied scope and a described
calculation. The returned questions used the known account, avoided abstract
entity/rule gates and did not immediately re-ask the unknown date. The named-work
case invited a walkthrough; broad work was narrowed once. See `question-uat.json`.

Two sustained synthetic-microphone GPT-Live/WebRTC rehearsals completed ten
participant answers each. Six answers included an inserted 1.1-second pause.
The correction run retained the start/finish email distinction and documentation-site
statement, without the abandoned-word prompt. The first natural run did rephrase
an unknown payment-date question once; the shared unknown-parking instruction was
tightened and the typed case rechecked. See `natural-live.json`,
`corrections-live.json` and `voice-uat.txt`.

A third sustained rehearsal completed twelve more participant answers, including
an actual interruption during interviewer audio. Its saved interview retained
sixteen topic records and the reported approvals, receipt checks, start/finish
distinction and unreviewed materials; it did not claim participant completion.
See `refined-live.json`, `refined-session.json` and `refined-voice-uat.txt`.

This run exposed further known-role/sequence repetition, an acknowledgement with
no next question, and answer splits after "Go ahead", "Got it, thanks" and "Good
to know". The final policy explicitly reuses overview facts, stays in the interviewer
role and follows a finished substantive answer with one useful missing detail.
The caption boundary now requires a question or information request. Replaying
all three sustained recordings through the final caption controller preserved
every participant word and kept the documentation/attachment qualification in one
answer. The third recording's fifteen fragmented user captions became ten logical
answers; physical interruptions and continued explanations can share one answer.
See `caption-replay.json`. These are chronological checkpoints, not a claim that
all thirty-two answers were generated under the final prompt.

Three final-build GPT-Live/WebRTC sessions then seeded the exact overview,
unknown-date and materials cases. The questions respectively asked about the
unreported payment-date basis, the workbook's unexplained construction, and the
payment date. They did not re-ask the named reviewer, restart the supplied route,
re-ask the unknown date in its own case, demand an attachment or reverse roles.
No provider/controller errors were recorded. See `seeded-voice-uat.txt` and
`seed_*-live.json`. Initial harness attempts, including a truncated opening audio
and waits that incorrectly required a literal question mark, remain retained.

A fresh full fictional source replay produced sixteen-topic capture and a
validated nine-step draft, with no API/schema errors. It retained the upstream
calculation, structural GP contribution difference, separate approval roles,
Treasury input, manual cash entry and parallel feeder lead. It kept unknown
thresholds, manager review objective, handoff mechanisms and unreviewed documents
as gaps, without certifying a GPFS standard. See `artifact-uat.json`.

## Runtime and acceptance boundary

Reused the installed Python 3.12.14, Node 24.22.1, Playwright 1.62.1, Chrome
156.0.8078.80 and Windows System.Speech/Microsoft David Desktop. No package,
browser, model, runtime or voice download was required. Audio fixtures were made
offline and injected through a synthetic microphone; physical output was muted.
The fresh resource preflight and functional receipt are in `.utility-reuse/` and
`runtime-reuse.json`.

These are agent-led acceptance rehearsals, not participant or owner sign-off.
Physical microphone/speaker quality, accents, room noise and interruption feel
still require a human check. Successful bounded trials do not guarantee every
model response or startup. Existing private settings and saved work were preserved.
