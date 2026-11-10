# Process Collector working location

This is the canonical editable checkout: `C:\Users\amelas\Documents\Process Collector`.

- Make all source edits here. Save local work, validation output and app data inside this project.
- Do not edit or launch the earlier scratch checkout under `Documents\Codex\2026-11-03\pull-the-latest-repo-from-the\ai-process-collector`.
- GitHub origin is `https://github.com/amelas-dev/ai-process-collector.git`; the upstream branch is `main`.
- Preserve `.env.local`, `.local/` and `work/`. They contain private settings, saved work and databases; keep them out of Git.
- Reuse the existing compatible Python runtime at `C:\Users\amelas\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`. Do not copy or install another runtime.
- Launch this checkout's `launcher.py` with that interpreter and `-I -B --no-browser`; preview is `http://127.0.0.1:8774/`.
- For Codex-managed previews, add `--foreground` and keep the returned execution session running. Background children of a completed tool job may be terminated by Windows job cleanup. Ordinary desktop launchers retain their existing behavior.
- Follow the computer's utility resource preflight policy before any dependency or resource acquisition.
