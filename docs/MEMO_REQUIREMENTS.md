# Memo requirements and acceptance criteria

This document translates a September 2026 process-capture memorandum into requirements for AI Process Collector. The original memorandum stays local. The application uses the GPFS assets documented in GPFS_ASSET.md. The original source is retained locally; its SHA-256 is `7ad850f29c6eab8e5224aa423321c9d507c5af1c7ed2535498e65db697407622`.

The memo defines the process-capture foundation. The user separately requested a voice interviewer, adaptive follow-up questions, an editable process map and detailed procedure, an interview whose duration the participant controls, and selectable voices that sound more natural. Those additions are identified below; they must not turn the memo's honest first-pass capture into an invented future-state SOP.

`FOUNDATION.md` is the standing interview policy loaded for interview and draft-generation requests. This requirements document is the review and acceptance reference. It is not evidence that every conversational requirement has been demonstrated reliably.

## 1. All eleven memo topics

Every capture must contain an answer or an explicit gap for each topic. `UNKNOWN` or `TBD` is a recorded gap, not proof that the topic is fully understood. `Not applicable` needs a participant-supported reason. The interviewer gathers these answers through a natural conversation rather than reading the eleven source questions in order.

| ID / schema key | Required capture | Acceptance criterion |
| --- | --- | --- |
| M01 · `name` | The everyday process name and other names used by colleagues, checklists or systems. | Preserve meaningful aliases and distinctions. Do not merge different work merely because its names sound similar. |
| M02 · `purpose` | One sentence stating what the client or firm has at the end that it did not have at the start. | Describe the business result. The interview's objective is not evidence of the process's purpose. |
| M03 · `trigger` | The specific initiating event, normal cadence and any deadline that cannot move. | Identify what actually starts work and how it is received or detected where known. Record deadlines and their stated basis without assuming an obligation has been independently verified. |
| M04 · `completion` | The observable condition showing the work is finished. | Distinguish a finished result from the last task someone happened to mention. Preserve unresolved completion criteria. |
| M05 · `accountable` | The role accountable for the overall result, or `TBD`. | Do not infer overall accountability from preparing, reviewing or approving a step. Do not appoint an owner when none genuinely exists. |
| M06 · `lifecycle` | The things that move through stages; each thing's stages, working/recording locations and handoffs. | Use the team's stage names. Identify what changes status, where work happens and where responsibility changes hands. An unknown sender, location or rejoin remains unknown. |
| M07 · `checks` | What must be checked or approved before release; preparer, reviewer, approver and retained proof. | Describe checks actually performed, release conditions and evidence kept. Merely mentioning a checklist or sample does not establish an operated control. |
| M08 · `variations` | Differences by client, fund, country, currency or system. | Capture the normal route once, then record only the differences, using the boundary tests and six fields in section 3. An empty list does not establish that no differences exist. |
| M09 · `pain_points` | Manual work, time-consuming activities, errors, rekeying and workarounds. | Preserve the participant's actual account. Mark rough effort as an estimate; do not infer measured savings or an approved improvement. |
| M10 · `risk` | The consequence if the work goes wrong. | Capture the stated effect on money, investors, clients, deadlines, regulation or internal operations. Do not invent a consequence or risk rating. |
| M11 · `materials` | Existing checklists, procedures, templates, sample outputs, screenshots, tickets and training notes. | Retain supplied locations or references. Distinguish material mentioned from material actually provided or reviewed. |

### Five additional GPFS topics

| ID / schema key | Required capture | Acceptance scenario |
| --- | --- | --- |
| M12 · `scope` | Include the stated entities and teams, period and process boundaries. | A participant names two funds in scope. Preserve both and flag any unstated exclusions. |
| M13 · `rules` | Capture who set a material rule, its source and treatment of exceptions. | A threshold comes from a template. Cite its source and leave its owner open if unknown. |
| M14 · `connections` | Identify named upstream or downstream work and its handoff. | A reviewer refers to another process. Keep the link as a lead until its identity is confirmed. |
| M15 · `data_systems` | Record inputs, source systems, entry and resulting records. | Preserve a distinction between a file's origin, manual entry and the system that receives it. |
| M16 · `volume` | Record frequency, range, effort and the basis of any estimate. | When volume varies across periods, preserve the stated range and qualifiers. |

Completion considers all sixteen topics. A participant may stop with unresolved topics and retain the partial interview.

## 2. Memo-wide rules

| ID | Requirement | Acceptance criterion |
| --- | --- | --- |
| MR01 | Describe today's actual practice. | No invented step, check, owner, system, location, stage, rule, timing or fact. Keep recommendations and future-state design out of the current-practice account. |
| MR02 | Capture one piece of recurring work. | Establish one start, accountable result and finished condition. If these point in different directions, flag the boundary instead of silently combining the work. |
| MR03 | Start with work the participant knows. | The participant need not learn new terminology, choose an architecture classification, name a system of record or data owner, or decide where work should live. |
| MR04 | Preserve gaps and disagreements. | Record uncertainty, differing team versions and who could clarify them. Do not reconcile accounts or pressure a participant to guess. |
| MR05 | Describe the normal route first. | Answer the memo topics for the normal way before detailing client-specific differences. If no common normal way exists, record that finding rather than inventing a standard. |
| MR06 | Keep supporting elements within their process. | Do not create separate process write-ups for a control, policy, system, template or report used within the work. If producing a report is itself the recurring work, it may be the captured process. |
| MR07 | Use plain language. | A new joiner can understand the write-up. Do not require hierarchy terms such as level, tier, domain or capability, or decide the architecture team's later mapping. |
| MR08 | Produce a concise first-pass memo. | Include all eleven headings and the five most important questions for the process owner. Aim for the source memo's two-page scope; Markdown export alone does not guarantee a rendered page count. |
| MR09 | Require knowledgeable review. | Outputs are drafts for someone who knows the work to correct. A polished document, referenced turn ID or participant's account is not independent verification. |

## 3. Branches, variations and possibly separate work

Apply the source memo's three boundary tests in this order:

1. Does the difference change the reason the work starts?
2. Does it change the person or role accountable for the result?
3. Does it change what counts as finished?

If any answer is yes, flag **POSSIBLY SEPARATE WORK** and identify the changed boundary. Do not make the final classification. If all three answers are no, the work can be captured as a variation. If a boundary is unknown, retain the uncertainty and record any resolver or source the participant volunteers.

| Situation | Required treatment |
| --- | --- |
| It can happen for everyone, depending on the situation. | A normal branch in the main process. Capture its condition and known outcome or rejoin. |
| It applies to particular clients, funds, countries, currencies or systems and reaches the same result with the same boundaries. | A variation. Record only what differs from the normal route. |
| Extra work is performed for a particular client. | Record and flag the difference; do not assume it is contracted, uncontracted, charged or uncharged. Apply the boundary tests. |
| Start, accountability or finished result differs. | Flag possibly separate work, with the reason, rather than forcing it into the normal route. |
| There is no common normal route. | Record that finding and preserve the known versions. Do not fabricate a standard. |

Effort, a different system and the participant's feeling that the work is different are not substitutes for the three boundary tests.

For **each variation**, retain all six source fields, including explicit unknowns:

| Field | Acceptance criterion |
| --- | --- |
| Who it applies to | Name the known clients, funds, countries, currencies or systems. |
| What is different | State the exact added, removed, reordered or changed activity, check, timing or standard; reference the normal steps where possible. Do not rewrite the whole process. |
| Why it is different | Preserve the stated reason and any supporting material. `Nobody remembers` is a valid answer. A reported contract or regulatory reason is not a verified legal conclusion. |
| What it costs us | Record rough extra time, people, reviews, effort or deadline impact, identifying estimates as estimates. |
| Do we charge for it | Retain yes, no or unknown with only the details actually supplied. |
| Could it go away | Capture who would object, known constraints and the participant's view. Do not decide on removal or assume an unknown constraint does not exist. |

## 4. User-added interview and output requirements

**Scope in V1.** Three parts of these requirements are not in this version and stay on the `v2` branch: correcting a transcription before it is sent (U01; V1 has live voice and typed answers), editing the process map and the draft's steps (U05 is met by the diagram and the report, and U07 covers the fields that Review still lets you edit) and Preview of a voice before starting (U08; the voice is chosen in Settings and heard through question playback).

| ID | Requirement | Acceptance criterion |
| --- | --- | --- |
| U01 | Voice interview with an editable text alternative. | Ask questions aloud using the selected natural AI or installed computer voice when available. Record answers only after a user action; allow correction of the transcription before submission and allow typed answers. |
| U02 | Adaptive, natural elicitation. | Use each response to choose the next useful question. Distinguish a named step from an explained mechanism: deepen one useful missing condition, check, readiness signal or handoff before moving on when a reader would otherwise have to guess. Keep curiosity aligned with the eleven topics; do not invent alternatives, repeat answered or explicitly unavailable details, pursue trivia or ask several unrelated questions in one turn. |
| U03 | Return to the foundation instead of following endless tangents. | Maintain memo coverage, the normal route, specific step gaps and a parking list. After an explicit unknown, seek a clarifying person/material or record the gap and move on. Do not continue probing the same unknown indefinitely. |
| U04 | Flexible meeting duration. | Continue until the participant chooses to stop or confirms the final check. Version 0.9.0 retired the advisory timer. Disclose separate technical context limits and preserve a continuation path. |
| U05 | Clear process map and detailed procedure for review. | Show the known sequence, decisions, branches, responsibilities and locations. For each step include action, input, output, completion criterion and handoff where established. Name missing necessary detail so a reader does not silently fill it in. |
| U06 | Reach an explicit closing point. | Recap the account and gaps, invite corrections and ask a final omissions question. Follow up on additions. Mark confirmation pending until a participant replies; do not equate topic coverage, elapsed time or draft readiness with confirmation. Honour an explicit request to stop with gaps retained. |
| U07 | Save, restore and export the reviewable capture. | Preserve the interview and edits through an explicit session save/open operation. Export the concise memo separately from the full procedure appendix and map. Do not silently replace reviewed edits when regenerating. |
| U08 | Selectable, more natural question playback. | Provide selectable natural AI voices and Preview before starting, with explicit computer-voice selection if available. The development adapter currently offers ten voices with Marin as default and Cedar as an alternative; hosted choices must come from the selected Azure service. Keep persistent credentials server-side. Read the displayed question, withhold mismatched speech and allow Stop. Do not silently switch providers or voices, or claim human-level quality without evaluation. |
| U09 | Azure and developer-owned hosting. | Prepare for Microsoft Foundry voice/model services and the organization's managed AI application patterns. Keep interview rules and evidence contracts independent of providers. Deliver source, memo requirements, tests, configuration contracts and clear remaining integration work so developers can deploy and manage it. Azure support is pending until tested in the actual hosting environment. See [handoff](AZURE_HANDOFF.md). |
| U10 | Simple, clear monochrome interface. | Keep the memo foundation prominent, prioritize conversation and review, remove repeated copy and technical connection details from ordinary screens, and use restrained futuristic monochrome styling. Keep optional context, voice choices, saving, sources, unresolved gaps and review controls accessible. Simplification must preserve the interview and output requirements above. |

The intended outcome is that the participant has had a meaningful opportunity to explain everything they know about the selected process. The application cannot guarantee exhaustive knowledge capture, factual truth or an executable procedure where necessary facts remain unknown. Participant confirmation of their account, process-owner approval and independent verification are separate events.

## 5. Output contract

1. **Concise memo response:** all eleven topics, normal route described once, variation differences and the five most important owner questions.
2. **Detailed appendix:** process map, practical procedure, item lifecycles, checks, branches, variation records, source references and the full open-question register. This user-requested appendix is not subject to the memo summary's two-page target.
3. **Review state:** clear draft labelling; known, partial, unknown and not-applicable answers; unresolved disagreements or unreviewed material; participant-confirmation state; and process-owner review still required.

Generated steps, connections, lifecycle items, variations and reported memo findings must cite participant answer IDs or explicit intake context. Assistant questions are not evidence. A valid citation proves that the referenced source exists; the wording and inference still require semantic review. Manual review edits need the same scrutiny.

## 6. Implementation and verification mapping

The implementation pointers below describe the prototype, not a production guarantee. See `VALIDATION.md` for the observed evidence and limitations.

| Requirement area | Implementation | Verification and limit |
| --- | --- | --- |
| Eleven memo topics and explicit gaps | `server.py`: `COVERAGE`, `FINDING`, interview/draft schemas, `validate_findings`; `web/app.js`: coverage and memo review. | Automated tests require all eleven keys and reject unsupported finding statuses or missing/invalid source references. They do not establish that a natural conversation elicited every necessary fact. |
| Standing memo foundation | `FOUNDATION.md`; `server.py`: `foundation_instructions`, interview and draft instructions. | Foundation is included in model requests. Faithful conversational application remains model-assisted and needs human evaluation. |
| Adaptive elicitation and tangent control | Interview instructions, `focus`, `parking_lot`, memo findings and live question display. | Fictional live calls demonstrated follow-up questions. An observed repeated-unknown question led to stronger instructions; broad reliability has not been established. |
| Normal route, branches and variations | Draft schema, six variation fields, boundary flag, lifecycle records and the workflow graph. | Source/reference and graph-integrity tests pass. A separate model audit checks a candidate against the interview, but semantic correctness is not guaranteed. |
| Clear, grounded steps and connections | Explicit step fields, per-step/per-connection evidence, `validate_draft`, source navigation and draft audit. | Tests reject fabricated/non-participant IDs, duplicate nodes and dangling edges. Live review found and corrected unsupported route/control/variation inferences; residual sender/location inference risks remain documented. |
| Advisory meeting length | Historical pre-0.9.0 evidence. Current acceptance checks that pause, resume and completion use interview state. | Automated requests beyond the planned length are accepted. A fictional live request at 75 elapsed minutes with a 60-minute plan continued. Time is not a completion condition. |
| Final omissions check and reply ordering | `server.py`: `FINAL_CHECK_PREFIX`, `enforce_closure`; frontend Final completeness check action. | Automated tests require a real assistant check and a later participant reply before confirmation can remain true. A live fictional confirmation flow passed. Interpreting the meaning of the reply remains model-assisted. |
| Draft review, save/restore and exports | Review screen (Report, Notes, Workflow and Open questions); JSON session save/open; memo/procedure Markdown and map SVG exports. | Browser checks exercised exports and session restoration. There is no automatic session persistence. |
| Voice interaction and selectable playback | Live voice over WebRTC, `OpenAIClient.voice_session` for question playback, ten AI choices with Marin default, installed English computer voices and saved `voice_choice`. | The 61 Python tests include 12 voice API/security checks; 8 Node checks cover mocked Realtime/media behavior. Live Marin and Cedar generation returned the requested sample with matching transcripts (about 5.65/6.05 seconds). In a browser check, Cedar playback reached Speaking and completed without console warnings/errors; the selector switched back to Marin. Physical listening, microphone capture, subjective voice quality and a full human interview remain unverified. |

## 7. Acceptance review scenarios

Use fictional or appropriately permitted process information for acceptance review. Record pass/fail evidence and unresolved findings rather than treating a fluent answer as success.

- A preparer and approver are identified but no overall owner is known: accountability remains `TBD` or partial, not inferred.
- A participant describes an exception but cannot explain its resolution: the map does not invent a return path, actor, storage location or retry condition.
- A checklist or sample output is mentioned but no use is described: it is listed as existing material, not promoted to an operated control.
- Two client approvals are required but their order is unknown: the variation records the requirement and unknown order without inventing sequential or parallel work.
- One situation can occur for all clients: it remains a normal branch rather than a client variation.
- A difference changes start, accountable role or finished result: it is flagged as possibly separate work with the changed boundary identified.
- The participant says there is no common normal route, or teams disagree: both accounts and the absence of a standard remain visible.
- The planned meeting time passes: answers, follow-up and drafting remain available; no topic is silently dropped because of time.
- The user requests the final check before every topic is resolved: the agent asks about omissions, retains the named gaps and does not imply verification or approval.
- The participant adds information during closure: update the account and seek confirmation again rather than preserving an obsolete completed state.
- The participant stops early: preserve a partial capture and its remaining questions without claiming exhaustive completion.
- Before an interview, play a question with Marin and with Cedar and compare their suitability. Switch to an installed computer voice only through an explicit selection. Record subjective listening results separately from provider generation or protocol-test results.
- Stop playback or change voice while AI audio is pending: the pending operation must be cancelled and stale audio must not play. If the returned transcript differs from the question, withhold playback and leave the original question available as text.

Teams participation, production deployment, production retention/access controls and a guarantee that a participant has nothing further to say are outside the demonstrated prototype evidence. Teams connection is a later integration step.
## November 5, 2026 GPFS extension

The original eleven-topic memorandum above is retained as historical source.
The current GPFS deployment extends its coverage contract to sixteen topics by
adding scope, business rules/lineage, connected processes, data/systems and
volume/effort. The current owning rubric is `interview_coverage.py` and the standing
policy is `FOUNDATION.md`. See [the GPFS extension](GPFS_INTERVIEW_INTELLIGENCE.md)
for current behavior and [QA/UAT limits](GPFS_QA_UAT_2026-11-05.md). This extension
does not establish an approved company standard from one participant's account.
