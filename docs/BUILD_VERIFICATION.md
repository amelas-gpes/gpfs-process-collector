# Publication verification

Verified on November 2, 2026, against the version 0.4.0 repository publication copy.

- **64 offline Python tests passed:** the original 45 prototype regressions, 4 portability checks and 15 voice/provider API tests. A synthetic injected identity provider works without an OpenAI key attribute; unsupported browser connection origins are rejected before binding. OpenAI responses were mocked; HTTP traffic stayed on temporary local servers.
- **9 offline Node checks passed:** simulated Realtime event sequencing, PCM/WAV framing, speech-transcript mismatch rejection, cancellation, incomplete responses, audio-size limits, unrelated acknowledgments, Stop cleanup and unsupported provider/transport rejection before any socket is created. No browser or audio hardware was exercised by these tests.
- Live Realtime checks generated the same requested preview sample with Marin and Cedar using `gpt-realtime-2.1-mini`. Returned transcripts matched; audio durations were approximately 5.65 and 6.05 seconds. These results establish provider generation, not browser playback or subjective voice quality. The other eight AI choices were not live-tested individually.
- A browser preview reached “Speaking · Cedar” and completed without console warnings or errors; the selector switched back to Marin. This was an observed UI flow, not a physical listening or subjective voice-quality test.
- Python3.12.14 from an existing compatible installation was reused. Runtime code uses only Python's standard library; no package installation or environment creation was needed.
- The portability checks verify repository-local environment lookup, process-environment precedence, rejection of unrelated ancestor settings, and logs staying inside the repository.
- JavaScript syntax was checked using an existing Node installation. Node is not required to run the application.
- The voice configuration exposes ten selectable AI voices with Marin as the default and Cedar as an alternative, plus explicit installed computer voices and a Preview voice control. The server requests a 60-second Realtime client token; only that short-lived token reaches the browser. Tests reject unsupported voices and malformed token responses and verify that the project API key is not returned.
- After the 0.2.1 provider separation, the installed application loaded its provider-supplied data notice and service configuration state. Marin preview reached Speaking and completed with no console warnings or errors. This confirms the current adapter still connects; it does not test an Azure provider.
- The Azure handoff records the intended Foundry/managed-application direction and separates current functionality from pending identity, persistence, provider and hosting work. The reference repository's main-branch README and architecture were read at commit `01eff3bf7739e8c45496ebdc40cbed87873a0a9e`; no reference repository or Azure resource was changed.
- The source, example and documentation publish list was checked for actual credential-shaped values, host paths, setup-account metadata and organization-specific branding. The `.env.example` key value is empty. Test-only fake sentinels are not usable credentials.
- Local key files, account setup history, credit information, machine inventory and preflight receipts are excluded from publication.
- No automated package/runtime download or CI setup workflow is included. Future CI setup should apply the owning environment's reuse policy rather than assuming the development host's resources exist there.

Earlier live synthetic API and browser checks apply to the earlier prototype behavior; the voice-upgrade checks are listed separately above. See [VALIDATION.md](../VALIDATION.md) for the full limits. Publication testing does not establish production readiness, reliable exhaustive capture, physical listening or subjective voice quality, physical microphone behavior, or Teams integration. No real business-process interview is included in the fictional example.

The source memorandum's requirements are preserved in [MEMO_REQUIREMENTS.md](MEMO_REQUIREMENTS.md) and the [standing foundation](../FOUNDATION.md), using neutral language. The original branded document is retained locally and is not part of the repository.

## Interface checks in 0.3.0

The monochrome workspace was observed on desktop and at 320px/390px widths without horizontal document overflow. Checks covered required-field disclosure/focus, live interview start, natural voice preview, all eleven expandable memo topics, edits and source navigation, session save/open, and complete memo/procedure/SVG exports with collapsed review details. No console warnings/errors were observed. The original memo source hash was unchanged. See [validation](../VALIDATION.md) for scope and limits.

## Focus and navigation checks in 0.4.0

The 64 Python regressions and 9 voice checks passed. Six additional built-in Node UI-state checks cover exact turn partitioning, pending-question stability, evidence navigation, read-only reported findings, modal focus and review/context jumps with zero provider calls. Actual browser checks confirmed unique turn placement, topic details, Escape/close focus, source jumps, section navigation, preservation and restoration of an unsent answer, current-question narration, and 320px/390px reflow without document horizontal overflow. No console warnings/errors were observed. See [validation](../VALIDATION.md) for the observed scope and limits.
