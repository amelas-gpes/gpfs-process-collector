# Live testing

Three things live here. A new test needs the first two. The third is history.

| Folder | What it is | Use it when |
| --- | --- | --- |
| [process-library](process-library/README.md) | The written business processes used as the source of truth: 43 processes, 2,020 pages. | Always. Participants answer from it and results are checked against it. |
| [harness](harness/README.md) | Scripts that play a participant against an isolated copy of the app and read its timings. | You want to run interviews, uploads or voice without clicking through the app. |
| [runs](runs/) | One dated folder per past test run, each with its own README, inputs and results. | You want a baseline to compare against, or a saved case to replay. |

## Starting a new test

1. Pick processes from the library. Nothing in `runs/` has to be read first.
2. Run against an isolated copy of the app, never the working checkout or its `work/` folder.
3. Save the results as a new folder `runs/YYYY-MM-DD-short-name/` with a README that states the app commit, what was run, the numbers and the findings. Do not edit an earlier run's folder; link to it.

## Past runs

| Run | App commit | What it covered | Outcome |
| --- | --- | --- | --- |
| [2026-11-16 process capture](runs/2026-11-16-process-capture/README.md) | `eb80ffb` | 21 typed interviews and 10 upload variants | Thirteen findings, fixed in the following release. Its interviews and upload inputs are fixtures for several regression suites in `tests/`, so keep the folder where it is. |
| [2026-11-17 stress](runs/2026-11-17-stress/README.md) | `04e6ee3` | 30 processes across typed, file, recorded-voice and live-voice interviews, plus concurrency and a prototype replay | Questions, voice and small files are fast; the diagram is slow and often missing. Led to the [diagram enhancement brief](../enhancements/diagram-speed-and-layout.md). |
| [2026-11-17 map lanes](runs/2026-11-17-map-lanes/README.md) | first part of the diagram brief | Stand-in providers only: scheduling, cancellation, the difference a check reviews, and thirteen saved maps through the new rules | A map on screen after every answer and none cancelled in simulation. Timings and fidelity with the AI service are not measured. |
| [2026-11-17 diagram review](runs/2026-11-17-diagram-review/README.md) | `b71f6fc` and the review fixes | Interview scheduling, late page updates, and exports of 22 recorded maps | The page retained a late diagram after a notes failure. All 378 exported connections started on their reported routes. |
| [2026-11-17 final stress](runs/2026-11-17-final-stress/README.md) | `dde4da1`, then two rounds of fixes | 34 library processes and the built-in example across typed, file, recorded-voice and simulated live-voice interviews, each through Wrap up and Create draft, plus five at once and the browser | No answer lost and questions in about 3 s. Nine defects fixed in the first round, among them drafts that failed for long interviews and for a file alone; the eleven things left open were closed in the second. Create draft is ready about a minute and a half after the click when started after Wrap up. |

Findings that became planned work are in [docs/enhancements](../enhancements/README.md). Release archives leave this whole folder out.
