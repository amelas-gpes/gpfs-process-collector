# GPT-Live question selection — 0.25.1

The 0.25.0 merge retained GPT-Live's broad questioning, curiosity, correction and eleven-topic guidance, but the newer next-question selection policy remained inside the typed/reviewed-turn prompt builder. This was an implementation omission, not a measured latency tradeoff.

`QUESTION_SELECTION_POLICY` now supplies the same selection rules to typed turns, the GPT-Live session and its delegated backend. It prioritizes material unexplained mechanisms, retains volunteered branches, widens coverage when useful and checks for answered or unavailable information. The live prompt tells the interviewer to choose ordinary follow-ups directly, without waiting for notes or delegating just to select a question. Background suggestions must still fit the latest answer and selection policy. No API call, model change, transcription stage or synchronous review gate was added. The live instructions grew by 288 words, including the new selection and nonblocking guidance.

This uses the existing split between conversation and background work described in [OpenAI's GPT-Live prompting guidance](https://developers.openai.com/api/docs/guides/live-prompting). Prompt inclusion does not guarantee adherence, and this change does not claim a full prompt simplification.

## Real-provider comparison, November 4, 2026

Six fresh GPT-Live/WebRTC sessions replayed the same existing fictional 6.849-second WAV: receiving an invoice by email, saving its PDF and logging it before manager review. The order was baseline, candidate, candidate, baseline, baseline, candidate. Baseline was the already-running 0.25.0 server; candidate was an isolated 0.25.1 server using the canonical checkout and separate local stores. Both used `gpt-live-1` and the same voice/configuration.

Timing starts at the last 20 ms fixture window whose RMS exceeds 0.006 (5.920 seconds after fixture start) and ends at the first received reply-audio sample above that threshold. A Web Audio analyzer sampled output every 25 ms. The greeting finished before the answer started; received output was muted to physical speakers. These measure browser audio arrival, not physical playback or a real participant's microphone endpoint.

| Pair | Baseline | Updated prompt | Difference |
| --- | ---: | ---: | ---: |
| 1 | 2.080 s | 2.179 s | +0.099 s |
| 2 | 2.051 s | 2.378 s | +0.327 s |
| 3 | 2.807 s | 2.278 s | −0.529 s |
| Median by variant | 2.080 s | 2.278 s | +0.198 s |

The observed differences fit the requested allowance of roughly one second added delay. Three samples per prompt and one answer do not establish a reliable upper bound, zero added delay, or instant response. Provider, network and host variation remain. The earlier reviewed-turn timings are a different path and are not used for this comparison.

All six sessions used the direct live transport, with no transcription, reader-session or concurrent question-turn requests. The managed interview capture request began after reply audio arrived. No delegation events or browser errors were observed, and all synthetic microphone tracks ended when stopped. Metadata and fictional results are retained locally under `work/live-prompt-2026-11-04/`; private settings and the saved participant interview are excluded from Git.

Question quality remains imperfect: one updated-prompt sample repeated the email-arrival trigger; two asked about readiness for manager review but presupposed a check during logging. Baseline samples also repeated triggers or bundled requests. This is evidence of prompt delivery and bounded sample latency, not consistent semantic accuracy or sustained interview acceptance.

## Regression validation

- 643 Python tests passed on the final full run, including actual live-session payload checks for shared selection guidance, the unchanged live model, one provider request and no typed JSON response contract in spoken instructions.
- 61 JavaScript checks passed across the live-voice and concurrent-app suites.
- The first full run had one Windows socket-abort error in an upload-rejection test. All 13 document API tests passed on immediate rerun, followed by the successful full run; no unrelated upload code was changed.
- Existing Python 3.12.14 and Node 24.22.1 runtimes were reused; the scoped core preflight passed. No packages, runtimes or browser resources were acquired.
