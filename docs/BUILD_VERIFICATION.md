# Publication verification

Verified on November 2, 2026, against the repository publication copy.

- **49 offline tests passed:** the original 45 prototype regressions plus 4 portability checks. OpenAI responses were mocked; test HTTP traffic stayed on temporary local servers.
- Python3.12.14 from an existing compatible installation was reused. Runtime code uses only Python's standard library; no package installation or environment creation was needed.
- The portability checks verify repository-local environment lookup, process-environment precedence, rejection of unrelated ancestor settings, and logs staying inside the repository.
- JavaScript syntax was checked using an existing Node installation. Node is not required to run the application.
- The source, example and documentation publish list was checked for actual credential-shaped values, host paths, setup-account metadata and organization-specific branding. The `.env.example` key value is empty. Test-only fake sentinels are not usable credentials.
- Local key files, account setup history, credit information, machine inventory and preflight receipts are excluded from publication.
- No automated package/runtime download or CI setup workflow is included. Future CI setup should apply the owning environment's reuse policy rather than assuming the development host's resources exist there.

Earlier live synthetic API and observed browser checks apply to the prototype behavior; see [VALIDATION.md](../VALIDATION.md) for their limits. Publication testing does not establish production readiness, reliable exhaustive capture, physical microphone behavior, or Teams integration. No real business-process interview is included in the fictional example.

The source memorandum's requirements are preserved in [MEMO_REQUIREMENTS.md](MEMO_REQUIREMENTS.md) and the [standing foundation](../FOUNDATION.md), using neutral language. The original branded document is retained locally and is not part of the repository.
