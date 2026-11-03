# Document context during an interview

Design recorded: 2026-11-02; upload coordination updated for 0.19.0 on 2026-11-03. Official documentation snapshots are in ignored `work/docs-*.md`. This document records the chosen architecture and its evidence boundaries. [Build verification](BUILD_VERIFICATION.md) separates executed checks, historical provider evidence and unverified physical audio.

The interview remains the participant's account of the business process. An uploaded workbook, PDF or image can establish documented notes and workflow steps through exact cited excerpts and an audited baseline. It cannot create participant testimony, confirm current practice, establish owner approval or announce that the interview has enough detail. Documented evidence and participant confirmation remain distinct.

## Research and choice

| Official capability | Consequence for this application |
| --- | --- |
| Responses `input_file` accepts files directly. Vision-capable models receive PDF text and page images. Each file must be under 50 MB, with a 50 MB combined request limit. | Useful for an individual visual page, but sending every original in every conversation request is not the storage or retrieval strategy. [OpenAI file inputs](https://developers.openai.com/api/docs/guides/file-inputs) |
| Direct spreadsheet augmentation parses at most the first 1,000 rows per sheet and supplies summaries/header metadata. | A successful direct-file request does not establish that a 50-tab workbook's later rows were read. Preserve and index the complete accepted workbook locally. [Spreadsheet augmentation](https://developers.openai.com/api/docs/guides/file-inputs#how-spreadsheet-augmentation-works) |
| File Search offers hosted semantic and keyword retrieval over uploaded files in vector stores. | A future option for larger text corpora. Retrieval is not a workbook calculation engine or proof that every row participated in an aggregation. [File Search](https://developers.openai.com/api/docs/guides/tools-file-search), [Retrieval](https://developers.openai.com/api/docs/guides/retrieval) |
| OpenAI recommends Hosted Shell for spreadsheet aggregations, joins, charting and custom calculations. Hosted Shell executes in managed containers. | This feature captures business context rather than performing arbitrary workbook analytics. Neither Hosted Shell nor model-directed local shell execution is implemented. [File-input guidance](https://developers.openai.com/api/docs/guides/file-inputs#how-it-works), [Hosted Shell](https://developers.openai.com/api/docs/guides/tools-shell#hosted-shell-quickstart) |

The selected design combines persistent local originals, a complete bounded text index, an early relevance assessment, and an incremental review. The conversation pauses while that review finishes; early findings remain in Assets rather than triggering intermediate conversation. Bounded review requests preserve progress and respect provider limits without implying coverage that spreadsheet augmentation does not provide. The local 64 MiB upload limit is an application storage limit; it does not override any provider request limit.

## Ingestion and source coverage

`documents.py` stores the original before parsing, with a SHA-256 digest, immutable upload context and a scope-bound document ID. Extraction runs separately from upload. SQLite FTS5 holds text chunks and source locations; a transaction publishes the extraction result. Limit failures do not silently publish a truncated text index.

- **PDF:** inventory every accepted page. Extractable text is split without dropping a long page's tail. Source IDs retain page numbers. Pages with no extractable text, or whose text decoding fails, receive an explicit visual-review placeholder rather than a claim that their contents were read. A page containing both text and images currently follows the text-only path: its embedded diagrams, charts, screenshots and image-only text are not automatically sent for visual review. Even a small text header or an incomplete OCR text layer can therefore prevent automatic visual review of the rest of that page.
- **XLSX/XLSM:** inventory every worksheet, including hidden tabs, and index populated cells throughout all accepted rows. A 50-tab workbook and rows beyond 1,000 are within this design; the configured maximum is 100 sheets. Retain sheet names, row intervals and cell ranges. Read formula text and available saved values without recalculating formulas, following external links or executing macros. Missing cached results and chart-only tabs remain explicit limitations.
- **CSV:** index accepted rows and coordinates throughout the file. Cell contents are literal text; formula-like values are not executed.
- **PNG and PDF pages flagged for visual review:** the current visual path sends a PNG or one individual native PDF page per analysis request. PDF selection is limited to pages with empty or failed text extraction; it is not an automatic visual sweep of every page. Searchable model transcription is tagged `origin: ai_visual_transcription` and `verified: false`; it does not become independently verified OCR or participant evidence. Small or rotated text and complex diagrams can be misread. [OpenAI vision limitations](https://developers.openai.com/api/docs/guides/images-vision#limitations)
- **Legacy XLS:** the current runtime has no `xlrd`. Retain the original and report the dependency gap; ask for a copy saved as XLSX or CSV. Do not report successful indexing or install another parser implicitly.

Inventory completeness, extraction coverage and AI review progress are separate measures. An inventory entry establishes that a page or tab exists. Indexed text establishes what the parser recovered. A model-reviewed chunk establishes that a bounded analysis request included that source; none of these alone establishes semantic correctness. Shortened inventory previews are explicitly flagged and do not remove the underlying indexed text.

“Complete local extraction” means visiting every accepted page/tab/row and preserving the supported text content within the stated bounds. It does not mean complete visual interpretation of the original. In particular, mixed-content PDF images and workbook-embedded images/charts are outside the current automatic extraction coverage. A chart-only worksheet can appear in the inventory without its visual contents being read. Export an important diagram or chart as PNG for the available visual path; automatic mixed-page and workbook-chart extraction remain deferred.

## Question-driven analysis and background review

The integration contract is:

1. On an accepted upload, acknowledge once and stop live voice, release the microphone and drain final captions. Capture the process name, objective, current question and a bounded recent conversation window with the upload, separately from the file's untrusted contents. Concurrent uploads join the pending intake rather than starting another conversation.
2. After local extraction, make a small Responses request using the current question, full unit inventory and selected source chunks. Assess relevance, retain useful questions and exact source IDs in Assets. This early assessment neither claims full review nor triggers an interview question or baseline update.
3. Continue a bounded, incremental sweep through the document's chunks. Persist a review cursor and reviewed/total counts. Merge findings with their sources; apply revision and session guards so a late response cannot replace newer analysis or affect another interview. Work already indexed remains available if the provider fails.
4. Wait for all accepted upload batches, file mutations, active reviews and voice-caption draining to settle. Review phase `complete` is terminal even when `review_complete=false` reports limited coverage. Any active extraction/review error blocks the new baseline until retried, removed or parked; it is not treated as successful review.
5. Build the working notes and workflow from authorized sources, audit the proposed map against those sources and the process boundary, then commit both together. Retain the last accepted capture if generation or audit fails. Only after acceptance request one follow-up using that baseline, transcript and exact excerpts; apply its question without replacing the accepted notes with a second generated snapshot. The server independently rechecks document readiness.
6. Provide a purpose, retry or save-for-later action in Assets. Parked files retain their analysis and questions for explicit discussion. If no new usable file evidence remains, keep the existing capture without inventing a follow-up. New uploads, purpose changes and interview changes invalidate obsolete work. Resume voice only when the participant selects **Continue talking**.

FTS5 is a local lexical index, not OpenAI hosted File Search, vector search or a relational workbook engine. Different terminology, implicit relationships or values lacking the query's words can be missed. A full inventory helps select likely sections; the background sweep broadens review beyond keyword hits over the supported extracted sources. It does not add the visual content omitted by the extraction path. This reduces dependence on initial retrieval but does not guarantee exhaustive understanding. A paused, failed or incomplete sweep must retain that status and its progress rather than report the document fully reviewed.

The implemented sweep batches at most eight chunks and 24,000 text characters, with at most one visual source per request. Retained analysis is bounded to 40 questions, 200 observations and 200 KiB of metadata per document. Reaching a retention bound sets an explicit limitation and prevents the `review_complete` flag even when the sweep reaches its final chunk; full indexed sources remain searchable. Conversation-context selection is smaller again: at most six relevant documents, 18,000 excerpt characters, shortened summaries and two retained questions per document. A successful conversation request therefore does not mean every stored source or review note was included in that request.

Document findings may support documented memo findings, workflow steps and the next interview question through the separate documentary evidence catalog. They must not be placed into participant turns or eligible participant source-ID sets, and cannot establish participant confirmation or completeness. Model instructions embedded in cells, page text or images remain untrusted reference content. Application instructions and permission decisions stay in application code and the trusted provider instruction layer.

## Voice pause and explicit continuation

Ordinary uploads do not stream intermediate context into a speaking voice session. Intake stops the session, releases its microphone and awaits final captions before committing the baseline. The acknowledgment and completed follow-up may use configured question playback, which does not reopen the microphone. **Continue talking** starts a new session after the intake settles.

`CollectorLiveVoice.start({context, turns, voice, document_scope})` forwards the current scope to the local `/api/live-session` endpoint for authorized document-context lookup once at startup. The application does not append those files again after startup. The controller does not retain a scope across calls or put that authorization token in greeting/context events; another interview must supply its own scope explicitly.

**Retained controller capability, not the ordinary upload path:** `CollectorLiveVoice.appendContext(text, {id, kind})` can add concise context to an existing GPT-Live session. It queues during startup and sends `session.thinking.append` only after `session.started`, with `delegation_id: null`. It does not restart voice, create a transcript turn, alter session instructions, or send `session.commentary.append` to request speech.

The first empty-history voice session has a separate opening flow: trusted startup greeting instructions are followed by one `session.commentary.append` after `session.started`. Resumed history and repeated startup events do not repeat that greeting. This opening request is independent of document delivery; its acknowledgment does not establish that the greeting was spoken or played. [GPT-Live opening guidance](https://developers.openai.com/api/docs/guides/live-conversations#greet-before-the-caller-speaks)

For that retained append capability, the controller correlates `session.thinking.appended` through `client_event_id`; `start_ms`/`end_ms` describe context delivery on the session timeline, not spoken acknowledgment or proof of comprehension. Acknowledgments can remain pending while the timeline pauses. A rejected append is handled separately from a failed voice connection. These distinctions follow the [official GPT-Live context contract](https://developers.openai.com/api/docs/guides/live-conversations#add-context-during-the-conversation).

The retained append capability limits each update to 16 KiB of UTF-8 text; its pending queue is bounded to eight updates, 64 KiB of encoded content and 256 events. Each complete append content envelope is at most 480 UTF-8 bytes, a conservative bound beneath the documented 500-token ceiling. Receipts distinguish queued, sent, acknowledged, rejected and cancelled updates. Stop and session replacement clear pending context; old events cannot acknowledge a new session's update. The last 64 completed IDs are cached; revised findings or explicit retries use a new update ID. A historical microphone-free provider probe acknowledged the startup greeting and queued context update. It does not verify the 0.19.0 intake flow, physical audio or live rejection recovery; see the verification receipt for executed scopes.

## Persistence, privacy and recovery

Originals and the SQLite index live in `work/documents/`, outside source control. Directories use mode `0700`; original files, database files and SQLite WAL/SHM files use `0600`. Atomic original writes and database transactions protect local consistency. This is private local storage, not encryption at rest or a multiuser identity system.

Every document read, mutation, search, source lookup and original access is authorized by an interview scope token. The database stores its hash. A saved interview's JSON export retains the token and document metadata so the same local installation can reconnect to the stored originals. Treat that export as private because the token authorizes access to its local document scope. A Markdown review can retain human-readable references, but neither format is a portable bundle of the original binaries. Opening a copied interview on another machine requires re-uploading the originals; a missing local scope must not appear to have restored them.

Removal archives a document reversibly. It excludes the file from active retrieval while preserving the original and index for restoration. Archived originals still count toward the scope's file limit. Archive is not permanent erasure; permanent deletion and a user-managed retention policy are separate, unimplemented operations.

Responses requests use `store: false`. This integration does not create OpenAI Files, vector stores or Hosted Shell containers. Selected text and visual inputs are still sent to OpenAI for processing; `store: false` must not be described as a guarantee that no provider-side processing records or retention can exist. No external document-retention service or cross-machine backup is implemented.

On parser or provider failure, retain the original, current indexed sources and explicit failure/progress state. A restart can resume pending local work. The final verification must demonstrate recovery and ensure that archived, superseded or differently scoped documents cannot be applied by a late background response.

## Current bounds and dependencies

| Bound | Current value or policy |
| --- | --- |
| Original size and files per interview | 1 byte–64 MiB per original; 20 originals including archives |
| PDF pages | 500; encrypted PDFs require an unlocked copy |
| Workbook sheets, rows and populated cells | 100 sheets; 1,048,576 rows per sheet; 2,000,000 populated cells per workbook |
| Text index | 64 MiB per document; 50,000 chunks; 6,000 characters per chunk |
| AI sweep batch | Eight chunks; 24,000 text characters; one visual source per request |
| Retained AI notes | 40 questions; 200 observations; 200 KiB metadata per document, with explicit limit indicators |
| Individual spreadsheet cell | 100,000 characters |
| Inventory metadata | 50 KiB; shorten preview samples explicitly, retain unit names/counts |
| Archive expansion | 512 MiB total, 128 MiB per member; compressed expansion ratio at most 500 |
| PDF decoded content | 16 MiB per page, 128 MiB total |
| PNG | 40 million pixels, plus original-file and provider limits |

`requirements-documents.txt` pins the parser packages present in the configured Python runtime: `pypdf==6.10.0`, `openpyxl==3.1.5`, and `Pillow==12.3.0`. SQLite/FTS5, CSV and ZIP support come from Python's standard library. `xlrd` is deliberately not listed because it is not installed. A different runtime must install these requirements and provide SQLite FTS5 before the same parser coverage can be claimed.

## Deferred capabilities and verification

Managed File Search could add semantic retrieval over a larger corpus; it would introduce hosted file/vector-store lifecycle, deletion, cost and authorization work. Hosted Shell could support deterministic workbook calculations and joins; it would need a bounded analytics workflow and separate artifact/retention controls. Neither capability is implemented by this design. A future Claude adapter could share normalized source locations and analysis schemas, but no Claude provider integration or parity verification is implemented.

The final verification receipt must separately record:

- Complete-corpus fixtures, including a 100-page PDF and a 50-tab workbook with data beyond row 1,000; coordinate/source readback; mixed-content PDF, visual and formula limitations; no silent truncation.
- Scope isolation, malicious file/container handling, permissions, archive/restore, restart recovery and saved-interview references.
- Relevant, ambiguous and unrelated documents; purpose asked once; parked context; progressive findings; provider failure; stale background responses; unchanged participant-evidence and readiness gates.
- Browser upload and source review during an ongoing interview, responsive layouts, export/reopen, one acknowledgment, microphone release/final-caption draining, audited baseline ordering and explicit voice continuation.
- Synthetic provider calls and real microphone/speaker checks, with executed, passed, failed, skipped and unverified scopes stated separately.

Executed results and remaining coverage are recorded in [build verification](BUILD_VERIFICATION.md). Architecture descriptions alone are not verification claims.
