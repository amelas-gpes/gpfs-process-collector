# AI Process Collector

An adaptive voice interviewer that helps people explain how a business process works today, then turns their account into a reviewable memo, process map and detailed procedure.

Version **0.14.0** adds purposeful curiosity across typed and voice interviewing. Naming a step is distinguished from explaining how it works: the interviewer should deepen one useful mechanism, condition, check or handoff before moving on when that prevents an assumption. The question audit also checks for missed depth, while retaining the eleven-topic framework, no-repeat rules, explicit unknowns and participant stopping choices. See the [curiosity policy and examples](docs/INTERVIEW_CURIOSITY.md).

Version **0.13.2** restores progressive workflow and memo updates during continuous speech. New captions no longer discard every completed capture; rewritten evidence still invalidates an older result. Background failures are visible during Voice. Managed terminal previews can use `launcher.py --no-browser --foreground` to retain an active server session.

Version **0.13.1** applies spoken and typed corrections to the affected workflow components. The current map and memo accompany each update; omitted steps, routes and topics are retained. Explicit removals require a quoted participant correction and a named target. Stable step IDs and atomic validation protect unrelated work. See the [workflow correction behavior](docs/WORKFLOW_UPDATES.md).

Version **0.13.0** adds dedicated transcript exports for AI question-quality review and general storage. In **Transcript**, choose **Markdown (.md)** or **JSON (.json)** and select **Export**; **More → Export transcript (.md)** works from any view. No draft or AI request is required. The complete transcript, eleven-topic memo snapshot and review guidance are included; private restoration capabilities and unsent text are excluded. See the [transcript export guide](docs/TRANSCRIPT_EXPORT.md).

The fifteen usability improvements and reliability audit fixes remain included: paged Admin metadata and lazy details, complete source navigation, independently paged histories, graph refinement, saved-interview validation, keyboard recovery, reduced motion and stale-build detection. See the [application audit](docs/APPLICATION_AUDIT.md) for verified coverage and limits.

The interface uses the shape-only GPFS logo in both the header and audio-responsive conversation presence, with the company lettering removed. Its five symbol elements gather inward while listening and open outward while speaking, with confined surface light and stable identification. Separate microphone and actual playback meters drive the response; captions never imply speech. Reduced-motion mode keeps clear, static state changes, and hidden views pause visual rendering. [GPFS asset provenance and motion design](docs/GPFS_ASSET.md) document the original vector and behavior.

The app starts with the conversation: select **Start voice** and begin talking, with no process name to fill in first. The app suggests a title from participant answers as the working process takes shape. You can edit that title at any time; a manual title takes precedence and is preserved when saving and reopening the interview. PDF, PNG, XLSX, XLSM and CSV reference files can be added before or during the conversation. A detailed **Report**, complete Markdown exports and an interactive workflow canvas remain available.

Switch directly between **Voice**, **Transcript** and **Workflow** while the same voice session continues. The GPFS symbol responds to separate measured microphone and playback audio; microphone controls remain available across the three views. The transcript, workflow and eleven-topic live memo stay inside their own areas, with a memo sheet on smaller screens. Live voice uses **GPT-Live 1** over WebRTC.

The interview now includes transcript search, exact-source return navigation, a labeled Save action, and actionable memo gaps. Workflow and Review maps offer step selection and **Follow path** with explicit reported branch choices. Reports have a sticky contents menu and search. Admin presents readable business-process records, source excerpts, and compact applied filters; file panels show clear review stages and persistent retry controls. These improvements retain the same conversation and do not create provider requests when navigating, searching, or retrying a local diagram layout.

Participant answers update the working workflow and memo together. Corrections can add, remove or change reported steps and revise findings. **The readiness notification appears only when all eleven memo topics are captured or explicitly not applicable.** Partial, missing or unknown topics cannot trigger it, even if the model suggests otherwise. A correction that reopens a topic withdraws readiness. Captured coverage remains the participant's account, separate from completeness confirmation, process-owner approval and independent verification.

Notifications dismiss after three seconds; a new notification starts a fresh three-second interval. The interview has no duration setting, clock, target or time-based stopping rule. Legacy timing fields in saved interviews are ignored, and timing metadata is omitted from current provider requests, saved sessions and exports. Reported business deadlines and processing times remain ordinary process facts to capture.

The shape-only update passed **82 relevant checks, 0 failed, 0 skipped**, with fresh-page rendering and open-conversation preservation verified. The 0.10.0 baseline passed 316 automated checks, a 16-check synthetic-audio motion exchange and twelve responsive view cases. Physical microphone/speaker quality remains unverified. [Build verification](docs/BUILD_VERIFICATION.md) separates current results from historical real-provider evidence and remaining coverage.

## What it does

**Company knowledge (local prototype):** Submit a process to retain an immutable interview revision, participant attribution and evidence-linked working graph. The Settings → Admin workspace is available only when explicitly enabled for the local owner, or through a trusted server-side authorization integration. Cross-process connections remain proposed until reviewed. See [knowledge graph architecture, setup and limitations](docs/KNOWLEDGE_GRAPH.md).

- Holds continuous, interruptible conversations using GPT-Live 1 without requiring a process title first. Microphone access starts only when the participant selects Start voice.
- Infers an editable process title from participant answers; a user-selected title wins over later automatic suggestions.
- Accepts reference files during Voice, Transcript or Workflow, checks relevance quickly, and continues a source-linked review in the background. Unrelated files can be given a purpose once or saved for later without interrupting the discussion.
- Offers typed interviews, with optional AI or installed computer playback voices.
- Previews a voice before starting: Marin is the default AI voice, with Cedar as an alternative to compare.
- Records answers, transcribes them through the OpenAI API and lets the participant correct the text before sending.
- Chooses adaptive follow-ups using the conversation and standing memo framework.
- Captures normal steps, item stages, responsibilities, locations, checks, exceptions and client-specific differences.
- Updates the live memo and workflow together from the same participant evidence, including during continuous voice conversations.
- Presents a detailed read-only Report alongside the editable memo, procedure, map, lifecycles, variations and review notes. Report includes the full process context, every captured detail, source evidence and all open questions; returning to it refreshes the latest reviewer edits.
- Uses a locally bundled ELK layout engine for the interactive workflow canvas. Layout positions validated steps and connections; it does not generate process facts.
- Saves the full interview through explicit JSON files; uploaded originals, extracted content and review notes persist locally. Saved JSON carries scoped file references and metadata, not embedded originals. Report and Markdown exports include document sources and reading limitations alongside the complete process and evidence.

This is a single-user local prototype. Teams participation is a later integration step.

## Intended Azure handoff

The hosted product will use Microsoft Foundry voice/model services and the organization's managed AI application patterns. The current OpenAI connection is a development adapter. [Azure architecture and developer handoff](docs/AZURE_HANDOFF.md) records the target structure, reusable interview behavior, provider contracts and remaining hosted work. The prototype's local Python server is not the production hosting plan.

## Requirements

- An existing compatible Python 3.12 interpreter with SQLite FTS5 support. The core interview server uses Python's standard library.
- For document parsing, the packages pinned in [requirements-documents.txt](requirements-documents.txt): `pypdf`, `openpyxl` and `Pillow`. These are separate from the core interview runtime and must already be installed in the chosen interpreter or installed explicitly.
- A current browser with microphone recording and WebRTC support for live voice. Optional AI question playback uses WebSockets; installed English computer voices are a local playback choice.
- OpenAI API access for `gpt-live-1`, `gpt-5.4-mini`, `gpt-transcribe` and optional typed-question playback through `gpt-realtime-2.1-mini`. The interview and transcription models can use compatible server-configured alternatives.

No runtime, package, browser, model, font or voice is automatically installed or downloaded when the application runs. Reuse your existing approved interpreter. ELK.js is bundled locally with its license and provenance in `web/vendor/`; the workflow canvas does not fetch a layout library from a CDN.

## Run locally

Configure `OPENAI_API_KEY` through your secure local environment, or an untracked `.env.local` in this repository. `.env.example` lists the recognized settings with an empty key value. The server never sends the key to the browser.

Live voice exchanges SDP through the local server with `/v1/live/sessions`; the project API key stays on the server. For optional typed-question AI playback, the server requests a short-lived Realtime client token with a 60-second lifetime. The browser uses that token to connect directly to OpenAI; the project API key stays on the server.

In PowerShell, point to an **existing** Python executable and launch:

```powershell
$env:VOICE_INTERVIEWER_PYTHON = 'C:\path\to\existing\python.exe'
& $env:VOICE_INTERVIEWER_PYTHON -I -B .\launcher.py
```

Open `http://127.0.0.1:8774/`. To stop this service:

```powershell
& $env:VOICE_INTERVIEWER_PYTHON -I -B .\launcher.py --stop
```

The Windows `Start Collector.cmd` and `Stop Collector.cmd` shortcuts use the same `VOICE_INTERVIEWER_PYTHON` setting. They do not install an interpreter or change global settings. Use `--port` if the default is occupied; stop with the same port. Runtime logs stay in the ignored `work/` directory inside this repository.

For a terminal managed by an agent, add `--foreground` and keep its execution session running. This avoids relying on a hidden background child of a short-lived tool job. Ordinary desktop launches retain their existing behavior. Bounded operational events, without transcript or credential data, are recorded in `work/server-lifecycle.jsonl`.

Default model settings can be changed using `INTERVIEW_MODEL` and `TRANSCRIPTION_MODEL` in server-side configuration. API usage consumes the configured project's credits or billed usage.

## Interview and review

1. Select **Start voice** and start talking. No process name is required; the title will follow what you describe, and you can edit it. Allow microphone access when your browser asks. The app sends microphone audio to OpenAI while connected; the GPFS symbol's inward and outward articulation follows separate microphone and playback audio levels, with status text for listening, speaking or muted states.
2. Speak naturally and interrupt when needed. **Mute mic** stops microphone transmission immediately; **End voice** releases the microphone, then waits briefly for final captions.
3. Switch to **Transcript** to see the conversation or **Workflow** to see the evolving map. Switching views keeps the same voice connection, transcript, unsent text and capture state; it does not make an API request or restart the interview. Each view scrolls within the workspace. The map and memo refresh together after participant answers or a short pause in captions. Later corrections can revise or remove earlier steps and findings; reported sources are validated, but the model can still misinterpret them.
4. Follow **Your memo** beside the conversation, or select **Memo** to open it as a sheet on smaller screens. All eleven topics remain represented, with captured, partial and unknown states; select a topic to inspect its evidence. Select **Type instead** for a typed interview. Optional recording and question playback remain available. Settings contains background, process-owner, objective and playback choices; these are not required to talk. There is no interview clock or duration control.
5. After ending voice, choose **Wrap up** for a final completeness check or **Review draft** for the detailed Report, editable memo, procedure and supporting details. Participant confirmation is separate from owner approval. Updates to the working map never replace edits in Review.
6. Save the interview JSON before closing. Transcript, working map, review draft, title preference and document references are saved together. The full conversation is not automatically persisted. Uploaded files and their review/index data have separate local persistence, described below.

Reconnecting GPT-Live requires a bounded initial history (128 messages and a conservative 7,800 UTF-8 byte text allowance). If the full history cannot fit, the app keeps it intact and offers typing or a saved continuation. Conversation length is not governed by a time target or cutoff. Live access depends on the selected OpenAI project's permissions and quota; failures retain the transcript and give actionable feedback. Review navigation requires ending voice first so microphone controls remain visible.

The built-in **Explore an example** and `Examples/Synthetic-reviewed-session.json` demonstrate a fictional, fully described process. Open the file through **More → Open interview**; loading either example does not itself call the API. The examples are illustrative, not verified company procedures.

Select a topic in **Your memo** to inspect the reported finding and its sources. Use **Transcript** for the full conversation and the seven review tabs: Report, Memo, Map, Procedure, Lifecycles, Variations and Review notes. Use Left/Right, Home or End to move between review tabs; edits are retained. Canvas pan, zoom and selection affect the view; the SVG export includes the full workflow. Viewing these panels does not submit a question or change captured facts.

## Reference files during the conversation

Select the paperclip **Add files** control in any conversation view. Uploads are available without a process name and while live voice continues. Compact file chips show progress; **Files** opens the tray for relevance, indexing coverage, reading limits, exact sources and questions.

An initial review checks the file against the current conversation. Relevant material can produce a short acknowledgment and a grounded follow-up when it fits the conversation. A late result does not replace a newer interview question or an unsent answer; its questions stay available in the tray. If the purpose is unclear, answer **What should I look for?** once or choose **Save for later**. Parked files can continue reviewing quietly, with **Questions for later** available through an explicit **Discuss** action. **Revisit this file** or **Retry review** restarts review when needed. Document claims remain unconfirmed reference material until the participant establishes how the process actually works; an upload cannot complete memo topics by itself.

The tray opens the exact cited PDF page or spreadsheet sheet/cell text for review. It displays incomplete visual extraction, unsupported material, formula limitations and review failures. PNGs and PDF pages without extractable text require AI visual review; visual transcriptions remain unverified. Workbook formulas and saved cached values are indexed as text/data, never recalculated. XLSM macros, external links and embedded actions are never executed. Chart-only sheets remain explicit gaps when their contents have not been reviewed.

For spreadsheets, local extraction indexes populated rows across every accepted worksheet into SQLite FTS5, with sheet/cell references. It does not stop at a header preview or the first 1,000 rows. OpenAI's native Responses `input_file` spreadsheet augmentation uses up to the first 1,000 rows per sheet; this app's local corpus extraction is separate from that smaller model view. [Official OpenAI file-input documentation](https://developers.openai.com/api/docs/guides/file-inputs#how-spreadsheet-augmentation-works). Indexing all accepted source rows makes them searchable; it does not mean the model has already reviewed or understood every row. Initial relevance uses selected content, followed by bounded background review with explicit progress.

Supported limits are **64 MiB per file** and **20 files per local interview scope, including archived originals**. PDFs accept up to 500 pages; workbooks up to 100 sheets and two million populated cells, with at most 1,048,576 rows per sheet. PNGs must be within forty million pixels. The extracted text corpus is bounded to 64 MiB and 50,000 chunks. Files outside supported bounds fail visibly instead of publishing a silently truncated index. Legacy `.xls` is not offered in the upload picker; convert it to `.xlsx` or `.csv`. The parser's optional legacy-XLS path requires `xlrd`, which is not included in the pinned requirements.

Originals, extracted content, the SQLite index, source metadata and review notes are stored in the ignored local `work/documents/` directory. File records retain a bounded copy of the intake context/recent conversation needed to interpret their purpose. **Clear interview** resets the conversation's file references without deleting originals. **Remove** detaches/archives a file from that interview; it is not a permanent file purge. Review can send relevant text chunks, page images and screenshots to OpenAI, as disclosed in the tray.

Save the interview JSON to retain the links back to these files. Reopening it on the same computer can restore those references and verify current file status. The JSON contains metadata and scoped references, not original binaries: moving the JSON alone to another computer does not transfer the documents. Back up or relocate `work/documents/` together with the JSON when preserving the complete local workspace. If a referenced local file workspace cannot be reached, the saved metadata remains visible with an explicit error.

## Memo requirements

- [Memo requirements and acceptance criteria](docs/MEMO_REQUIREMENTS.md): all eleven topics, memo-wide rules, six variation fields, boundary tests, user-added requirements and acceptance scenarios.
- [Standing interview foundation](FOUNDATION.md): included in every interview and draft request.
- [Validation evidence and limits](VALIDATION.md): observed tests, live synthetic checks and unresolved limitations.

The source memorandum is retained locally. This repository preserves its requirements in neutral language without including the original document. The source hash is recorded for traceability. The separately supplied official GPFS logo is documented in the asset provenance above.

## Data and review boundaries

Submitted interview text and recorded audio are sent to OpenAI. Connected live voice continuously sends microphone audio to GPT-Live 1 until muted or ended. Optional question playback also sends question text to OpenAI for AI-generated speech through `gpt-realtime-2.1-mini`; installed computer voices play locally. Generated playback audio is held in memory rather than saved by the application. The server does not automatically save the complete interview or its recordings. Uploaded files, extracted content, their review notes and bounded intake context persist locally; save the full interview JSON explicitly to retain the complete conversation and its file references. `store:false` is used for model response requests and does not replace provider account policies.

Natural AI playback reads the displayed question rather than generating the interview's next question. Before playback, the client compares the returned speech transcript with the requested text, ignoring case and punctuation, and withholds audio on a mismatch. This check can also reject equivalent spoken forms, such as expanded numbers. Stop, a voice change or starting a recording cancels pending playback.

The service binds only to `127.0.0.1`, checks Host/Origin/CSRF values and serves an explicit asset/API allowlist. It is not a shared production service. Review access, retention, deployment and microphone behavior before use with real business information.

The tool cannot guarantee that every relevant fact has been elicited or interpreted correctly. Source IDs establish attribution, not semantic truth. Unknown actors, locations, timing, handoffs and exception paths must remain visible until a knowledgeable reviewer resolves them.

## Offline tests

```powershell
& $env:VOICE_INTERVIEWER_PYTHON -I -B -m unittest discover -s tests -v
```

With an existing Node installation, run the frontend protocol and media checks:

```powershell
& 'C:\path\to\existing\node.exe' .\tests\test_voice_frontend.cjs
& 'C:\path\to\existing\node.exe' .\tests\test_ui_state.cjs
& 'C:\path\to\existing\node.exe' .\tests\test_live_voice.cjs
& 'C:\path\to\existing\node.exe' .\tests\test_workflow_graph.cjs
& 'C:\path\to\existing\node.exe' .\tests\test_gpfs_presence.cjs
& 'C:\path\to\existing\node.exe' .\tests\test_documents_frontend.cjs
```

**0.9.0 historical baseline — 280 offline checks passed, with zero failures or skips:** 132 Python, 56 UI-state, 24 document-frontend, 31 Live voice, 9 playback and 28 workflow-canvas checks. Four small synthetic real-provider document cases passed across nine calls after fixes; earlier failed attempts remain recorded separately. Offline corpus tests covered a 100-page PDF and a fifty-tab workbook with source content beyond row 1,000, including row 1,205. Those larger fixtures were not sent for live model review. Browser observations verified automatic titles, manual-title preservation, a mid-conversation CSV receipt and relevant follow-up, provider-failure recovery and JSON restoration. Physical microphone capture, audible output and interruption quality were not tested for 0.9.0. A separate microphone-free GPT-Live probe verified the opening greeting, expected transcript, inbound audio packets and acknowledged document context; it does not establish physical audio quality. See [build verification](docs/BUILD_VERIFICATION.md) for evidence and limits.
