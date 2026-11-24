# Process Collector working location

The canonical editable checkout on this computer is the Process Collector folder in the current user’s Documents directory.

- Make all source edits here. Save local work, validation output and app data inside this project.
- Use the canonical Documents checkout for normal launches. Run integration tests in an isolated work directory.
- GitHub origin is `https://github.com/amelas-dev/ai-process-collector.git`; the upstream branch is `main`.
- Preserve `.env.local`, `.local/` and `work/`. They contain private settings, saved work and databases; keep them out of Git.
- Reuse the existing compatible Python runtime at `%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`. Do not copy or install another runtime.
- Launch this checkout's `launcher.py` with that interpreter and `-I -B --no-browser`; preview is `http://127.0.0.1:8774/`.
- For Codex-managed previews, add `--foreground` and keep the returned execution session running. Background children of a completed tool job may be terminated by Windows job cleanup. Ordinary desktop launchers retain their existing behavior.
- Follow the computer's utility resource preflight policy before any dependency or resource acquisition.

## Architecture and verification

The application uses Python for the API and JavaScript for the interview page. Before changing a component listed in the [architecture decision index](docs/adr/README.md), read its decision. Update the decision and its tests when ownership, configuration precedence, or persistence compatibility changes.

- Keep interview rules independent of HTTP, provider credentials and local storage. Inject the provider or its transport when testing application behavior.
- Use real temporary SQLite databases for changes to filing and ownership. Cover reopening, failed writes, retries, and prior store formats. These changes carry Tier 3 data-integrity or access-control risk.
- On Windows, from an isolated checkout with the project interpreter, run `python -X utf8 -I -B -m unittest discover -s tests -p "test_*.py"` and `node tests/run_all.cjs`. Use the interpreter path specified above. The suite includes socket-free unit cases, loopback API and SQLite integration, and parser subprocesses.
- The Azure implementation has its own deployment boundary. Keep the local listener on loopback. Hosted identity, storage, access control and provider integration require validation in the hosting project.
- Run `python -I -B tests/check_release_inputs.py credentials` to check the Git index for private state and recognizable credentials. Run `python -I -B tests/check_release_inputs.py dependencies` with the authenticated GitHub CLI to check the exact document-reader pins for active, reviewed high- or critical-severity advisories.
