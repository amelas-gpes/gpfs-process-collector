# Prototype validation · November 2, 2026

## Verified

- **45 offline regression tests passed**, with external API responses mocked. They cover all eleven memo topics, source/edge validation, unknowns, request limits, local-only binding, Host/Origin/CSRF checks, secret-file isolation, quota-error reporting, advisory time beyond 60 minutes, protected service shutdown, final-check/reply ordering, and closure without inventing another question.
- **Live OpenAI calls with fictional process information:** adaptive follow-up; eleven-topic extraction; draft generation plus a separate grounding audit; explicit unknown accountability and charging; client variation capture; and transcription of locally synthesized speech.
- The synthesized recording transcribed as: “An invoice arrives in the shared mailbox. The accounts payable clerk records it in the invoice log. A manager approves by email.” No real meeting or microphone audio was used for this API check.
- A live interview request at 75 elapsed minutes with a 60-minute plan continued normally. Automated tests also cover other elapsed/planned combinations.
- A live final-check request returned the omissions question with confirmation pending. An explicit fictional participant reply then set confirmation true and produced an acknowledgment, with unknowns remaining open.
- **Observed browser behavior:** live interview start and answer submission, adaptive question display, installed Microsoft David English voice availability, eleven-topic coverage, draft review, editing a step and seeing the map update, memo/procedure/SVG downloads, JSON save and restore with the timer paused, and final completeness-check invocation.
- Desktop and narrow-screen layouts were observed. A mobile navigation overlap was corrected. The narrow layout had no page-wide horizontal overflow; the map scrolls within its own region.
- Start/stop launchers were exercised on this host. The server uses the existing Python runtime with standard-library imports. No package, model, browser, font, runtime or environment was installed or copied.

## Grounding review and limits

The first generated draft inferred an unsupported exception-return connection, treated mentioned materials as operated controls, and put variant-only approval work into the normal route. The application now requires connection evidence and runs a separate audit of the candidate against the interview before returning it.

The audited live rerun corrected those major graph/control/variation issues. It retained all eleven topics, kept payment execution outside the described process, preserved unknown overall accountability and charging, and did not fabricate a retry path. **Human review remains necessary.** The reviewed rerun still assigned a mismatch handoff sender and treated a role as a lifecycle location despite missing evidence. Additional standing instructions now explicitly prohibit these cross-section inferences. Those last prompt refinements have not been established as reliable by a broad evaluation.

A live question also revisited a detail the fictional participant had already said they did not know. The standing instructions now require asking who or what material could clarify an explicit unknown, then moving on. Topic status is the model's assessment and can be wrong; preparer/reviewer identification is not proof of overall accountability. Source IDs verify that a referenced statement exists, not that the generated wording is semantically supported.

The user-invoked final-check action is enforced by the application: it always asks an omissions question and sets confirmation pending. A model cannot mark the interview confirmed unless an actual participant reply follows the final check in the transcript. Interpretation of that reply remains model-assisted and is not independent verification.

Drafting and its evidence check took about 86 seconds in the reviewed synthetic run, including the interview and transcription checks. Runtime varies. The browser allows up to 150 seconds per request; a slow provider request can still fail recoverably.

**Not verified:** physical microphone capture on the user's device, subjective listening quality, a full-length human interview, exhaustive capture of everything a participant knows, production security/retention suitability, or Teams participation. The prototype has no Teams integration. Participant confirmation does not constitute process-owner approval or independent verification.

The server does not persist interview sessions. Browser-tab state is lost when closed unless the user explicitly saves a JSON file. API text/audio leave the computer for OpenAI; `store:false` is used for model response requests, without making a claim about the account's provider-side data policy.

## Run the offline checks

From this folder, with the existing runtime:

```powershell
& $env:VOICE_INTERVIEWER_PYTHON -I -B -m unittest discover -s tests -v
```

Loopback access was needed outside the command sandbox to run HTTP tests. Test traffic remained on an ephemeral local test server, with OpenAI mocked. Live checks used only a fictional interview and synthesized speech.

## Implementation references

The prototype uses the [Responses API's structured output format](https://developers.openai.com/api/docs/guides/structured-outputs) and the current [file-transcription workflow](https://developers.openai.com/api/docs/guides/speech-to-text). Model availability was checked against the official [GPT-5.4 Mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini) and [GPT-Transcribe](https://developers.openai.com/api/docs/models/gpt-transcribe) pages. The memo's process-capture framework is documented in FOUNDATION.md.

## Publication copy

The repository copy keeps environment-file lookup and runtime logs inside its own directory, provides interpreter-configurable launch scripts, and uses generic branding. The original local installation is preserved. Local account setup records, credentials and host inventory receipts are excluded. Tests were rerun against this publication copy. No automatic installation or CI download workflow is included.
