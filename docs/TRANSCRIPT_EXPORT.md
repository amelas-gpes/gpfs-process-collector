# Transcript exports for interview review

Open **Transcript**, select **Export**, then choose Markdown or JSON. For a quick readable copy from Voice, Workflow or Review, use **More → Export transcript (.md)**. Exports work as soon as a recorded message exists, including an unfinished interview without a generated draft or configured AI provider. Empty conversations cannot be exported.

Share the Markdown file with an approved reviewer or AI assistant to assess the interviewer. JSON provides the same content for structured storage and analysis. Exporting runs entirely in the browser; it does not request an AI response, upload the file, train a model, or clear the interview's unsaved indicator. Use **Save** separately to retain a private file that can restore the full interview in this app.

## Contents

- Process name, owner role, objective and supplied context.
- Every stored message in chronological order, with sequence number, stable turn ID, original role and exact text. No search filtering, pairing or summarization removes messages.
- Clear attribution for participant messages, AI messages and file-context updates; a file-related interviewer question remains an interviewer message.
- All sixteen memo topics, their latest recorded status/answer, topic guidance and cited participant turn IDs. Missing assessments remain unknown. Capture coverage, participant confirmation and owner approval remain distinct.
- Working summary, current focus, parked topics and available draft open questions, with a stale-draft warning where appropriate.
- An AI review brief asking for evidence by turn ID, topic gaps, ambiguity, assumptions, premature closure, weak or missed follow-ups, and specific improvements to interviewer guidance.

Markdown uses dynamically sized text fences so pasted code, Markdown and multiline answers retain their exact text. JSON uses `format: "ai-process-collector-transcript"` and `schema_version: 1`. Its stable top-level fields are `exported_at`, `app_version`, `app_build` (the commit of a packaged release, or `dev+` and a source hash for a working tree; `unknown` when the server does not report one), `process`, `synthetic_example`, `capture`, `counts`, `turns`, `memo`, `interview_notes`, `document_references`, and `review_guide`.

## Interpretation and sharing

These are review/storage snapshots, not independently verified business procedures or complete restoration files. No per-turn memo history or turn timestamps are stored, so exports do not invent either. The export timestamp is the time the copy was made. During an active capture, stored captions can be provisional; memo analysis can lag newer answers. All topic checks still need to be assessed against the transcript, even when the app's latest snapshot marks them captured.

The sharing format uses an explicit allowlist. It excludes provider configuration, document-scope capabilities, knowledge status tokens, unsent composer text, raw recordings, file originals and document analysis bodies. Supporting documents may still be needed to judge a file-related exchange; their contents cannot be inferred from a file receipt. Conversation text and supplied context are preserved as entered, so review their business information before sharing with an authorized recipient. There is no automatic redaction of sensitive information within the actual conversation.

To request a useful review, attach the exported `.md` or `.json` and ask: “Assess the interview against all eleven memo topics. Cite turn IDs where the interviewer should have clarified or pushed deeper. Suggest the missed follow-up questions and changes to the interviewer guidance.” The same guidance is already included in each export.
