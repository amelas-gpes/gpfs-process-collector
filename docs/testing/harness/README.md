# Participant harness

Scripts used for the [2026-11-17 stress run](../runs/2026-11-17-stress/README.md). They talk to the app over its local HTTP interface exactly as the browser does, and record how long each thing a participant waits for takes. They need the project's Python 3.12 and, for voice, macOS `say` and `afconvert`.

Copy this folder to a scratch directory as `lib/`. Case state is written to a `cases/` folder beside it. Always point them at an **isolated copy** of the app on its own port, never the working checkout.

| Script | What it does |
| --- | --- |
| `serve.py ENVFILE APPDIR PORT [KEY=VALUE ...]` | Starts an isolated copy of the app with the settings in `ENVFILE` passed as environment and content-level event logging on. Extra `KEY=VALUE` pairs override settings for an experiment. |
| `pc.py` | Plays a participant: `start CASE --port P --name "..."`, `answer CASE "text" [--voice] [--think S]`, `skip CASE`, `upload CASE FILE...`, `wrap CASE`, `waitmap CASE`, `show CASE`, `timings CASE`. |
| `replay.py THINK TAG CASE@PORT ...` | Replays the answers of finished cases at fixed pacing. Use it for before/after comparisons so the answers are identical. |
| `stages.py SCRATCH` | Per-stage model timings and map worker events from each copy's `work/raw-trace`. |
| `agg.py`, `arms.py` | Tabulate cases and replay arms. Written for one run; adjust the paths at the top. |
| `mkpdf.py`, `mkfile.py` | Cut library pages into a PDF; build a CSV or XLSX from a JSON spec. |
| `extract.py`, `toc.py`, `slice.py` | Turn the process library into per-process text. |
| `shim.js` | Pasted into the page in a browser to feed recorded speech in as the microphone for live voice, and to time captions, replies, notes and map requests. The audio must be served from the app's own origin, which needs a test-only addition to the isolated copy's static file table. Never add that to the real app. |

Runs against the real provider cost money. A typed interview of six answers makes about six question calls, six note captures and several map calls.
