# Process capture regression cases

On November 16, 2026, Process Collector 0.32.0 returned a typed question in a median of 3.4 seconds. The clearest accuracy failure occurred after the interview. The carry-vesting notes correctly recorded that selecting Method B puts work on hold, but the published diagram included a path from the start to calculation and release that bypassed method selection. File uploads also exposed a long wait between reading the file and asking a useful question.

## Test baseline

| Participant action | Observed result |
| --- | --- |
| Answer a typed question | All 104 timed interview HTTP requests returned a question. Median 3.4 s, p95 6.9 s, maximum 8.2 s. The 18 rendered browser answers had a 2.7 s median and 5.0 s p95. |
| Get a question from a file | Ten variants covered six processes. Six produced a question unaided, two required intervention, and two failed to produce one. All eight delivered questions addressed a genuine gap. Among those eight, median file-selection-to-question time was 120.8 s, with a range of 45.3–454.7 s including retries and intervention. |
| Review the latest answers | All 17 HTTP interviews produced notes for their final answer revision. Three initial maps for that revision succeeded and 14 ended in error. One failed map subsequently appeared after Wrap up had already timed out. |
| Save and reopen | All 21 packaged interview files reopened in the app. The FA-17 browser session also produced a partial draft and an isolated revision-one pending submission receipt. Its Wrap up took 188.1 s and its draft request took 262.8 s. |

The 21 conversations covered 20 distinct processes and 122 source-grounded participant answers. Two testers independently exercised FA-11. Testers played the participant from the September 2026 process library and explicitly left undocumented details open. The saved files record this provenance and carry no process-owner approval. The source contains 43 processes across 2,020 pages. [Source process library](source/IP1-export.pdf) · [Interview files](interviews/) · [Source pages for each participant answer](interviews/source-pages.json)

The baseline used the real provider and production app paths at commit `eb80ffb` in isolated local stores. The lead interviewer used `gpt-6-luna` and process and document review used `gpt-6.1-terra`. At most two foreground requests overlapped per HTTP interview listener. Background jobs could queue, and separate listeners shared a machine and provider account. Uploads ran sequentially on each document listener in fresh browser contexts. The results describe this workload. Scope covered typed English exchanges, PDF and CSV intake, and browser interactions.

## Replay a case

Use a Git clone or download individual files from this directory on GitHub. Desktop release archives omit this testing corpus.

1. **Inspect the baseline.** Download an interview JSON and open it with **Menu → Open saved interview…**. Compare its Notes, structured connections and Workflow with the cited pages. Reopened coverage is provisional. The saved wording lets reviewers identify exactly which answer or map route produced a finding. [Interview files](interviews/) · [Answer-to-page index](interviews/source-pages.json)
2. **Test the interviewer again.** Start a fresh interview for the same process in an isolated test workspace. Answer each new question using the cited source pages. If the source leaves a detail unresolved, say so. Preserve the generated replies even when they differ from the prior conversation. Measure from sending an answer to receiving the next question, then check notes and map status independently. [Source process library](source/IP1-export.pdf)
3. **Test document intake.** Start a fresh process for each U1–U10 case and use **Assets → Add files** to upload its input. Keep the evaluator's answer key outside the interview. Record file selection, review, accepted map and first visible question separately. Compare the question with the supplied facts and the deliberately withheld facts. For a failed attempt, record elapsed time, visible error and retry outcome. [Upload inputs](uploads/inputs/) · [Answer key](uploads/answer-key.json)
4. **Compare results.** Use the acceptance checks below to distinguish a fixed defect from different model wording. Report time to a useful question, failures, and any manual intervention. Compute successful-case latency separately from failure counts. [Original upload results](uploads/upload-results.csv) · [Provider stage timings](uploads/provider-stages.csv)

## Findings and acceptance checks

### High priority

| # | Finding and evidence | Acceptance check |
| --- | --- | --- |
| 1 | **File review can finish while the browser stays on “Reading your files.”** On U1 polling stopped at 2.95 s. The server had reviewed eight sections by about 50 s, but the browser still showed the reading state at 339.9 s. A 374-byte CSV reproduced the race in U7. Exercising the visible-tab handler resumed progress. | Keep polling when extraction has returned a result and review has yet to report a phase. If review finishes between polls, a continuously visible tab advances to the baseline without intervention. |
| 2 | **A map can bypass a mandatory hold or disconnect a required check.** The GP-03 interview map took S1 → S2 → S6 toward calculation without traversing method selection S3 or decision S4. FA-20 left identity validation and ownership tracing disconnected. FA-04 placed legal clearance outside the route despite an explicit release block. | Verify reachability against cited prerequisites before publishing. Every GP-03 path to calculation passes through method selection, Method B ends in hold, and FA-20 connects the stated identity-to-screening sequence. |
| 3 | **A failed or queued map can block Wrap up for five minutes.** GP-03, MC-04 and FA-07 each returned HTTP 504 at 300 s while notes were available. FA-07 returned HTTP 502 after another 126 s on retry. | Make synchronized notes available for review while the map has its own status and retry. Exercise both a single session and overlapping sessions. A map failure must preserve the transcript and notes. |
| 4 | **Mapping and audit delay the first useful file question.** On U3 a 265-byte input reached baseline building at 4.9 s and the first question at 56.1 s. U2 took 8.2 s and 125.9 s respectively. U4 took 454.7 s including a retry. | Ask a provisional, source-grounded question when the file establishes a gap and complete the audited map in the background. Proposed targets on a one-page text fixture are upload acknowledgement within one second and a usable question within 15 s at p95. Check stale results after a new answer or file change. |
| 5 | **The participant is asked to resolve a model-generated citation error.** On the second U1 upload, map validation rejected a generated operating detail at 136.4 s. A retry failed its citation check at 233.3 s. Neither attempt delivered a follow-up. | Force an invalid generated citation on the same file. Repair or drop the unsupported detail internally, keep the file attached, and ask a question grounded in a verified excerpt. |

### Medium priority

| # | Finding and evidence | Acceptance check |
| --- | --- | --- |
| 6 | **A successful map retry leaves an old timeout visible.** In Edge, the FA-11 retry finished in 70.9 s. Workflow showed “Up to date” and the save marked notes and map current, while Notes still displayed the timeout. | After a successful retry, both panels show the state of the accepted revision. Prior failures belong in history. |
| 7 | **Follow-ups revisit an answer or a stated unknown.** FA-07 asked for the Team Lead approval record immediately after the participant said its form was unconfirmed. FA-17 asked what followed settlement just after the participant had described filing and AFC sign-off. | Before asking, compare the proposed question with recent answers and known unknowns, including turns awaiting capture. Target a genuinely different gap or identify the precise detail still missing. |
| 8 | **One panel can call a fact unknown after another records it.** FA-17 listed the insufficient-funds handoff to FA-16 in structured connections, while its Connections note called it unknown. FA-07 recorded the AML and admission gates under Checks and Risks, while Rules still said governing requirements were unspecified. | Update each affected topic when new evidence arrives. Retain narrower uncertainties and retire the contradicted gap. |
| 9 | **Paraphrasing the same handoff creates duplicate links.** FA-20 produced two Compliance Officer escalations for overlapping unresolved-screening conditions after the participant described the handoff twice. | Merge the equivalent escalation and retain both citations. Preserve a separate route where the outcome genuinely differs. |
| 10 | **A question turns an artifact into a person.** FA-13 described binder support going to FA-15A. The next question treated binder support as a recipient that finished the binder after receiving the workbook. | Preserve the roles of supporting records and receiving process. Ask who handles the records if the actor is unclear. |
| 11 | **The interview goal appears as the operational purpose.** FA-15B and FA-20 included the goal of documenting the process in their business-purpose notes. | Change only the interview goal in a replay. The operating purpose should still describe the business result supported by participant evidence. |
| 12 | **Text pages can be flagged as unread graphics.** In U4 the app sent two text-rich pages for visual review. Inspection of the rendered pages showed ordinary legible instructions without a separate graphic to interpret. | Recognize text-only PDF forms on those two pages and avoid a false unread-graphic warning. An image-only control page should still trigger visual review. |
| 13 | **The Materials note misstates text coverage.** On U10, Assets reported indexed text on all 24 pages and the workflow received 48 of 48 sections. Materials called text coverage incomplete. Deep visual review had paused with 23 pages outstanding. | Expose indexed native text, excerpts supplied, deep-review progress and unread visuals as distinct facts. For U10, Assets and Materials must agree on 24 text pages, 48 supplied sections and the outstanding visual review. |

## Accuracy checks to retain

| Case | Source-grounded expectation for a rerun |
| --- | --- |
| FA-02 | A shared custodian name alone cannot resolve an ambiguous receipt. Keep it unidentified until the amount, remittance or transaction evidence supports attribution. |
| FA-12 | Retain the marked internal tie-out PDF in the binder and release the clean client-approved package. |
| FA-15B | An upload receipt alone does not close an auditor request. Capture auditor confirmation or a recorded authorized reason and the final reconciliation. |
| GP-05 | Check zero for each partner. Offsetting partner balances can make the vehicle total zero while leaving the wind-down incomplete. |
| MC-02B | Both AEA's quarter-close email and the saved Bilixio reports are prerequisites. |
| U3 and U8 | The one-action MC-04 input supports a question about what follows schedule review. The seven-stage excerpt supplies those stages. Verify the interviewer takes the richer evidence into account. |
| U10 | The complete GP-03 upload produced a 19-node map that preserved the Method B hold, net-zero points and effective-date schedules. Its follow-up correctly asked about the unconfirmed overall owner. The successful upload and the erroneous map from the separate GP-03 typed interview give two paths for testing the same rule. |

The final fund-accounting cases FA-11 and FA-15A, the cross-functional cases GP-05 and MC-02B, the fresh browser checks GP-02 and MC-01, and the final upload variants U7 and U9 added no further issue types in their respective test series. A future run should record new failures separately even if the overall timings improve.
