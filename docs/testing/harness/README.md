# Participant harness

Scripts used for the [2026-11-17 stress run](../runs/2026-11-17-stress/README.md) and extended for the [final stress run](../runs/2026-11-17-final-stress/README.md). They talk to the app over its local HTTP interface exactly as the browser does, and record how long each thing a participant waits for takes. They need the project's Python 3.12 and, for voice, macOS `say` and `afconvert`.

Copy this folder to a scratch directory as `lib/`. Case state is written to a `cases/` folder beside it, logs to `logs/`. Set `PC_REPO` to the checkout and, when the scratch directory is inside the checkout's `work/` folder, `PC_SCRATCH` to a folder outside it for the isolated copies. Always point the scripts at an **isolated copy** of the app on its own port, never the working checkout.

| Script | What it does |
| --- | --- |
| `serve.py ENVFILE APPDIR PORT [KEY=VALUE ...]` | Starts an isolated copy of the app with the settings in `ENVFILE` passed as environment and content-level event logging on. Extra `KEY=VALUE` pairs override settings for an experiment. |
| `pc.py` | Plays a participant: `start CASE --port P --name "..."`, `answer CASE "text" [--file PATH] [--voice] [--think S]`, `skip CASE`, `upload CASE FILE...`, `wrap CASE`, `waitmap CASE`, `prepare CASE` (the draft's first half, as the page asks for it when the participant wraps up), `draft CASE` (Review, Create draft), `report CASE` (transcript, timings, notes, map and draft on one page), `show CASE`, `timings CASE`, and `live CASE --source OTHER --port P` (replays a finished case through the routes the page calls after each spoken answer in Live voice). |
| `rig.py up N... [--fresh]`, `down N...`, `status` | Copies the checkout to `copies/app-N` under `PC_SCRATCH` and serves it on port 8800+N with the checkout's settings as environment; stops only servers it started. `RIG_SRC=<tree>` serves another source tree, for example a patched clone. |
| `clone_case.py SRC NEW PORT` | Copies a finished case so that its draft can be requested again from another server (`prepare NEW`, `draft NEW`). |
| `scripted.py CASE PORT PROCESS STYLE` | A participant without an agent: narrates section 8 of a library process (`narrate`, `voice`, `unknown`, `early`, `file_mid`, `file_only`, `file_contradict`) or replays a list of answers (`answers --answers FILE`), then runs Wrap up, Create draft and the report. Needs `text/` from `mktext.py`. |
| `score.py table`, `questions`, `loss`, `json` | Scores cases from their files: timings and map shape, every interviewer question in order, and names and numbers from the answers that appear in none of notes, map and draft. |
| `stage_times.py [--calls] N...` | Per-stage model timings and worker events from the copies `rig.py` made. |
| `runtests.py SRC LABEL` | Copies a source tree to scratch and runs every Python and Node suite there, with one JSON summary. |
| `mktext.py PROCESSES.json OUT` | Per-process text files and an index from `slice.py`'s output. |
| `replay.py THINK TAG CASE@PORT ...` | Replays the answers of finished cases at fixed pacing. Use it for before/after comparisons so the answers are identical. |
| `stages.py SCRATCH` | Per-stage model timings and map worker events from each copy's `work/raw-trace`. |
| `agg.py`, `arms.py` | Tabulate cases and replay arms. Written for one run; adjust the paths at the top. |
| `mkpdf.py`, `mkfile.py` | Cut library pages into a PDF; build a CSV or XLSX from a JSON spec. |
| `extract.py`, `toc.py`, `slice.py` | Turn the process library into per-process text. |
| `shim.js` | Pasted into the page in a browser to feed recorded speech in as the microphone for live voice, and to time captions, replies, notes and map requests. The audio must be served from the app's own origin, which needs a test-only addition to the isolated copy's static file table. Never add that to the real app. |

Runs against the real provider cost money. A typed interview of six answers makes about six question calls, six note captures and several map calls; Create draft adds two large calls. A scripted participant costs nothing beyond that. An agent participant reads the process and judges each question, which is the only way to grade questions, but twenty of them at once used up a whole usage window in the final run: start a few at a time.
