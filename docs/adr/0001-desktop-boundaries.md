# 0001 · Desktop application boundaries

Accepted for the desktop application on November 23, 2026.

## Scope

The Windows desktop updater consumes `main`. The web page, Python server and private stores run on one computer. The Windows account controls local file access. The HTTP service accepts loopback connections and validates browser requests. This deployment has no server-verified employee identity by default.

The Azure rebuild lives on `feature/azure-platform`. Its cutover decision retains the desktop release channel until hosted acceptance. The hosted topology, Entra authentication, managed identity, Key Vault, durable queues, immutable storage and environment promotion apply to that implementation. The desktop release makes no claim about their deployment. See [Azure handoff](../AZURE_HANDOFF.md).

## Ownership and evidence

| Boundary | Decision | Executable evidence |
| --- | --- | --- |
| Startup and resources | `collector_settings.py` reads supported file and environment settings into one read-only snapshot. Server construction validates concurrency limits. Explicit settings control trace content and voice mode. | `test_portability.py`, `test_raw_trace.py`, `test_settings_file_encoding.py` |
| Interview decisions | `interview_stop.py` owns participant stop detection and its shared browser patterns. It can evaluate a transcript without loading the server. Evidence and coverage rules live in `capture_facts.py` and `interview_coverage.py`. Fact creation accepts an identity and clock source so a correction can be replayed with its original metadata. | `test_capture_facts.py`, `test_live_stop_parity.py`, `test_live_notes_mid_answer.cjs`, `test_completion_boundary.py` |
| Provider access | `OpenAIClient` delegates authenticated HTTP exchanges to `openai_transport.py`. The transport owns the destination, redirect policy, proxy discovery, cancellation and response lifetime. Provider-independent tests can supply an in-memory exchange. The knowledge worker uses the provider's structured-analysis operation and advertised readiness. | `test_provider_transport.py`, `test_provider_cancellation.py`, `test_provider_key_boundary.py`, `test_knowledge_api.py` |
| Recovery and filing | `recovery_store.py` owns consent, record validation, cross-process locking and atomic file replacement. `KnowledgeGraph` owns the SQLite filing transaction and preserves earlier revisions and review history. Authorization uses the exact principal supplied by the trusted integration. | `test_recovery_copy.py`, `test_knowledge_immutability.py`, `test_store_format.py`, `test_release_compatibility.py` |
| Document readers | The desktop process and its isolated parser workers use the pinned PDF reader. The app verifies the bundled wheel before loading it as a fallback. A caller that already loaded a different pypdf version delegates PDF reads and page exports to a clean child. | `test_pdf_reader_delivery.py`, `test_document_readers.py`, `test_document_parser_process.py` |
| Desktop lifecycle | `NativeHost.cs` owns WebView2 and Windows interactions. `HostLogic.cs` owns the decisions the shell can make without either. Build approval and supported data formats are checked by `desktop/manage.py`. | `test_desktop_host_logic.py`, `test_desktop_manager.py`, `test_desktop_updates.py` |

## Scope of the architecture review

The supplied engineering policy README identifies profile 1.6.1. Its authority manifest records provenance and the pending regulatory framework. The AGENTS template informed the concrete commands and owners in the repository instructions. The archive's Claude settings are client configuration.

- **Application structure.** The logical architecture, physical architecture, Python guide, C# guide, and architecture-testability rules govern ownership, dependency direction and tests. Core Additions informed the decision index. Platform-Specific Guidance covers hosted Azure triggers, identity, observability and deployment. The C# component here targets the installed Windows .NET Framework toolchain.
- **Testing and delivery.** TESTING, the enterprise TDD policy, test taxonomy, quality-risk profile, Python and .NET test profiles, security verification, CI quality gates and exception process were reviewed against the Windows release. Storage, authentication and provider changes carry Tier 3 risk. Offline behavioral tests cover invalid input, real persistence and authorization, cancellation and restart. The repository uses unittest, compiled C# console checks and Node's test harness. A passing desktop run establishes behavior only for the paths, toolchains and adapters it exercises.
- **Financial data and audit.** The financial-domain standard applies to posting or modeling accounting transactions. This application records descriptions of work, source files and evidence. A filed revision is a business record with local history. An administrator with direct access to the SQLite file can alter it. The audit-trail profile's separate protected writer, verified identity, independent retention and tamper evidence would be required for regulated use. Classification of uploaded material, the legal framework and retention approval belong to the data owner and Compliance.

The checks above implement the boundary and transaction controls (AS-021, AS-035, AS-043, ARC-013), data-integrity verification (QR-004, QR-005), and release gates (CI-001 through CI-003, SEC-020 and SEC-021). The hosted controls in the physical architecture and the audit profile's protected storage and retention requirements need evidence from their own environments.

## Release implications

Opening company knowledge upgrades it to format 3. Earlier builds supporting up to format 2 refuse that database. Operators who need the option to return to an earlier build should keep a pre-upgrade backup. [Desktop data compatibility](../DESKTOP.md)

The desktop API still contains prompt orchestration and some domain validation. In-process jobs, caches and worker limits assume one desktop instance per workspace. Hosted scale-out and regulated audit acceptance require additional implementation and independent verification. The repository records no approval to use a local database as a regulated audit store.
