# Changelog

One entry per release, newest first. A release is a commit on `main` in which `VERSION` in
`server.py` was raised; tag that commit `v<VERSION>` and add its entry here in the same change.
Between releases, changes are collected under "Unreleased". The release number alone does not
identify the code that is running: Settings > Data handling, saved interviews and transcript
exports also carry the build (a desktop release's commit, or `dev+` and a source hash for a
working tree). See [docs/DESKTOP.md](docs/DESKTOP.md#which-build-is-running).

## Unreleased

- Corrected how the interview handles late diagram checks, retries and Wrap up. A failed notes update can still deliver a diagram, and a late map leaves synchronized review notes intact. Diagram exports reconnect branches to their reported source steps, including rework loops and routes repeated in older saved drafts. [Review findings and verification](docs/testing/runs/2026-11-17-diagram-review/README.md)

The workflow diagram keeps up with a typed interview. This is the first part of the [diagram brief](docs/enhancements/diagram-speed-and-layout.md), for findings 1 to 5 of the [November 17 stress run](docs/testing/runs/2026-11-17-stress/README.md). It was verified with stand-in providers only; [what was checked and what still needs a run against the AI service](docs/testing/runs/2026-11-17-map-lanes/README.md).

- **A new answer no longer cancels the map being drawn.** The map of an earlier answer is kept when the conversation has only grown since. Workflow shows it as “Map through answer N · later answers pending”, and the next map starts from it instead of from nothing. A map of wording that was edited since is still discarded. (Finding 1)
- **The map appears as soon as it is drawn; its source check runs beside it.** The check took longer than the drawing (112 s against 41 s) and stood in front of it. The drawn map has passed every check the app makes without a model. Workflow says “Updated through the latest answer · check pending” until the check has run, and drops the suffix when it has. The check reviews only what changed since the last checked map, and its result is kept under any map drawn while it ran. (Finding 2)
- **The model that draws the map is given the map's rules again.** Since 0.30.0 the background map was drawn from instructions cut before the routing, component and step-detail policies: 103 of 106 maps in the stress run. The source audit was the first model to read those rules and rewrote most steps of every map it checked. This also covers the rule that a gate lies on the route it governs. (Finding 2)
- **A map is no longer lost to a time limit or an output limit.** A check that fails leaves the drawn map on screen (“· check incomplete”) and is tried once more at Wrap up; if it still has not finished, Workflow offers **Update workflow**. A map cut off at its output allowance is asked for once more with a larger one. The allowance is 16,000 tokens (24,000 with files); a background map has 300 seconds to be drawn and 420 to be checked. (Finding 3)
- **Several maps are drawn at once, in turn.** One worker served every interview on a server and stayed with one interview for as long as it had work. `COLLECTOR_MAP_WORKERS` (default 2) maps are drawn at once and an interview with more to draw queues behind the others. (Finding 4)
- **Cancelling a request to the AI service frees it at once.** A cancelled map kept its worker and a provider slot until the provider had finished, up to four minutes. Only a discarded conversation cancels work now, and that request ends within a second.
- **Questions do not queue behind background work.** `COLLECTOR_PROVIDER_SLOTS` (default 6, was a fixed 4) requests run at once, and notes and maps leave two of them free for questions, transcription and voice.
- **At Wrap up a map built answer by answer is compared once with a map of the whole account** and replaced only when that one carries clearly more: it cites an answer the other never cites, or has more than about a seventh more steps.
- **In Live voice the map starts from a finished caption**, as the notes do. It started one second after the first words, from part of a sentence. (Finding 5)
- **The Live interviewer is told to ask one question per turn and to leave a detail alone once the speaker has said they do not know it.** This is wording in its instructions; no voice session was run to confirm the effect. (Finding 9)
- Not changed: spelling hints for Live voice captions (finding 10). Reviewed voice sends `TRANSCRIPTION_KEYWORDS` to the transcription endpoint; no such setting is documented for a Live session, and a field the provider refuses would stop voice from starting.
- **The first question about a text file comes after its first review pass**, not after the whole review, which took 161 seconds for an 85-page PDF. The in-depth pass goes on in the background. A file with a scanned page or an image still waits for that reading. Two files are reviewed side by side. (Finding 6)
- **The diagram marks where the work starts and ends and where it branches.** A small dashed circle stands in front of the first step and after each last step when the account does not state a start or an end, and a small dashed diamond follows a step that several routes leave. The markers are part of the picture only: they are not steps, cannot be selected, are not saved or sent, and are left out of the SVG file. Lanes by role and compact decision shapes are not included. [Workflow diagrams](docs/WORKFLOW_DIAGRAMS.md#evidence-and-picture) (Finding 7)
- The status reply of a conversation says whether its map was checked (`workflow_checked`, `workflow_check_state`, `workflow_version`) and can carry the map through an earlier answer (`workflow_checkpoint`). [HTTP interface](docs/API_CONTRACT.md)

Three corrections to the map's source check, found by an independent review after the change above was merged. Each has a test that fails on the code as first merged.

- **A file set aside during an interview no longer stops the map's source checks.** A step drawn from a file that was then saved for later or removed, or whose passage no longer fitted into one request, was refused as new evidence from a file that could not be read. The check failed before anything was sent, after every further answer, and Workflow stayed on “· check incomplete”. Such a step stays as it was drawn and the check reviews the rest.
- **The map keeps the record of the model and prompt that made it.** A saved interview and an export name the model and prompt behind each result. The map drawn in the background had lost that record.
- **A step the check removed and a later answer stated again returns with its route.** It came back alone, and no later check was asked about the route into it.
- The check keeps the steps and routes of a map in the order they were drawn in.

Testing material reorganized; no change to the app.

- `docs/testing` now separates what a new test needs from what earlier tests left behind: the business process library in `process-library/`, the participant harness in `harness/`, and one dated folder per past run under `runs/`. The November 16 run moved to `docs/testing/runs/2026-11-16-process-capture`. [Testing index](docs/testing/README.md)
- Added the results of the November 17 stress run: 30 processes across typed, file and voice interviews. [Results](docs/testing/runs/2026-11-17-stress/README.md)
- Added `docs/enhancements` for planned work, with a brief for making the workflow diagram fast, reliable and standard. [Planned enhancements](docs/enhancements/README.md)

A cleaner interview workspace: the same information, said once and in fewer words.

- **Notes shows one status line.** The panel stacked up to four lines (“final check not yet run”, the pre-check count, which answers the notes include, and the workflow’s “Updating…”). Each source now marks what it reports, and the panel shows one: trouble first, then work in progress, then what the notes include. The figure is marked “Checked” once the final check has run.
- **The workflow reports in Workflow.** With the review team, a refresh of the map alone no longer writes “Updating…” or “Up to date” under Notes. While the background work has the notes and is still drawing the map, Notes says “Updating the workflow…”. When only the map failed, Notes says so with an **Update workflow** control beside it, and says “Updating the workflow…” while that retry runs instead of asking for it again.
- **The topic list is the only list of open topics.** “Remaining topics”, its unstyled “Next: …” button and the “Now discussing” copy of the question on screen are gone. Topic rows use short labels (“Captured”, “Needs detail”, “In progress”, “Documented”, “Not applicable”), a tick alone for a covered topic, and one colour for the state that asks for something; the tooltip keeps each row’s full state.
- **One line above Wrap up and Create draft says why they wait or what they are for:** “Stop talking to wrap up.” during voice, “Every topic is captured. Wrap up for the final check.” when the list is complete. The notes status no longer repeats that guidance.
- **The team status sits beside the Workspace title** and opens into the role list there. It stays off the page until a role has run, so the conversation no longer loses a row to “Standing by”.
- **The question card starts at the question.** A spoken acknowledgement in front of it (“Mm.”, “Okay, …”) is left to the transcript.
- **Voice controls.** A muted microphone reads as a pressed control; Stop talking is a quiet outlined control. With the reply box open, the voice control is the secondary “Talk instead” and “Type instead” is not offered again.
- **The example has no dead controls.** It offers **Start your own** where the talk and type controls were, and its prepared draft opens from **Open draft**.
- **An error is shown once.** When it stands on the line above the conversation, the toast with the same words is not drawn beside it.
- **Assets says what is needed to add a file.** The extraction limits and the full notice about what the AI service receives open from one line below the list.
- The Workspace tab is **Summary**; the Save copy description is one sentence.

Fixes for the thirteen findings of the November 16 process-capture run. [Findings, acceptance checks and replay cases](docs/testing/runs/2026-11-16-process-capture/README.md)

- **File review no longer stalls on “Reading your files.”** Status polling continues between a file being indexed and its review reporting a phase, and for as long as a file intake is waiting on its files. A file left indexed without a review phase is reviewed on the next poll. (Finding 1)
- **A map is checked for parts its route passes by before it is published.** A check, a selection or a hold that no connection reaches, and a step whose stated input no route supplies, are found without reading any source. The sources are asked once how those parts join; a connection is added only with a quoted passage from a source it cites, and a direct arrow is rerouted only when the verified connections lead through the part that was detached. What the sources do not settle is named in the open questions. The routing policy now says that a gate lies on the route it governs and that one statement listing actions in order reports that order. (Finding 2)
- **A working map is no longer lost to its own source audit.** The audit of a transcript-only map ran into a 120-second limit, and its 12,000-token allowance was used up by reasoning before it could answer, which discarded maps that had been drawn correctly (14 of 17 in the run). The audit now has 180 seconds when the page waits for it and 240 in the background, with a 24,000-token allowance; a background map has 180 seconds to be drawn.
- **Wrap up releases the synchronized notes without waiting for the map.** A map that is still queued or being drawn, or that failed, keeps its own status and its own retry; the page fetches it when it arrives and applies only the map. A failed map no longer fails Wrap up. (Finding 3)
- **The first question after a file is added is asked from the file's own excerpts**, as soon as the file has been read. The notes and the audited map of the same revision are completed in the background and are dropped when the account has moved on. A file-only start now gets a map as well. (Finding 4)
- **A citation a model got wrong is settled internally.** An operating detail that cites a source outside its step, or wording its source does not contain, is dropped; a source ID that is not a source is taken off; a step or connection left with no source is left off the map and named in the open questions. The map is no longer refused for it, and a file follow-up falls back to the file review's own excerpt-bound question when the model's reply cannot be asked. Harmless reviewer slips (a discard of something never proposed, a discard beside a replacement, one skipped route row) no longer fail a map. (Finding 5)
- **An accepted map ends an earlier map failure in both panels.** A failure of the map alone is shown in Workflow with its retry; Notes says the notes are caught up. (Finding 6)
- **The interviewer checks its question against the answers, including the one just given.** It is given the sentences in which the participant said a detail is unknown or unconfirmed, commits to the one detail it is after before wording the question, and is told not to ask again for a stated unknown or for what an answer already explains. (Finding 7)
- **One capture no longer contradicts itself.** Every structured link to another process is stated in the Connections note; an answer that states a requirement or names another process reopens the open gaps of those topics for an explicit decision. (Finding 8)
- **The same handoff described twice is one link** with both citations; a link whose outcome differs stays separate. (Finding 9)
- **Records and receiving processes are not turned into people.** The question and capture policies keep supporting records, the process that receives them and the people who handle them apart. (Finding 10)
- **The interview goal is not recorded as the purpose of the work.** A purpose statement that rests on the intake alone is dropped when evidence states the purpose, and is otherwise the open gap it is. (Finding 11)
- **A PDF page of text with rules, table grids, shaded bars and bullets is no longer flagged as unread graphics**, also when the exporter puts the whole page inside one form object. Images, shadings, slanted lines, arrowheads, large curves and pages with little text of their own still get a visual reading. Files indexed by an earlier build are compared locally, free of charge, and offered for re-indexing when their sections differ (`EXTRACTION_VERSION` 4). (Finding 12)
- **Indexed text, supplied sections, review progress and unread visuals are separate facts** in what the notes are given about a file, as they are in Assets. (Finding 13)

## 0.32.0 · November 16, 2026

- Added **Settings → Agents** for administrators to follow an interview through the app, inspect the instructions used at each stage and copy a prompt.
- The workflow links directly to the prompts for all ten agent roles. The read-only library explains when each template runs and shows placeholders for interview-specific information.

## 0.31.1 · November 16, 2026

- Combined the separate Settings and overflow controls into a single labeled **Menu**. Settings is first, with the existing save, open, transcript, submit, library, example and start-over actions grouped below it.
- Kept Ctrl/Command + comma for direct access to Settings, the unsaved-work indicator and keyboard navigation. Closing Settings returns to the unified menu button.

## 0.31.0 · November 16, 2026

- Rebuilt Settings as a wider workspace with persistent section navigation, a direct header entry, a setting finder and a Ctrl/Command + comma shortcut. The last selected section stays available when reopening Settings.
- Added custom appearance choices, a searchable voice picker with keyboard controls, clearer playback switches, separate interview context, readable recovery and privacy summaries, usage cards, a dedicated logs view and Help & about.
- Kept existing preferences, recovery behavior, interview locks and source-return navigation. Every Settings section is directly visible on mobile. Version and build information are now under Help & about.

## 0.30.2 · November 16, 2026

- Removed the developer content logging banner from the interview screen. Logging information lives in Settings.
- Added **Settings → Application logs** to inspect recent or current-session events, search loaded entries, expand recorded details and refresh the view. Log reads are bounded and protected by the app's request token; private log files remain local.

## 0.30.1 · November 16, 2026

- Open **Context** from the top navigation to edit interview details. **How this works** is now in **Settings**.
- Removed the data notice and duplicate links from the welcome screen. Settings still explains data handling, and app messages use provider-neutral wording.

## 0.30.0 · November 15, 2026

- Start over stops queued interview analysis and pauses file review. A saved interview can resume an unfinished file follow-up. Other tabs sharing the workspace show file changes without interrupting the interview.
- Review preserves the wording and assessment recorded in a saved draft. The memo, report and workflow exports identify their sources. The working map supports local CSV, BPMN, Mermaid, image and print output.
- Settings show provider usage and optional token budgets. New generated records identify the model and prompt, and the desktop host disables form autofill for interview details.
- Pausing an interview keeps its notes. Later answers can update the existing map, and completion review checks the participant's evidence and active files. The interviewer can repeat the final question without starting a second review.
- Live voice can resume a long conversation. The transcript flags speech that could not be captioned. Reviewed voice identifies answers that began while the microphone was paused.
- File review keeps saved excerpts and visual transcriptions through retries. The interview can disclose which passages it read, and the map can retain a citation to a file that has since been parked.
- Filing a process shows which draft, files and answers will be included. Company knowledge preserves the filed revision and detects competing revision submissions.
- **Keep a recovery copy on this computer** is available in Settings and starts off. A saved recovery copy can be restored after a crash. Two windows recording different interviews cannot claim the same recovery slot.

- Settings > Data handling shows the release number and the build. Saved interviews carry
  `app_version` and `app_build`; transcript exports carry `app_build`; `/api/config` reports
  `build`, `release_commit` and `release_staged_at`; the `start` row of
  `work/server-lifecycle.jsonl` carries the commit of a desktop release.
- `build_id` ignores line endings, so a working tree and a downloaded build of the same commit
  have the same value. Its value therefore changes once for every existing checkout.
- Desktop app: downloaded builds are unpacked and checked but run only after approval in the
  window; `rollback`, `hold` and `resume`; a startup check with empty stores before a build is
  given saved data; store formats are recorded. Details are in `docs/DESKTOP.md`.

## 0.29.0

Version **0.29.0** adds a GPFS-branded component library with 91 business operations and 11 workflow symbols. Open **More options → Component library** to inspect the designs, or select a step in **Workflow → Cinematic** to see its captured operating details and sources. Both views use the same captured graph. The browser selects, draws and animates the artwork locally. Reviewers can choose a design for an editable step and keep it with **Save copy**. [Workflow diagrams and component library](docs/WORKFLOW_DIAGRAMS.md)

## 0.26.1

Version **0.26.1** refined the conversation while retaining the sixteen-topic evidence and completion requirements. The interviewer follows the participant's walkthrough, learns scope in context, parks unknowns and asks practical follow-ups. Listening cues no longer split a participant answer; delayed notes cannot replace newer speech or script the next spoken question. See [conversation repair and QA/UAT evidence](docs/CONVERSATION_REPAIR_QA_2026-11-05.md).

## 0.26.0

Version **0.26.0** adds GPFS scope/boundary discovery, conditional calculation and entity questions, rule lineage, stronger control capture, classified variations, cited taxonomy and connected-process leads. The shared rubric now has **16 topics**; reports, saved interviews and exports preserve the new fields. Typed and live interviewing share the selection policy, with compact coverage guidance on the spoken front. See [implementation](docs/GPFS_INTERVIEW_INTELLIGENCE.md) and [QA/UAT evidence and acceptance limits](docs/GPFS_QA_UAT_2026-11-05.md). Human microphone/speaker acceptance and sustained conversational quality remain open.

## 0.25.1

Version **0.25.1** shares the detailed next-question selection policy with the GPT-Live interviewer and its delegated backend, as well as typed/reviewed turns. Live follow-ups use the current conversation directly; they do not wait for background notes or add a separate question-review request. Suggested questions are reconciled with the latest answer and the selection policy. See [live prompt validation](docs/LIVE_PROMPT_PARITY.md) for measured latency and remaining question-quality limits.

## 0.25.0

Version **0.25.0** combines the interview-intelligence candidate with the live-voice changes through 0.24.1. GPT-Live remains the default spoken interviewer, with the managed team capturing its transcript in the background. Typed and reviewed-turn interviews use richer question guidance, all eleven topics, authorized excerpts and source-bound background advice. Personal activities receive conditional commercial requirements, and transcript-only workflows receive source auditing. Reviewed voice prepares its reader connection during transcription and exports local timing records. **Physical voice and sustained interview acceptance remain outstanding:** earlier reviewed-turn trials measured 5.5–9.5 seconds to meaningful audio and some questions still bundled requests; those measurements do not describe the default live path. See [implementation, evidence and validation limits](docs/INTERVIEW_INTELLIGENCE.md).

## 0.24.0

Version **0.24.0** makes spoken interviews immediate: GPT-Live carries the conversation in real time (`VOICE_MODE=live`, the default) while the managed team keeps the notes, map, advisory pre-checks and completion gates from the transcript behind it. The lead's suggested question reaches the live interviewer silently; the acknowledgement, final omissions check and completion line are recorded by the application and read by GPT-Live word for word; completion still needs the application's permit. `VOICE_MODE=reviewed` keeps the 0.21–0.23 reviewed-turn voice. Version **0.24.1** fixes the live voice drifting into voicing the participant's own answers: participant captions are recorded only when the microphone held speech, the notes reach GPT-Live as one short update after each capture instead of a per-fragment stream, exact lines go through the provider's instruction channel, and the live instructions state that it speaks only as the interviewer. See [agent architecture](docs/AGENT_TEAM.md).

## 0.23.1

Version **0.23.1** repairs concurrent process naming and progress reporting. Inferred display titles are separate from source context and survive save/export without invalidating in-flight work. The workspace distinguishes discussed topics from fully captured topics and shows which answer the notes have reached. Equipment/input availability can establish a conditional variation as well as a lifecycle route. No-speech transcription keeps listening; failed recordings can be explicitly retried from bounded memory, with clearer failure messages and metadata-only recognition diagnostics. See [repair validation](docs/CONCURRENT_REPAIRS.md).

## 0.23.0

Version **0.23.0** separates the conversational interviewer from background analysis. Voice and typed answers receive a short next-question response while a bounded worker updates source-bound notes and the workflow. Intermediate pending snapshots coalesce into the latest complete account. The Notes panel shows whether analysis is working, caught up or needs attention. Wrap up synchronizes the actual current transcript before using the existing independent review and confirmation gates. Background questions are never spoken and background findings cannot authorize completion. File intake retains its explicit review phase. See [concurrent interview architecture](docs/CONCURRENT_INTERVIEW.md).

Version **0.23.0** makes the conversation faster without loosening the evidence gates. Only the open claims an answer could affect need explicit reconciliation, so most turns stay on the fast lead model; the lead's response is streamed with the question first, shown as a preview while the notes finish; the working map starts alongside each turn instead of waiting for the Workflow tab; the completion review runs its coverage check as three concurrent topic groups; newly captured topics get a background advisory pre-check (display-only); a prior review reaches the lead as its gaps rather than its full text; and voice pre-fetches its reader token and ends an answer after 1.8 seconds of silence. See [agent architecture](docs/AGENT_TEAM.md) and [workflow updates](docs/WORKFLOW_UPDATES.md).

## 0.21.0

Version **0.21.0** introduced the managed team: one lead interviewer, independent coverage and process reviewers, and an on-demand document analyst. The application owns the final-check and completion gates. Voice transcribes a turn and verifies the reader's transcript before playback; specialists never speak independently. A restrained team panel shows actual work state and expandable role details. The default interview/coverage model is GPT-6 Luna, with GPT-6.1 Terra for process and document review. Physical audio remains untested.

## 0.20.0

Version **0.20.0** checks claimed topic coverage with an independent explanation and evidence assessment. Material gaps keep a section partial; a final response check prevents recognized premature wrap-ups after question auditing. Live voice receives fresh coverage gaps silently and must review all eleven sections before suggesting closure. The interview remembers multiple issues raised in one answer, distinguishes ownership from consequences, and honors explicit participant stops without marking unfinished sections complete. See [interview completeness and its validation limits](docs/INTERVIEW_COMPLETENESS.md).

## 0.19.1

Version **0.19.1** gives document workflow checks more time, reports timeouts separately from connection failures, and keeps failed checks paused until an explicit retry or a file change. Uploaded files and the accepted capture are retained. File intake uses one acknowledgment, a pause while the file is reviewed, an audited update to notes and workflow together, then one grounded follow-up. Select **Continue talking** when ready to resume; voice receives the current file scope once at startup.

## 0.15.0

Version **0.15.0** expands workflows to eleven evidence-backed component types: activities, decisions, starts, endings, parallel splits and joins, alternative-route merges, waits, subprocesses, document operations and data-store operations. Shapes and branch labels wrap to measured text; decisions, loops and dependencies retain their reported topology. Responsive controls, a diagram key and route details support navigating larger maps. See the [workflow diagram guide](docs/WORKFLOW_DIAGRAMS.md).

## 0.14.0

Version **0.14.0** adds purposeful curiosity across typed and voice interviewing. Naming a step is distinguished from explaining how it works: the interviewer should deepen one useful mechanism, condition, check or handoff before moving on when that prevents an assumption. The question audit also checks for missed depth, while retaining the eleven-topic framework, no-repeat rules, explicit unknowns and participant stopping choices. See the [curiosity policy and examples](docs/INTERVIEW_CURIOSITY.md).

## 0.13.2

Version **0.13.2** restores progressive workflow and memo updates during continuous speech. New captions no longer discard every completed capture; rewritten evidence still invalidates an older result. Background failures are visible during Voice. Managed terminal previews can use `launcher.py --no-browser --foreground` to retain an active server session.

## 0.13.1

Version **0.13.1** applies spoken and typed corrections to the affected workflow components. The current map and memo accompany each update; omitted steps, routes and topics are retained. Explicit removals require a quoted participant correction and a named target. Stable step IDs and atomic validation protect unrelated work. See the [workflow correction behavior](docs/WORKFLOW_UPDATES.md).

## 0.13.0

Version **0.13.0** adds dedicated transcript exports for AI question-quality review and general storage. In **Transcript**, choose **Markdown (.md)** or **JSON (.json)** and select **Export**; **More → Export transcript (.md)** works from any view. No draft or AI request is required. The complete transcript, eleven-topic memo snapshot and review guidance are included; private restoration capabilities and unsent text are excluded. See the [transcript export guide](docs/TRANSCRIPT_EXPORT.md).

### Earlier validation checkpoints

The November 3–4 readiness work includes long process simulations, retained failed attempts, independent semantic review, actual parser/provider checks and rendered interface rehearsals. This is a development checkpoint: full-library and held-out acceptance testing are incomplete, and workflow/draft source omissions remain under investigation. All 571 Python tests and 16 JavaScript suites passed before publishing, but those checks do not establish complete semantic accuracy or release readiness. Physical microphone and speaker quality remains unverified. See [current validation limits](docs/BUILD_VERIFICATION.md). The following version notes describe earlier milestones.

Transcript retains its focused conversation workspace: a readable message column, compact file updates, on-demand Find, and a single Export menu for Markdown or JSON. The reply box follows the conversation, with clear Dictate and Talk live options. During live voice, Stop and Mute stay accessible in the transcript header. Long messages remain complete and use the conversation's outer scroll only when needed. Voice, Transcript and Workflow remain at the top right, with Settings and Save copy in the three-dot menu. Notes, Summary + Parked and Assets retain dedicated sidebar tabs.

Attached procedures can supply the documented process directly. Notes, workflow capture, draft generation and the question audit share exact scoped file excerpts, with filename/page citations kept separate from participant answers. Follow-up focuses on missing details, contradictions or differences in current practice. Drop files anywhere in the interview workspace to use the existing upload flow. See the [document interview guide](docs/DOCUMENT_INTERVIEWS.md).

The fifteen usability improvements and reliability audit fixes remain included: paged Admin metadata and lazy details, complete source navigation, independently paged histories, graph refinement, saved-interview validation, keyboard recovery, reduced motion and stale-build detection. See the [application audit](docs/APPLICATION_AUDIT.md) for verified coverage and limits.

The interface uses the shape-only GPFS logo in both the header and audio-responsive conversation presence, with the company lettering removed. Its five symbol elements gather inward while listening and open outward while speaking, with confined surface light and stable identification. Separate microphone and actual playback meters drive the response; captions never imply speech. Reduced-motion mode keeps clear, static state changes, and hidden views pause visual rendering. [GPFS asset provenance and motion design](docs/GPFS_ASSET.md) document the original vector and behavior.

The app starts with the conversation: select **Start voice** and begin talking, with no process name to fill in first. The app suggests a title from participant answers as the working process takes shape. You can edit that title at any time; a manual title takes precedence and is preserved when saving and reopening the interview. PDF, PNG, XLSX, XLSM and CSV reference files can be added before or during the conversation. A detailed **Report**, complete Markdown exports and an interactive workflow canvas remain available.

Switch between **Voice**, **Transcript** and **Workflow** during a voice session. Microphone controls stay available in all three views. The GPFS symbol responds to measured microphone and playback audio. On smaller screens, open **Workspace → Notes** for the sixteen-topic memo.

The interview now includes transcript search, exact-source return navigation, a labeled Save action, and actionable memo gaps. Workflow and Review maps offer step selection and **Follow path** with explicit reported branch choices. Reports have a sticky contents menu and search. Admin presents readable business-process records, source excerpts, and compact applied filters; file panels show clear review stages and persistent retry controls. These improvements retain the same conversation and do not create provider requests when navigating, searching, or retrying a local diagram layout.

Participant answers update the working memo. Open **Workflow** to inspect the latest map. Corrections can add, remove or change reported steps and revise findings. **Readiness requires assessment of all sixteen topics and a successful process review.** New substantive evidence reopens the review. The participant confirms their account, and the process owner reviews the resulting draft.

Notifications dismiss by themselves: a short confirmation after three seconds, a longer message after about 70 milliseconds per character (at most twenty seconds). A new notification starts a fresh interval. The countdown pauses while the pointer is over the notification or its close button has keyboard focus. Errors, and warnings about saved data (voice stopped before the transcript was finalized, provisional coverage after opening a saved interview, a paused review), also stay on the line above the conversation or the report until dismissed. A notification raised while a dialog is open (Settings, the Workspace sheet, a topic) is shown inside that dialog; an error or warning raised there stays until it is dismissed or the dialog closes. The interview has no duration setting, clock, target or time-based stopping rule. Legacy timing fields in saved interviews are ignored, and timing metadata is omitted from current provider requests, saved sessions and exports. Reported business deadlines and processing times remain ordinary process facts to capture.

The shape-only update passed **82 relevant checks, 0 failed, 0 skipped**, with fresh-page rendering and open-conversation preservation verified. The 0.10.0 baseline passed 316 automated checks, a 16-check synthetic-audio motion exchange and twelve responsive view cases. Physical microphone/speaker quality remains unverified. [Build verification](docs/BUILD_VERIFICATION.md) separates current results from historical real-provider evidence and remaining coverage.
