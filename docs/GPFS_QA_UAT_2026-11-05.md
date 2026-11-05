# QA and UAT review — November 5, 2026

Historical **0.26.0** evidence. The subsequent Capital Calls test exposed sustained
conversation failures that these short trials did not cover. Current behavior and
the repair validation are in [the 0.26.1 review](CONVERSATION_REPAIR_QA_2026-11-05.md).

Status: implemented; automated QA passed; agent-led UAT exercised; human acceptance pending.

All retained evidence is in `work/gpfs-intelligence/`. Test transcripts and documents
created for this review are fictional. No private saved employee/client account was
used in provider trials. Existing private configuration and app stores were preserved.

## Automated verification

- The final full Python suite passed **654 tests**, including the final compatibility
  guard. The full result is recorded in `python-qa-final-complete.txt`.
- All 21 JavaScript suites passed (`javascript-qa-verified.txt` and
  `javascript-qa.json`), including the new metadata preservation/export suite.
- Guards cover sixteen-topic alignment, old-file migration, completion revocation,
  tag correction and omission preservation, edited-source retirement, unauthorized
  citations, controlled taxonomy values, gold-standard corroboration and graph enums.
- Existing source, document authorization, workflow correction, completion, voice,
  concurrency, retry, portability and local API tests remain included.

## Browser rehearsal

Used existing Playwright 1.62.1 with installed Chrome 156.0.8078.80, on this Windows
host. No browser, environment or package was downloaded.

1. Opened a fresh application and verified sixteen visible topic controls.
2. Opened the complete fictional example and its report; checked the five new memo
   sections and the classification/dependency section.
3. Saved and reopened the interview. Sixteen topics, eleven steps, three taxonomy
   records and two dependencies survived; participant confirmation reopened as false.
4. Checked the report at 1440 × 1000 and 390 × 844. No page errors or horizontal
   page overflow were observed. Review tabs retain their existing horizontal scroll.

Evidence: `browser-qa.json`, saved/reopened example JSON and the inspected
`browser-initial.png`, `browser-report-desktop.png`, `browser-report-mobile.png`.
This is a functional/layout rehearsal, not accessibility certification.

## Actual-provider interview and output rehearsal

Three invented domains exercised six adaptive opening questions each: capital-call
journal entries, a ManCo fee calculation, and enterprise HR/IT access. Repeated
passes retained every result. Early passes exposed bundled scope questions,
repeated input-readiness probes and rephrased unknown-standard questions. Shared
phase priority, explicit parking rules and the spoken role were tightened.

The final HR recheck established applicability, parked unknown standard status,
established start, parent and finish/consumer, then offered a scope/boundary recap.
Some requests still bundle closely related information, such as finish and consumer.
The one-request contract remains a conversational quality limit, not a guarantee.

A longer fictional capital-call source replay produced a sixteen-topic capture and
a validated seven-step draft. The draft retained rule provenance, structural GP
fee-waiver treatment, fund/feeder applicability, upstream notice preparation,
Treasury input, re-keying, approval levels, open balances and a parallel feeder lead.
It preserved unknown thresholds, review objectives and missing transitions as gaps.
In particular, it did not invent the preparation-to-review handoff or cash-difference
return route. The manager's objective remains uncertain; the output does not declare
the second approval redundant. Unreviewed LPA/side-letter mentions remain reported.

An initial draft failed an unsupported taxonomy-value guard. The corrected schema
constrains values per facet at generation time; the repeated full capture/draft
completed without errors. Evidence: `provider-uat.json` (retained initial failure),
`provider-uat-v2.json` (successful artifact run), `provider-openings-final.json`,
and `provider-hr-recheck.json`.

## Actual GPT-Live/WebRTC rehearsal

Reused the existing fictional invoice WAV and bounded local probe code. Audio was
fed through a synthetic browser microphone and physical output was muted.

Early spoken trials still asked about invoice mechanics before entity scope.
The spoken role now explicitly prioritizes the missing scope and omits the full
background coverage table while retaining the shared selection policy. Two final
sessions (07 and 08) both asked: “Which entities or part of GPFS does this invoice
work serve?” No errors were recorded in those two sessions. They used gpt-live-1
with the existing live-front/WebRTC architecture. No extra synchronous next-question
request was introduced.

Two earlier starts did not produce the greeting before the probe stopped, and
reported context-injection errors when the session closed. Those failed attempts
are retained as `live-trial-05.json` and `live-trial-06.json`. A separate probe
navigation error is retained in `live-qa-verified.txt`. Final receipts are
`live-trial-07.json`, `live-trial-08.json`, `live-qa-verified-v2.txt`. Short successful
trials do not establish startup reliability or latency guarantees.

## Acceptance limits

- Physical microphone, speakers, interruption feel and sustained real interviews
  require a human test. Agent-led rehearsal is not participant or owner sign-off.
- Classification and relationship semantics still need review. A valid citation ID
  does not prove the interpretation; no generated tag establishes legal authority,
  control effectiveness, an approved standard, redundant review or unnecessary work.
- Existing saved interviews are not backfilled with invented GPFS facts. Their new
  fields remain unknown until the existing evidence or a follow-up supports them.
- Startup failures and occasional bundled questions remain visible in the evidence;
  there is no claim of perfect questioning or general release certification.

The existing runtime paths, resource receipt and verification outcomes are recorded
in `runtime-reuse.json`; the local resource preflight passed.
