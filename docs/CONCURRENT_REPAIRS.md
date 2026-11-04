# Concurrent interview repairs — 0.23.1

The first participant test exposed gaps beyond the initial concurrency tests:
automatic titles were skipped, discussed-topic progress was confused with complete
coverage, and a transcription failure erased the useful error detail and stopped
voice without retaining its recording. These are application defects; a provider
HTTP 200 record alone is not evidence that speech was recognized.

## Naming

The background and synchronized workflow paths apply a derived display title.
`state.context` remains the participant's source context. Automatic naming cannot
invalidate question, background or recording-retry source signatures. Header,
exports and filenames use the displayed name; saved interviews keep the derived
name separately. Explicit participant edits override automatic naming.

## Discussion and analysis freshness

Source-backed `topic_discussion` metadata is separate from strict captured/N/A
assessment and completion authority. The panel reports discussed and fully captured
counts separately. Partial topics say “Discussed · needs detail”; an unknown
topic says no detail has been captured rather than claiming it was never explored.
The panel identifies the last answer in displayed notes and indicates pending or
revised answers. A first activity alone still does not establish an initiating
event, cadence or deadline. A conditional equipment/input route can support both
lifecycle and variations without making either topic complete.

## Transcription recovery

No-speech responses warn and resume listening without automatically resubmitting
the audio. Other failures give category-specific guidance. At most the latest
failed recording is retained in memory (12 MiB, 10 minutes). “Retry recording” is
an explicit action; retry checks the source context, turns and document revision,
and accepted text is inserted once. Later accepted speech, page exit, reset,
file intake or disposal clears retained audio. Recordings are not added to saved
interviews or logs. The earlier failed recording cannot be recovered retroactively.

Server diagnostics distinguish accepted speech from rejected/empty transcription
results using fixed categories only. They contain no transcript, provider response
text, recording or credential data. Diagnostics cannot make a valid request fail.

## Validation boundary

Local regressions cover immutable automatic titles during in-flight questions,
save/export naming, evidence-backed discussion, unchanged strict completion,
overlapping conditional-route topics, lag markers, empty transcription, explicit
retry, expiry/size bounds, source changes and duplicate prevention. Full existing
Python and JavaScript suites are rerun. These use simulated providers/media and
do not certify physical microphone recognition quality.

The supplied transcript was read locally as evidence. Automatic approval review
rejected external replay of that private payload; no replay request was sent.
