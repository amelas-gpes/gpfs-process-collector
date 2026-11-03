# Prototype validation · November 2, 2026

## Version 0.2.0 voice upgrade

- **61 offline Python tests passed:** 45 original regressions, 4 repository-portability checks and 12 natural-voice API/security checks. Provider responses were mocked. The added checks cover the ten-voice allowlist, Marin default, `gpt-realtime-2.1-mini`, a requested 60-second client-token lifetime, project-key isolation, malformed provider responses and Host/Origin/CSRF/content-type protections.
- **8 offline Node checks passed** using simulated WebSocket and media APIs: acknowledged-item sequencing, PCM-to-WAV framing, withholding mismatched speech, cancellation, incomplete-response rejection, audio-size limits, unrelated-item acknowledgments and Stop resource cleanup. These checks do not exercise a real browser or audio device.
- **Live OpenAI Realtime generation:** Marin and Cedar each generated the requested fictional preview sample, with matching returned transcripts and audio durations of approximately 5.65 and 6.05 seconds respectively. This establishes provider generation for those two voices, not subjective listening quality or successful browser playback. The other eight AI choices were not live-tested individually.
- The implementation offers ten selectable AI voices, Marin by default, plus an explicit choice of installed English computer voices and **Preview voice**. AI speech uses a short-lived client token; the project API key stays on the server. API playback does not silently fall back to a computer voice.
- **Observed browser preview:** Cedar reached the “Speaking · Cedar” state and completed without console warnings or errors; the selector then switched back to Marin. This establishes the observed UI flow, not a physical listening test or a subjective assessment of how human the voice sounds.

The browser results in the next section describe the earlier prototype checks, separately from the voice-upgrade preview above.

## Verified

- The original **45 offline regression tests** remain part of the 61-test suite. They cover all eleven memo topics, source/edge validation, unknowns, request limits, local-only binding, Host/Origin/CSRF checks, secret-file isolation, quota-error reporting, advisory time beyond 60 minutes, protected service shutdown, final-check/reply ordering, and closure without inventing another question.
- **Live OpenAI calls with fictional process information:** adaptive follow-up; eleven-topic extraction; draft generation plus a separate grounding audit; explicit unknown accountability and charging; client variation capture; and transcription of locally synthesized speech.
- The synthesized recording transcribed as: “An invoice arrives in the shared mailbox. The accounts payable clerk records it in the invoice log. A manager approves by email.” No real meeting or microphone audio was used for this API check.
- A live interview request at 75 elapsed minutes with a 60-minute plan continued normally. Automated tests also cover other elapsed/planned combinations.
- A live final-check request returned the omissions question with confirmation pending. An explicit fictional participant reply then set confirmation true and produced an acknowledgment, with unknowns remaining open.
- **Earlier observed browser behavior:** live interview start and answer submission, adaptive question display, an installed English computer voice available, eleven-topic coverage, draft review, editing a step and seeing the map update, memo/procedure/SVG downloads, JSON save and restore with the timer paused, and final completeness-check invocation.
- Desktop and narrow-screen layouts were observed. A mobile navigation overlap was corrected. The narrow layout had no page-wide horizontal overflow; the map scrolls within its own region.
- Start/stop launchers were exercised on this host. The server uses the existing Python runtime with standard-library imports. No package, model, browser, font, runtime or environment was installed or copied.

## Grounding review and limits

The first generated draft inferred an unsupported exception-return connection, treated mentioned materials as operated controls, and put variant-only approval work into the normal route. The application now requires connection evidence and runs a separate audit of the candidate against the interview before returning it.

The audited live rerun corrected those major graph/control/variation issues. It retained all eleven topics, kept payment execution outside the described process, preserved unknown overall accountability and charging, and did not fabricate a retry path. **Human review remains necessary.** The reviewed rerun still assigned a mismatch handoff sender and treated a role as a lifecycle location despite missing evidence. Additional standing instructions now explicitly prohibit these cross-section inferences. Those last prompt refinements have not been established as reliable by a broad evaluation.

A live question also revisited a detail the fictional participant had already said they did not know. The standing instructions now require asking who or what material could clarify an explicit unknown, then moving on. Topic status is the model's assessment and can be wrong; preparer/reviewer identification is not proof of overall accountability. Source IDs verify that a referenced statement exists, not that the generated wording is semantically supported.

The user-invoked final-check action is enforced by the application: it always asks an omissions question and sets confirmation pending. A model cannot mark the interview confirmed unless an actual participant reply follows the final check in the transcript. Interpretation of that reply remains model-assisted and is not independent verification.

Drafting and its evidence check took about 86 seconds in the reviewed synthetic run, including the interview and transcription checks. Runtime varies. The browser allows up to 150 seconds per request; a slow provider request can still fail recoverably.

**Not verified:** physical listening to the new AI voices, physical microphone capture on a user's device, subjective listening quality, a full-length human interview, exhaustive capture of everything a participant knows, production security/retention suitability, or Teams participation. The prototype has no Teams integration. Participant confirmation does not constitute process-owner approval or independent verification.

The server does not persist interview sessions. Browser-tab state is lost when closed unless the user explicitly saves a JSON file. API text/audio leave the computer for OpenAI, including question text when a natural AI voice is selected; installed computer voices play locally. Playback audio is held in memory. `store:false` is used for model response requests, without making a claim about provider-side data policies.

The AI speech transcript check compares normalized text before playback and rejects a mismatch. It is a text guard, not independent verification of the audible recording, and may reject equivalent expanded numbers or abbreviations. Cancellation and resource cleanup passed mocked checks; real-device behavior still requires review.

## Run the offline checks

From this folder, with the existing runtime:

```powershell
& $env:VOICE_INTERVIEWER_PYTHON -I -B -m unittest discover -s tests -v
& 'C:\path\to\existing\node.exe' .\tests\test_voice_frontend.cjs
```

Loopback access was needed outside the command sandbox to run HTTP tests. Test traffic remained on an ephemeral local test server, with OpenAI mocked. Live checks used only a fictional interview and synthesized speech.

## Implementation references

The prototype uses the [Responses API's structured output format](https://developers.openai.com/api/docs/guides/structured-outputs) and the current [file-transcription workflow](https://developers.openai.com/api/docs/guides/speech-to-text). Model availability was checked against the official [GPT-5.4 Mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini) and [GPT-Transcribe](https://developers.openai.com/api/docs/models/gpt-transcribe) pages. Natural AI playback follows the documented [Realtime WebSocket connection](https://developers.openai.com/api/docs/guides/voice-websockets), [client-secret creation](https://developers.openai.com/api/reference/resources/realtime/subresources/client_secrets/methods/create) and [conversation/audio events](https://developers.openai.com/api/docs/guides/realtime-conversations). The memo's process-capture framework is documented in FOUNDATION.md.

## Publication copy

The repository copy keeps environment-file lookup and runtime logs inside its own directory, provides interpreter-configurable launch scripts, and uses generic branding. The original local installation is preserved. Local account setup records, credentials and host inventory receipts are excluded. Tests were rerun against this publication copy. No automatic installation or CI download workflow is included.

## 0.2.1 provider interface and Azure direction

The intended hosted application uses Azure/Microsoft Foundry and the managed AI application conventions. The local OpenAI adapter remains the only implemented provider. Public configuration now comes from the injected provider; voice sessions identify their transport and the browser rejects unsupported adapters instead of silently falling back. Browser connection origins remain explicitly restricted. No Azure resource or corporate repository was changed.

The portable repository passed 64 offline Python tests and 9 Node voice checks. The installed copy has four fewer Python tests because its approved local credential lookup intentionally differs from the portable copy. Tests use synthetic credentials and mocked providers. Azure authentication, deployment, model availability and production operation remain unverified. See [Azure handoff](docs/AZURE_HANDOFF.md).

## 0.3.0 interface simplification

The interface now uses monochrome styling, a dedicated eleven-topic memo foundation rail and a compact setup form. More context, voice options and data/saving information use native disclosures. The memo review presents eleven compact topic rows that expand for answers, statuses and sources. Technical connection details and repeated onboarding copy were removed from ordinary screens. Source labels are readable Answer/Question references; original evidence IDs remain in the data and exports.

Observed checks used fictional process information: native validation reopened a hidden required field and focused it; a live first question loaded and focus reached the enabled reply box; Marin preview reached Speaking; memo text/status edits worked; Starting context reopened the setup fields; save/open restored a reviewed draft with the timer paused. All eleven memo sections and six procedure steps were present in exports with evidence retained while the review disclosures were closed. The SVG retained six step titles and used neutral colors. Browser console showed no warnings/errors in the checked flows.

The initial workspace and expanded voice settings were checked at 320px and 390px widths with no document horizontal overflow. Mobile controls were made readable, and the temporary viewport override was reset. These are observed layout checks, not a full device or accessibility certification. Physical microphone behavior, print rendering and a complete human interview were not retested for this visual update.

The existing 64 Python regressions and 9 Node voice checks passed. Existing Python/Node/browser resources were reused; no packages, fonts, assets, frameworks or environments were installed or downloaded. Memo source integrity remained unchanged. The Azure provider and hosting integration remain pending as documented in the handoff.
