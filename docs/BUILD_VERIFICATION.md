# Publication verification

Verified on November 2, 2026, against the version 0.2.0 repository publication copy.

- **61 offline Python tests passed:** the original 45 prototype regressions, 4 portability checks and 12 natural-voice API/security tests. OpenAI responses were mocked; test HTTP traffic stayed on temporary local servers.
- **8 offline Node checks passed:** simulated Realtime event sequencing, PCM/WAV framing, speech-transcript mismatch rejection, cancellation, incomplete responses, audio-size limits, unrelated acknowledgments and Stop cleanup. No browser or audio hardware was exercised by these tests.
- Live Realtime checks generated the same requested preview sample with Marin and Cedar using `gpt-realtime-2.1-mini`. Returned transcripts matched; audio durations were approximately 5.65 and 6.05 seconds. These results establish provider generation, not browser playback or subjective voice quality. The other eight AI choices were not live-tested individually.
- A browser preview reached “Speaking · Cedar” and completed without console warnings or errors; the selector switched back to Marin. This was an observed UI flow, not a physical listening or subjective voice-quality test.
- Python3.12.14 from an existing compatible installation was reused. Runtime code uses only Python's standard library; no package installation or environment creation was needed.
- The portability checks verify repository-local environment lookup, process-environment precedence, rejection of unrelated ancestor settings, and logs staying inside the repository.
- JavaScript syntax was checked using an existing Node installation. Node is not required to run the application.
- The voice configuration exposes ten selectable AI voices with Marin as the default and Cedar as an alternative, plus explicit installed computer voices and a Preview voice control. The server requests a 60-second Realtime client token; only that short-lived token reaches the browser. Tests reject unsupported voices and malformed token responses and verify that the project API key is not returned.
- The source, example and documentation publish list was checked for actual credential-shaped values, host paths, setup-account metadata and organization-specific branding. The `.env.example` key value is empty. Test-only fake sentinels are not usable credentials.
- Local key files, account setup history, credit information, machine inventory and preflight receipts are excluded from publication.
- No automated package/runtime download or CI setup workflow is included. Future CI setup should apply the owning environment's reuse policy rather than assuming the development host's resources exist there.

Earlier live synthetic API and browser checks apply to the earlier prototype behavior; the voice-upgrade checks are listed separately above. See [VALIDATION.md](../VALIDATION.md) for the full limits. Publication testing does not establish production readiness, reliable exhaustive capture, physical listening or subjective voice quality, physical microphone behavior, or Teams integration. No real business-process interview is included in the fictional example.

The source memorandum's requirements are preserved in [MEMO_REQUIREMENTS.md](MEMO_REQUIREMENTS.md) and the [standing foundation](../FOUNDATION.md), using neutral language. The original branded document is retained locally and is not part of the repository.
