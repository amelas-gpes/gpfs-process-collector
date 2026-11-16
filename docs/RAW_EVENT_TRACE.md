# Reading Process Collector’s raw event trace

Event files live in the active workspace’s `work/raw-trace` directory. The server writes observations as the interview runs, including work that finishes after a participant leaves. A developer can read the JSONL directly. Each line is one observation from its named producer.

## View logs in Settings

Open **More options → Settings → Application logs**. The viewer loads up to 100 recent entries across saved sessions; choose **Current session** to limit it to this server run. Use **Refresh** to read new entries and **Search loaded entries** to filter the loaded window. Expand an entry for its timestamp, event, correlation identifiers and recorded details. Logging status, storage interruptions and shortened previews are shown here. Reading logs does not change the files or switch logging modes.

The reader scans at most eight recent files and 8 MiB per request, limits its response to 1 MiB, and shortens individual previews above 32 KiB. Full records remain in the JSONL files. An unfinished final line is skipped until it is complete. Requests require the app's same-origin and current request-token checks. Logs and private settings stay outside Git.

## Open the live server’s file

From the canonical checkout, run the following in PowerShell. The filter uses the listener’s run ID so the launcher’s separate file does not get selected. A desktop installation uses its own work folder.

```powershell
$traceRun = (Invoke-RestMethod http://127.0.0.1:8774/api/config).raw_trace.app_run_id
$traceFile = Get-ChildItem -LiteralPath .\work\raw-trace -Filter "*$traceRun*.jsonl" |
    Sort-Object LastWriteTimeUtc | Select-Object -Last 1
Get-Content -LiteralPath $traceFile.FullName -Tail 20 -Wait
```

The server reads the mode at launch. `RAW_TRACE_MODE` in the local environment or `.env.local` takes precedence over a single ASCII value in `work/raw-trace-mode.txt`. The values are `content`, `metadata` and `off`. A fresh checkout defaults to metadata. Content mode retains permitted text verbatim. Logging information is in Settings; there is no welcome-screen logging banner. Choose content mode for interviews authorized for local capture. No upload, AI evaluation or training job is part of recording.

## Row format

- `schema_version`, `type`, `event_id`, `producer` and `payload` identify what was observed and by whom. `mode` records the content setting at the time. An omitted payload value may carry a structured `_trace` marker or an explicit omission field.
- `app_run_id` identifies the writing process/run. `sequence` gives its enqueue order. `observed_at` records the observation time. `recorded_at` is the server-side receipt/enqueue time. Clock values from different producers can disagree.
- Browser rows also carry the originating tab’s `producer_id` and `source_sequence`. Repeated deliveries keep that pair and get separate receipt records. Related HTTP operations use `operation_id`; server records can carry `tab_id`, `interview_id`, `turn_id`, revision, request ID or parent operation as available. Provider request IDs can also be inside the payload. IDs supplied by a browser identify its claim and grant no access.
- A model response, guard result, returned answer, DOM render and playback callback each have their own row. A guard reason is the value issued by application code. A provider's response is attributed to that provider. Neither becomes a conclusion about participant intent.

## Coverage

| Observation point | Recorded boundaries |
| --- | --- |
| Launcher, desktop bridge and HTTP server | Launch options, probe and child results, ready/close signals, server bind/close, asset writes, request dispatch, parsed request fields, response writes and observed failures. |
| Browser interface | App control events, notices, workspace and mode changes, tab visibility, committed turns and amendments, DOM insertion, application of notes/maps/drafts, and observed download/write/restore events. Input events identify the control without copying an unsent editor value. |
| Voice and transcription | Browser media/controller events, caption changes, approved speech, playback callbacks, mute/stop and interruptions. The server records sending audio and receiving transcription results at the applicable boundary. Committed text is recorded in content mode. |
| Model and interview routing | Structured request preparation, actual dispatch and received results at the transport adapter, stream boundaries, validation outcomes, candidate wording, guard decisions, fast/coordinator branches and authorized output. Fixed prompts and ordered permitted inputs accompany dispatched requests in content mode. |
| Concurrent notes, capture, maps and specialists | Queue, worker start, replacement/discard, completion/error, publication, and application in the browser, with the relevant revision or generation. |
| Files, filing and recovery | Upload receipt, reference selection, review scheduling/attempts, retries, metadata writes, archive changes, submission routes, matching job status, recovery and save/load outcomes. Original files, intermediate recorders and private restore payloads retain their own storage rules. |

## Observation limits

Raw audio, video, file originals, private reasoning, access-bearing credentials and unsent dictation/composer content are excluded. Where a document or media boundary suppresses a value, the trace retains available references, lengths or state changes. An interrupted provider stream can retain event types and offsets without a final safe text buffer. A DOM insertion establishes that the app rendered a node; playback-started establishes the browser callback. Direct WebRTC transport, provider internals, physical audibility and actions outside the app may be unobservable.

Each producer starts recording when its instrumentation loads. Events before browser configuration can carry a `configuration_pending` omission. Startup failures before the server opens its trace may leave only launcher or desktop diagnostics. Previously saved interviews contribute the observations made when they are reopened. Earlier interactions are not reconstructed.

The browser batches events and attempts a last flush on page hide. A crash can lose its pending tail. The writer bounds its queue and starts another JSONL segment at 512 MiB. The run ID and sequence continue across segments. Repeat the live-file command when the writer moves to the next file. The writer samples free disk space and reserves 64 MiB for the app. During a space pause, the `raw_trace` status in `/api/config` reports the reason and number of omitted records. When space returns, the next successful record carries `storage_gap_before`. Source sequences, omission markers and a `trace.loss` record on orderly close when writable also expose detectable gaps. A hard process kill can leave a partial final line. Treat the last complete observation as the end of the available evidence. There is no automatic expiry of finished run files. Remove a run’s files only after its writer stops.

## Reproduce the synthetic browser trace

With the project's existing `VOICE_INTERVIEWER_PYTHON`, `COLLECTOR_PLAYWRIGHT` and `COLLECTOR_BROWSER` paths, run `node tests/browser/raw-trace.cjs`. The exercise opens two tabs against a synthetic loopback provider, submits text with deliberate whitespace, correlates the browser and server records, checks a credential and an unsent string stay excluded, and prints the output path under `work/raw-trace-validation`. The Python `test_raw*.py` and Node raw-browser suites cover the writer, guards, streams, retry, restore, voice callbacks and stale work through their respective fixtures.
