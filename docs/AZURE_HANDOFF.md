# Azure hosting and developer handoff

## Accepted direction

The intended hosted product runs in Azure, uses voice/model services offered through Microsoft Foundry, and follows the organization's managed AI application conventions. This repository is the functional prototype and handoff source. Its current OpenAI connection is a development adapter, not the production provider decision.

Continue improving the interview, review experience and memo coverage here. Preserve these requirements when the hosting team moves the application into its supported stack. A local OpenAI key, model name or voice choice must not become a hosted deployment prerequisite.

## Reference pattern and evidence

The managed applications reference was read from its GitHub `main` branch on November 2, 2026, at commit `01eff3bf7739e8c45496ebdc40cbed87873a0a9e`. Its README and architecture document describe React/TypeScript/Vite with Entra sign-in, an ASP.NET Core API, separate domain/infrastructure code, an optional background worker, Azure Container Apps and Static Web Apps, SQL/Blob persistence, managed identities and Foundry integration.

Those are source-backed conventions, not verification of the live Azure environment or authorization to reuse another application's resources. The existing reference Foundry client serves its analysis provider; it is not evidence that speech is already configured. Developers should reuse supported platform patterns and libraries where suitable, with app-specific authorization, configuration and data boundaries.

## What carries forward

| Area | Preserve from this prototype | Hosted implementation |
| --- | --- | --- |
| Interview domain | Sixteen-topic rubric, one useful adaptive question, normal route before variants, parked tangents, explicit gaps, closure confirmation and participant-controlled duration | Put rules, schemas and prompt versions in the application's domain/orchestration layer. Preserve evidence attribution and the separate draft audit. |
| Review experience | Editable transcript, step and connection evidence, map/procedure/memo review, explicit save/export, stale-draft indication | Fit the supported React application shell. Preserve behavior rather than requiring the current vanilla JavaScript layout or Python host. |
| AI services | Structured interview/draft, audio transcription, question playback | Separate Foundry adapters for text generation, transcription and speech. Each may use a different deployed model or service. |
| Identity and access | Localhost-only development boundary | Use the managed-app Entra sign-in and server-side authorization patterns, including per-interview access. Browser sign-in alone does not authorize API access. |
| State and evidence | Stable turn IDs, participant statements, review edits and draft status | Version interview state and reviewed outputs in the approved store, with ownership, concurrency checks and audit records. Choose retention deliberately; SQL/Blob are reference patterns, not provisioned dependencies here. |
| Operations | Recoverable errors and explicit resource limits | Reuse supported deployment, readiness, telemetry and rollback patterns. Keep transcripts, recordings and credentials out of routine logs. Queue long draft/export work only where required. |

The current Python `http.server` launcher is a local development convenience. It has no hosted authentication, multi-user isolation, durable session store or production lifecycle. Hosting is an integration task in the managed application stack, rather than exposing that local listener publicly.

## Historical interface in version 0.2.1

For current routes, authorization and provider dependencies, see [API contract](API_CONTRACT.md). The earlier interface below describes the original hosting proposal.

The injected application client exposes interview, draft, transcription, voice-session creation, `public_config()` and `browser_connect_sources()`. HTTP routes obtain public readiness, provider attribution and voice capabilities from that client. A configured provider does not have to possess an OpenAI API key. Public metadata must contain no persistent credentials.

Speech configuration names its provider and transport, available voices and default voice. Voice-session results also identify the transport. The browser dispatches to an explicit supported transport adapter; the existing OpenAI WebSocket authentication and events remain inside the OpenAI implementation. Unsupported transports fail visibly, with no silent call to the development provider. Only server-controlled, explicitly allowed connection origins belong in CSP.

This is an initial separation, not a completed Azure integration or a fully extracted domain library. Prompt orchestration and the OpenAI implementation still share `server.py`; the hosting team can port or extract that logic into the supported backend without preserving this Python file organization.

The 0.2.1 routes were `/api/config`, `/api/interview`, `/api/transcribe`, `/api/draft` and `/api/voice-session`. Their domain output schemas and evidence validation are the useful compatibility baseline. The hosted API can version or rename routes with its UI; it must replace local-only CSRF/shutdown behavior with its own authenticated lifecycle.

## Azure voice choice

Choose and test the actual service before implementing the Azure adapter:

- **Azure OpenAI Realtime:** the closest candidate for current model voices. Microsoft documents backend-issued ephemeral credentials, Entra authentication and browser WebRTC. A model deployment name and Azure resource endpoint are required. Marin and Cedar are documented choices, subject to the selected deployment's availability and behavior. [Microsoft Realtime WebRTC guidance](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/realtime-audio-webrtc).
- **Azure Speech:** separate transcription and synthesis can preserve the existing record → review transcript → submit flow. Speech voice identifiers and supported styles come from the selected resource's voice catalog. [Transcription](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/fast-transcription-create), [synthesis and voice discovery](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/rest-text-to-speech).
- **Foundry Voice Live:** an alternative managed speech conversation service with its own configuration, voice types and event differences. It needs a dedicated adapter and acceptance test. Keep memo/evidence controls in charge of interview behavior even if recognition, generation and speech share one connection. [Voice Live overview](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/voice-live).

An endpoint substitution alone is insufficient. Authentication, deployment identifiers, structured output support, voice catalog, media formats, browser transport, timeouts and error handling must match the selected Azure services. Use managed identity for server access where supported; keep long-lived service credentials out of the browser. If a browser needs a direct media connection, issue a narrowly scoped short-lived session through the authorized backend, or negotiate through that backend.

Interview state must outlive any media connection. Renewing a provider's timed audio session must not close the interview or lose transcript, edits or pending questions. The participant controls meeting duration. There is no advisory timer. Voices are loaded from the selected adapter; the current ten OpenAI voices are not a universal list for every Azure service.

The current browser and saved-session validation accept lowercase AI voice aliases. An Azure Speech adapter must map native names such as `en-US-AvaMultilingualNeural` to stable supported aliases, or deliberately extend both catalog and saved-session validation. Preserve the provider and voice selection when migrating saved interviews; do not silently reinterpret a voice under a different provider.

## Developer handoff and acceptance

Provide the source, neutral memo requirements, synthetic example, prompt/schema versions, regression evidence, API/capability contracts, and a list of implemented versus pending integrations. The developers own Azure configuration, deployment and ongoing operation. No Azure resource, identity, model deployment or company repository is modified by this prototype preparation.

Before hosted acceptance, developers should:

1. Confirm the application placement, supported frontend/backend stack and deployment workflow. Reuse the managed-app conventions without copying resource names, app registrations or permissions from another utility.
2. Select permitted Foundry text, transcription and speech services; verify region, deployment names, model capabilities, quotas, network access and identity roles in the actual environment. Do not automatically fall back to OpenAI if Azure is unavailable.
3. Implement sign-in, per-interview access and durable state/retention. Decide whether raw audio is retained; the present prototype holds it only in memory. Verify isolation with two different users and that reviewed edits survive reconnect/restart.
4. Run an Azure integration spike: discover/select voices, preview, transcribe/correct an answer, generate a follow-up, interrupt speech, handle a failed/expired media session and continue beyond a one-hour plan.
5. Run the memo/evidence acceptance scenarios, including unknown handoffs, contradictory accounts, variations, participant closure and preservation of manual review edits. Test a real permitted process interview for clarity and voice quality.
6. Build and deploy through the team's workflow to its chosen test target, verify the exact revision and Foundry connections, then complete the team's normal release review. Local regressions do not substitute for hosted verification.

Teams participation remains a later input/output channel over the same interview state and rules. It should not require a second interview engine.
