# AI Process Collector

An adaptive voice interviewer that helps people explain how a business process works today, then turns their account into a reviewable memo, process map and detailed procedure.

Version **0.2.0** adds selectable natural AI voices and a preview before the interview.

The interview follows a reusable process-capture framework. It elicits the eleven memo topics naturally, follows useful answers, parks tangents, keeps unknowns explicit and seeks participant confirmation before closing. **60 minutes is the adjustable planning default, not a cutoff.**

## What it does

- Speaks questions using one of ten natural AI voices, or an explicitly selected installed English computer voice.
- Previews a voice before starting: Marin is the default AI voice, with Cedar as an alternative to compare.
- Records answers, transcribes them through the OpenAI API and lets the participant correct the text before sending.
- Chooses adaptive follow-ups using the conversation and standing memo framework.
- Captures normal steps, item stages, responsibilities, locations, checks, exceptions and client-specific differences.
- Produces an editable eleven-topic memo, detailed procedure, SVG map, lifecycle records, six-field variations and open questions.
- Saves and restores sessions through explicit JSON files; exports memo/procedure Markdown and map SVG.

This is a single-user local prototype. Teams participation is a later integration step.

## Requirements

- An existing compatible Python 3.12 interpreter. The application uses only Python's standard library.
- A current browser with microphone recording and WebSocket support. Installed English computer voices are an optional local playback choice.
- OpenAI API access for `gpt-5.4-mini`, `gpt-transcribe` and `gpt-realtime-2.1-mini`. The interview and transcription models can use compatible server-configured alternatives.

No runtime, package, browser, model, font or voice is automatically installed or downloaded by the project. Reuse your existing approved interpreter.

## Run locally

Configure `OPENAI_API_KEY` through your secure local environment, or an untracked `.env.local` in this repository. `.env.example` lists the recognized settings with an empty key value. The server never sends the key to the browser.

For natural AI playback, the server requests a short-lived Realtime client token with a 60-second lifetime. The browser uses that token to connect directly to OpenAI; the project API key stays on the server.

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

Choose **Interviewer voice** and select **Preview voice** before starting. The ten AI choices are Marin, Cedar, Alloy, Ash, Ballad, Coral, Echo, Sage, Shimmer and Verse. Installed English voices appear separately under **Installed computer voices**. Selecting a computer voice is explicit; an AI playback failure does not silently switch voices. The selected voice is included when you save a session.

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

Submitted interview text and recorded audio are sent to OpenAI. Natural AI playback also sends question text to OpenAI for AI-generated speech through `gpt-realtime-2.1-mini`; installed computer voices play locally. Generated playback audio is held in memory rather than saved by the application. The server does not persist interview content or recordings; saved exports contain the information the user explicitly chooses to retain. `store:false` is used for model response requests and does not replace provider account policies.

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
```

**61 Python tests and 8 Node checks passed.** The tests mock OpenAI and use temporary local servers or simulated browser APIs. They make no external API calls or downloads; Node is not required to run the application. See [build verification](docs/BUILD_VERIFICATION.md) for evidence and limits.
