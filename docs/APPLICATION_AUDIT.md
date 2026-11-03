# Application audit — November 3, 2026

The active objective is to audit the entire UI/UX and backend architecture, fix reproduced defects, push verified changes, and continue reviewing until no further reproducible defects are found. This is an ongoing audit, not a claim that software is free of bugs.

## Architecture and boundaries

The app is a local single-user prototype. The browser holds the editable conversation; explicit JSON export preserves it. Loopback HTTP serves the interface and authorizes requests through Host, Origin, CSRF and server-owned Admin checks. Provider credentials stay on the server. Uploaded originals and extracted sources remain local. Document review and cross-process matching receive selected, bounded context through injected provider adapters. SQLite retains knowledge revisions and review history.

```mermaid
flowchart LR
  B[Browser workspace] --> H[Loopback HTTP boundary]
  H --> I[Interview provider adapter]
  H --> D[Private document store]
  H --> K[Knowledge revisions and evidence]
  D --> W[Document review worker]
  W --> P[Configured AI provider]
  K --> M[Bounded matching worker]
  M --> P
```

Existing boundaries remain explicit: this is not a shared hosted service, production identity system, or independent verification of employee accounts. No user data, credentials, or actual business interviews are included in test fixtures.

## Audit coverage

| Area | Evidence and changes |
|---|---|
| Welcome, conversation, memo, transcript, Review and workflow | Existing desktop/phone screens and source inspected; searches, source return, path navigation and complete exports checked. File-purpose capture now follows the actual question and current file intent. |
| Saved interviews | Opening locks conflicting editing/uploads; fallible local fields are validated before replacement. Failed opening preserves the existing interview and unsent answer. Renaming alone no longer requests another AI extraction. |
| Browser/file lifecycle | Conflicting file actions are serialized; file discussion waits for an active reply. BFCache restoration replaces aborted controllers, ignores old responses and resumes status safely. Interrupted source reads offer retry. |
| Admin submissions and filters | Frozen attempts retain their key/body through a lost response. One active submission is admitted. Session and view epochs reject stale receipts and late administrative completions. System filters match the correct revision. |
| HTTP and launcher | Connections, header/body reading, upload concurrency and shutdown ordering are bounded. Failed construction and failed launch clean up only owned resources. Invalid ports fail before launch. |
| Evidence and knowledge persistence | Non-finite data and malformed workflow arrays are rejected; file events cannot become participant evidence. Revision types and shutdown/retry races are guarded. Request-intent idempotency is separated from mutable file analysis. |
| Knowledge performance | In a synthetic 40-submission fixture, full Admin snapshot SELECTs fell from 98 to 10, retaining all entities, edges, jobs, canonical groups and history. Matching scope/candidate filtering happens before file-source resolution. |
| Large documents and background work | Poll/worker scheduling is atomic; obsolete intents are removed. Storage error reporting cannot kill the worker. Revisit rereads the complete indexed content; unread/empty sources cannot claim complete review. Workbook formulas preserve meaningful text/metadata and readers close on initialization failure. |
| Live transport and animated presence | Source reviewed; narrow transport-send, recovery-timer, callback-isolation and caption chronology fixes made. Presence lifecycle reviewed and its deterministic visual checks run. Voice paths were not executed. |

## Verification policy and limits

Tests use synthetic fixtures, temporary storage, fake analyzers and local sockets. The browser review uses only the built-in fictional example. No new interview answers, file uploads to a provider, voice sessions, microphone/speaker access, or AI credits are used. Physical voice behavior and live model quality remain unverified. The Live controller changes receive syntax and source review only, respecting the existing voice-testing restriction.

Already-running parser/provider callbacks cannot be forcibly canceled by the current adapters. Document shutdown offers a short grace, prevents new analysis dispatch and suppresses late analysis publication. A process exit may still end a daemon parser; durable originals permit later recovery.

## Remaining audit work

- Admin snapshots still return full retained histories. Query batching fixes database work; coordinated pagination and lazy detail loading are still needed to bound transport/browser memory for a large company graph without hiding data.
- Continue the integrated failure/recovery and accessibility review against the next delivered build.
- Continue source review after the current fixes. The goal remains active until the completion audit has evidence for the whole objective.

Commands, exact results, browser evidence and delivery status for each batch belong in [build verification](BUILD_VERIFICATION.md).
