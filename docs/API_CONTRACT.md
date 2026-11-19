# Local HTTP interface

The desktop window and browser use the same loopback HTTP service. GET `/api/config` returns capabilities, model aliases, build identity, available document types, local storage health and a per-server CSRF token. All POST routes require the current `X-CSRF-Token`, the matching localhost Host and a permitted Origin when present. State-changing requests require an explicit Content-Length. The anonymous `X-Interview-Id` header attributes provider usage.

The interview snapshot contains `context` and `turns`. A turn carries a unique ID, role and text. A capture token, conversation token, review ticket, file scope or submission-status receipt is opaque. Keep it with its own interview. The service resolves source text from the local store and validates citations. A browser-supplied source label cannot grant access.

An interview request can include `file_topic_reviews` with one decision per topic. Each entry contains `topic` and `decision` (`confirmed` or `needs_changes`). A confirmation requires the exact `answer` reviewed and adds it to participant context. A flag asks the interviewer to clarify the file notes when material. The interview still checks coverage and waits for its own final reply. Saved interviews keep both the reviewed `answer` and the original `source_ids` for each decision.

| Method and path | Caller, input and result |
| --- | --- |
| POST `/api/trace/events` | The browser sends its tab UUID and 1–64 observations, with source sequence, timestamp, type, payload and optional correlation IDs. The 256 KiB batch limit, same-origin and CSRF checks apply. A 200 receipt gives `received` and `accepted` counts. Accepted means enqueued by the local writer. Per-run counters in `/api/config` report writes and detectable loss. [Trace schema and data boundaries](RAW_EVENT_TRACE.md). |
| GET `/api/trace/logs` | Settings reads saved local events with `scope=all` for recent sessions or `scope=current` for this server run. Requires the current `X-CSRF-Token` and the same-origin checks. Returns up to 100 events, writer `status`, a `limited` flag and the count of shortened previews in `clipped`. Scans at most eight recent files and 8 MiB, with a 1 MiB response budget; previews above 32 KiB are shortened without changing saved files. Invalid scopes return 400, rejected tokens return 403 and unreadable logs return 503. [Reader limits](RAW_EVENT_TRACE.md). |
| GET `/api/admin/agent-prompts` | Settings reads the server's built-in instruction templates as `agents[]`. Each agent has an `id`, `label`, `description` and a list of prompts with `id`, `label`, `when` and `text`. The UI adds the live instructions issued by its browser voice controller. Requires a trusted `knowledge.admin` identity or an explicitly configured loopback owner, the current `X-CSRF-Token` and the same-origin checks. The server reports eligibility in `/api/config` as `agent_prompts_available` and rechecks access on each catalog request. |
| POST `/api/conversation/turn` | The interview sends a snapshot and action. A client can supply a random 64-character lowercase hex `conversation_start_id` on its first turn and retain it across retries until it receives the conversation token. Returns the immediate question or pause, a conversation token and capture progress. |
| POST `/api/conversation/cancel` | End the conversation identified by `conversation_token` and cancel its queued work. A same-interview mode switch sends `handoff: true` to retain a review issued for the same evidence. Repeated cancellation is safe. |
| POST `/api/conversation/discard` | Stop queued analysis using the conversation token and pause file review using the document scope. Repeating a successful request is safe. |
| POST `/api/conversation/status` | Poll the current conversation. Returns progress and available notes/map results for that revision. `workflow_state` and `workflow_pending` describe the map of this revision as drawn. When it is there, `workflow_capture` carries it (with `generated_by` and `app_version`, the latest draw and the latest check) with `workflow_checked` (whether it has passed its source check), `workflow_version` (changes whenever the map does) and, until it is checked, `workflow_check_state` (`working` or `error`) with `workflow_check_error` for a failure. Until it is there, `workflow_checkpoint` can carry the map through an earlier answer: `revision`, `through_turn_id`, `turns`, `workflow_capture`, `checked` and `version`. Apply it only while its turns are still the beginning of the conversation. |
| POST `/api/conversation/sync` | Reconcile the current conversation and its background work after new evidence or reconnection. Returns the synchronized notes with the map's own state; a map that is returned carries `workflow_checked`, `workflow_version` and, while unchecked, `workflow_check_state` as above. |
| POST `/api/agent-team/interview` | The capture worker submits a snapshot for the coordinated lead. Returns the evidence-linked memo and capture state. |
| POST `/api/agent-team/workflow` | Submit the snapshot and an optional accepted previous capture. Returns the updated map, open questions and source references. |
| POST `/api/agent-team/review` | Submit the issued review ticket and matching evidence. Returns the completion assessment, blockers and speech authorization. |
| POST `/api/agent-team/coverage` | Request provisional checks of captured topics in a current capture. Returns topic-level results and their answer bindings. |
| POST `/api/agent-team/status` | Look up the current agent run and its role progress. |
| POST `/api/agent-team/cancel` | Cancel the specified run. Obsolete results cannot replace the current capture. |
| POST `/api/interview` | Compatibility interview entry point. The built-in client uses the coordinator. |
| POST `/api/workflow` | Compatibility map entry point. Accepts the interview snapshot and optional previous capture. |
| POST `/api/draft` | Generate and independently check a draft against participant and document evidence. Returns the draft and available coverage or file evidence. |
| POST `/api/transcribe` | Send supported audio bytes with their media type. Returns transcription text. The body limit is 12 MiB. |
| POST `/api/voice-session` | Request a short-lived reader credential for the selected voice. |
| POST `/api/live-session` | Submit WebRTC SDP and interview snapshot for connected Live mode. Returns SDP and session metadata. |
| POST `/api/usage/check` | Settings clears the local quota latch and reads counts. The next provider call checks actual account availability. |
| POST `/api/documents/session` | Establish or reopen a private document scope for interview intake. |
| POST `/api/documents/upload` | Send raw file bytes with the file scope and encoded name in the request headers. Returns an accepted document and starts indexing. Maximum 64 MiB per file. |
| POST `/api/documents/status` | List the scope's current records, progress, limitations and available actions. |
| POST `/api/documents/action` | Apply a file-specific action using its scope, ID and current state. Returns the updated record. |
| POST `/api/documents/source` | Open the authorized, indexed source location belonging to a file in this scope. |
| POST `/api/documents/context` | Retrieve the bounded selection for an interview scope, query and optional preferred source IDs. Returns authorized excerpts, evidence catalog and reading limits. |
| POST `/api/recovery/status` | Read local recovery settings and availability without loading the transcript. |
| POST `/api/recovery/setting` | Set the boolean `enabled` preference for this local store. |
| POST `/api/recovery/save` | Replace the local recovery copy for the interview ID with its validated session. |
| POST `/api/recovery/load` | Retrieve the requested stored interview by its recovery ID. |
| POST `/api/recovery/discard` | Discard the copy identified by the current recovery ID. |
| POST `/api/knowledge/submit` | File a bounded snapshot as a new process or authorized revision. Returns HTTP 202 with the filed revision number and private status receipt. |
| POST `/api/knowledge/status` | Read the status associated with a valid submission, revision and receipt. |
| POST `/api/shutdown` | Local launcher requests orderly shutdown. The launcher verifies checkout and running process identity. |

Clients can send a 32-character lowercase hex `operation_id` to `/api/conversation/turn` and `/api/conversation/sync`. Reuse it when retrying the same snapshot and action after a lost response. Concurrent duplicates share one execution. Reusing the ID with a different action or transcript returns 409.

Successful operations normally return JSON with HTTP 200. Upload acceptance returns 202. Invalid shapes, stale state, unavailable services and oversized uploads return distinct errors. Common statuses include 400 for invalid inputs, 403 for rejected authorization, 404 for missing items, 409 for conflicting state, 413 for size, 415 for media type, 429 for local/provider limits and 503 for unavailable stores. Unexpected server failures return a correlation ID where available.

Local-owner mode or a trusted server-side authorizer controls revision access. A saved receipt permits a status lookup for its specific filed revision. The typed concurrent, document-analysis and agent-team flows depend on the built-in provider integration. A hosted adapter must implement and test the corresponding capabilities. [Data handling](DATA_HANDLING.md)
