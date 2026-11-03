# AI Process Collector

An adaptive voice interviewer that helps people explain how a business process works today, then turns their account into a reviewable memo, process map and detailed procedure.

The interview follows a reusable process-capture framework. It elicits the eleven memo topics naturally, follows useful answers, parks tangents, keeps unknowns explicit and seeks participant confirmation before closing. **60 minutes is the adjustable planning default, not a cutoff.**

## What it does

- Speaks questions with an installed local English computer voice.
- Records answers, transcribes them through the OpenAI API and lets the participant correct the text before sending.
- Chooses adaptive follow-ups using the conversation and standing memo framework.
- Captures normal steps, item stages, responsibilities, locations, checks, exceptions and client-specific differences.
- Produces an editable eleven-topic memo, detailed procedure, SVG map, lifecycle records, six-field variations and open questions.
- Saves and restores sessions through explicit JSON files; exports memo/procedure Markdown and map SVG.

This is a single-user local prototype. Teams participation is a later integration step.

## Requirements

- An existing compatible Python 3.12 interpreter. The application uses only Python's standard library.
- A current browser with microphone recording support. Chrome or Edge is recommended for trying the prototype; a local English voice enables question playback.
- OpenAI API access for `gpt-5.4-mini` and `gpt-transcribe`, or compatible server-configured alternatives.

No runtime, package, browser, model, font or voice is automatically installed or downloaded by the project. Reuse your existing approved interpreter.

## Run locally

Configure `OPENAI_API_KEY` through your secure local environment, or an untracked `.env.local` in this repository. `.env.example` lists the recognized settings with an empty key value. The server never sends the key to the browser.

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

Default model settings can be changed using `INTERVIEW_MODEL` and `TRANSCRIPTION_MODEL` in server-side configuration. API usage consumes the configured project's credits or billed usage.

## Interview and review

1. Name one piece of recurring work. Add the interview goal, a role if known, and existing text you are permitted to share.
2. Adjust the planned duration if useful. The elapsed timer can be paused; passing the plan never ends the interview.
3. Start the interview. Record or type an answer, correct the transcription, and select **Send answer**.
4. Follow the actual route from start to finish, then explore checks, exceptions, differences, pain points and gaps. **Finish on pause** can be disabled for answers with longer pauses. Each recording is limited to 90 seconds; continue in another answer when needed.
5. Use **Final completeness check** to invite omissions and corrections. Participant confirmation is separate from process-owner approval and independent verification.
6. Select **Create draft** after any answer. Review and edit the memo, map, procedure, item lifecycles, variations and open questions. Draft generation includes a separate evidence audit; it can still misinterpret a statement.
7. Save the session JSON before closing the tab. There is no automatic session persistence. New answers mark old drafts stale; regeneration asks before replacing edits.

`Examples/Synthetic-reviewed-session.json` is a fictional review example. Open it through **Session → Open saved session**; opening a saved file does not itself call the API. It demonstrates a 75-minute capture against a 60-minute plan with acknowledged gaps.

## Memo requirements

- [Memo requirements and acceptance criteria](docs/MEMO_REQUIREMENTS.md): all eleven topics, memo-wide rules, six variation fields, boundary tests, user-added requirements and acceptance scenarios.
- [Standing interview foundation](FOUNDATION.md): included in every interview and draft request.
- [Validation evidence and limits](VALIDATION.md): observed tests, live synthetic checks and unresolved limitations.

The source memorandum is retained locally. This repository preserves its requirements in neutral language rather than including organization-specific branding or the original document. The source hash is recorded for traceability.

## Data and review boundaries

Submitted interview text and recorded audio are sent to OpenAI. Question playback uses an installed local browser voice. The server does not persist interview content or recordings; saved exports contain the information the user explicitly chooses to retain. `store:false` is used for model requests and does not replace provider account policies.

The service binds only to `127.0.0.1`, checks Host/Origin/CSRF values and serves an explicit asset/API allowlist. It is not a shared production service. Review access, retention, deployment and microphone behavior before use with real business information.

The tool cannot guarantee that every relevant fact has been elicited or interpreted correctly. Source IDs establish attribution, not semantic truth. Unknown actors, locations, timing, handoffs and exception paths must remain visible until a knowledgeable reviewer resolves them.

## Offline tests

```powershell
& $env:VOICE_INTERVIEWER_PYTHON -I -B -m unittest discover -s tests -v
```

The tests mock OpenAI and use temporary local servers. They make no external API calls or downloads. See [build verification](docs/BUILD_VERIFICATION.md) for the publication checks.
