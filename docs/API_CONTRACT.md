# Local HTTP interface

The desktop window and browser use the same loopback HTTP service. GET `/api/config` returns capabilities, model aliases, build identity, available document types, local storage health and a per-server CSRF token. All POST routes require the current `X-CSRF-Token`, the matching localhost Host and a permitted Origin when present. State-changing requests require an explicit Content-Length. Readiness and administration are separate capabilities. The anonymous `X-Interview-Id` header attributes provider usage.

The interview snapshot contains `context` and `turns`. A turn carries a unique ID, role and text. A capture token, conversation token, review ticket, file scope or submission-status receipt is opaque. Keep it with its own interview. The service resolves source text from the local store and validates citations. A browser-supplied source label cannot grant access.

| Method and path | Caller, input and result |
| --- | --- |
| POST `/api/conversation/turn` | The interview sends a snapshot and action. Returns the immediate question or pause, a conversation token and capture progress. |
| POST `/api/conversation/discard` | Stop queued analysis using the conversation token and pause file review using the document scope. Repeating a successful request is safe. |
| POST `/api/conversation/status` | Poll the current conversation. Returns progress and available notes/map results for that revision. |
| POST `/api/conversation/sync` | Reconcile the current conversation and its background work after new evidence or reconnection. |
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
| POST `/api/knowledge/submit` | File a bounded snapshot as a new process or authorized revision. Returns an immutable revision and private status receipt. |
| POST `/api/knowledge/status` | Read the status associated with a valid submission, revision and receipt. |
| POST `/api/knowledge/admin/browse` | Page through processes, entities, connections, canonical groups or jobs using bounded filters. |
| POST `/api/knowledge/admin/detail` | Retrieve the requested item by kind and ID, with revision where applicable. |
| POST `/api/knowledge/admin/history` | Read a page of changes or decisions for one item. |
| POST `/api/knowledge/admin/graph` | Read a bounded graph with the selected filters and level of detail. |
| POST `/api/knowledge/admin/snapshot` | Compatibility response for older cached clients. Returns 409 directing the client to refresh. |
| POST `/api/knowledge/admin/example` | Open the isolated example knowledge workspace. |
| POST `/api/knowledge/admin/review` | Record a review decision on a proposal at its expected review version, including reason when required. |
| POST `/api/knowledge/admin/retry` | Retry an eligible matching job by ID. Returns its current job state. |
| POST `/api/knowledge/admin/delete` | Delete the selected filed process under the local administrator's authority. |
| POST `/api/knowledge/admin/document-source` | Read a referenced file excerpt belonging to the selected filed revision. |
| POST `/api/knowledge/admin/canonical-create` | Create a canonical group from selected reported entities. |
| POST `/api/knowledge/admin/canonical-update` | Update the selected canonical group with version checks. |
| POST `/api/shutdown` | Local launcher requests orderly shutdown. The launcher verifies checkout and running process identity. |

Successful operations normally return JSON with HTTP 200. Upload acceptance returns 202. Invalid shapes, stale state, unavailable services and oversized uploads return distinct errors. Common statuses include 400 for invalid inputs, 403 for rejected authorization, 404 for missing items, 409 for conflicting state, 413 for size, 415 for media type, 429 for local/provider limits and 503 for unavailable stores. Unexpected server failures return a correlation ID where available.

Local-owner mode or a trusted server-side authorizer controls administration and revisions. A saved receipt permits its scoped status lookup. Example mode uses an isolated store. The current typed concurrent, document-analysis and agent-team flows depend on the built-in provider integration. A hosted adapter must implement and test the corresponding capabilities. [Admin pagination and response fields](ADMIN_API_CONTRACT.md) · [Data handling](DATA_HANDLING.md)
