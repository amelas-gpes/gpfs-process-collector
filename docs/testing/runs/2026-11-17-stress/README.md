# Stress run, November 17, 2026

Thirty distinct processes from the [process library](../../process-library/README.md) were run against Process Collector at commit `04e6ee3` (0.32.0 plus the unreleased fixes) to measure how fast each part of the experience is and whether accuracy holds. The diagram is the weak point: it was missing at the end of 14 of 27 scripted interviews and almost never appeared while the participant was still answering. Questions, voice replies, transcription, notes and small file reads were fast or accurate.

This folder is a record. A new test does not need it; use it as a baseline or to replay a case. The planned work that came out of it is the [diagram enhancement brief](../../../enhancements/diagram-speed-and-layout.md).

## What was run

| Cases | Mode | Variation |
| --- | --- | --- |
| T01–T13 | Typed | Full in one answer, step by step with branches, vague, partial (middle only, start only), out of order with a correction, vague then detailed, patient, exception-focused, conceptual, rambling, terse |
| F01–F10 | Files | 85-page PDF, 7-page and 1-page PDF, full CSV, three-row CSV, multi-sheet XLSX with a hidden sheet, PNG image, scanned PDF, two files at once, a file added mid-interview |
| V01–V04 | Recorded voice | Detailed, vague, a two-minute monologue, fast and jargon-heavy |
| V05–V07 | Live voice in a browser | Full, partial, vague; synthetic speech fed in as the microphone |
| STRESS-* | Typed | Five interviews at once on one server |
| A-*, B-*, C-* | Typed replay | Unmodified app, prototype, prototype with a different audit model, on identical answers |

Participants were scripted agents answering from the library and leaving open what it marks unresolved. The real provider was used, in isolated copies of the app, one interview per server unless stated. Voice used a synthetic macOS voice.

## Results

| Area | Result |
| --- | --- |
| Next question, typed | 2.1 s median, 3.1 s p90, 5.2 s max (129 answers) |
| Live voice reply | 1.0–2.3 s after the speaker stops; captions begin about 1 s into speech |
| Transcription | 1.8 s median; 129 s of audio in 5.6 s; word error 0–7% |
| Notes after an answer | 31 s median, 42 s p90 |
| Diagram before the next answer | 7 of 139 answers |
| Final diagram after Wrap up | 13 succeeded (215 s median wait), 14 failed |
| Small files | First question 7–24 s after choosing the file |
| 85-page text PDF | Text read in 3.2 s, first question at 161 s |
| Live voice diagram | 100–318 s after the last spoken answer |
| Five interviews on one server | Three had no diagram nine minutes after Wrap up; Wrap up up to 127 s |

Participant-scored accuracy: notes 4.1 of 5, questions 3.7 of 5. Of the 14 final maps, 6 had a start node, 1 an end node, 9 were one connected flow and 12 had branches leaving an ordinary activity box.

## Findings

1. A new answer cancels the map being drawn (65 cancellations), and the cancelled request keeps the only map slot until the provider returns.
2. The map's source audit takes longer than drawing it (112 s median against 41 s) and re-sends about 89% of the steps it is checking.
3. The 14 failed maps were mostly audit and draw timeouts; a long first answer can also hit the 12,000-token draw limit.
4. One map worker serves every interview on a server.
5. Live voice starts a map one second after the first words, from a partial sentence.
6. File review is serial and the first question waits for all of it.
7. Diagrams lack start and end nodes, draw decisions as activity boxes and leave exceptions as dead ends. This follows from the evidence-first prompts and a renderer that draws the evidence graph literally.
8. Most note captures run on the slower model (127 of 163).
9. The live interviewer is not gated and once asked three questions in one turn about a step the speaker had said they did not know.
10. Transcription slips on a few terms: "so OFAC" as "SOFAC", "Signatory A" losing its letter, "Passthrough" as "PassThru".

## Prototype replay

`prototype.diff` was never applied to the app. It keeps the in-flight map instead of cancelling it and shows the drawn map while its audit runs.

| | Unmodified | Prototype |
| --- | --- | --- |
| First diagram visible | Never during the interview | 34–67 s after the first answer in 4 of 5 runs, 223 s in one |
| Final diagram | 1 of 3 | 4 of 5 |

Blind judges scored fidelity 6–8 of 10 in both arms. One prototype map carried 16–20 of 28 stated steps where the unmodified map carried all 28.

## Files

| File | Contents |
| --- | --- |
| `cases/` | One JSON per interview: context, transcript, every timed event, final notes, final map and graph checks. Session tokens are removed. |
| `timings.json` | Per-case question, notes, map, Wrap up and file timings. |
| `stages.json` | Every model call with stage, model, duration and token counts, and map worker events. |
| `evals.json` | Each participant's evaluation of its own case: map, notes and question defects, file handling, transcription slips, waits observed. |
| `judges.json` | Two blind judgements for each of six replay maps. |
| `live_scripts.json` | The spoken answers used for V05–V07. |
| `prototype.diff` | The unapplied prototype, against `04e6ee3`. |
| `V05-live-voice-final-map.jpg` | The rendered diagram from the full live-voice case. |

Replay a case with the [harness](../../harness/README.md): `replay.py 45 TAG T01@PORT`.
