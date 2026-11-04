# Evidence and interview completion

The current managed-team implementation is described in [AGENT_TEAM.md](AGENT_TEAM.md). Version 0.22.0 uses one lead call for ordinary turns, explicit parallel review only at completion readiness, and zero further calls for an unchanged final confirmation. Candidate topics are provisional; every required dimension and the practical process must pass current independent review before the final omissions check. New substantive evidence invalidates the prior completion authority. Managed review may publish an explicitly cited repair when a summary omitted facts already supplied, but cannot manufacture missing testimony.

Version 0.24.0 brings GPT-Live back as the spoken front (`VOICE_MODE=live`, the default) while the managed team runs on the transcript behind it: the lead captures each spoken answer in the background, the application records and issues the acknowledgement, the final omissions check and the completion line, and the completion permit is unchanged. Version 0.21.0 had replaced direct live audio with reviewed turns, which remain available as `VOICE_MODE=reviewed`. The following 0.20 description is historical; its per-turn review timing does not describe the current UI.

Version 0.20.0 makes topic coverage depend on an explanation of the relevant process facts. Mentioning a topic, naming a tool, writing a heading or reaching the end of one line of questioning is insufficient.

## Coverage assessment

`interview_coverage.py` defines the eleven-topic rubric and the required dimensions of each topic. The same concise rubric reaches typed interviewing, the question auditor, direct live voice, delegated voice reasoning, workflow capture and draft generation.

When a capture proposes any `captured` or `not_applicable` finding, an independent model assessment checks all eleven topics against the complete supplied transcript and authorized document excerpts. It returns a plain-language explanation, source references, dimension-level support, unresolved gaps and a next useful question. Topic-level and dimension-level non-applicability require explicit participant support. An unavailable detail stays unresolved.

The server validates the assessment and only allows it to demote findings. It cannot promote partial topics, overwrite the supported account or add workflow facts. Missing dimensions, unsupported evidence, documentary-only current-practice claims and unresolved gaps prevent full coverage. If the assessment fails, claimed full topics become partial while useful process capture remains available. A model can still misinterpret valid evidence; structural validation is not semantic proof or independent process verification.

Uncertainty is scoped to the relevant finding and dimension. An unknown folder in a long answer must not erase an explicitly established accountable role from the same answer. A preparer, reviewer or approver is not automatically the role accountable for the overall result.

Reopened saved sessions retain their answers, sources and workflow, but their previous full-coverage claims are provisional until reassessed. The app offers **Recheck coverage** and also reassesses on continued interviewing. Opening a file alone does not make a provider request. A failed coverage review uses the same explicit retry, without an automatic retry loop. Request deadlines include the added assessment so a slow valid response is not discarded by the previous shorter browser timeout.

## Conversation and closure

The question auditor checks the final wording against the same rubric and full transcript. A deterministic response check runs after it, so the auditor cannot bypass completion checks by replacing the proposed question with recognized wrap-up language. An incomplete manual completeness check names open sections and requests corrections without announcing that the interview is finished.

The interviewer retains both threads when someone mentions two material issues. It switches from an unproductive vague probe to a concrete ambiguity or ordinary example, respects explicitly unavailable details and moves to untouched sections. It distinguishes risk ownership from actual consequences, process names from file names, and known output artifacts from unexplained transitions.

A local “No” answers the preceding local question. It does not confirm all sections. A new exception after a final check revokes confirmation. Explicit participant stops are respected immediately, with the account retained as partial where necessary. If all remaining gaps are explicitly unavailable, a partial handoff is appropriate; the sections remain incomplete. Partial drafts remain available.

## Live voice

The browser sends bounded coverage snapshots through the existing silent context channel after accepted capture updates and on connection. Snapshots contain all eleven findings, gaps, suggested follow-ups, the analyzed participant turn and freshness. New speech invalidates earlier readiness. Incomplete captions, changed documents, unaudited restored captures and lagging analyses cannot authorize completion. These snapshots are interpretations, never participant evidence, and do not trigger speech.

Live voice instructions forbid any self-initiated closure; the application issues the acknowledgement, the final check and the completion line as exact lines to say, and only its permit completes the interview. The live audio stream still has no deterministic pre-audio content gate on ordinary questions: prompt compliance and physical microphone/speaker turn-taking require live evaluation. Offline transport tests and text-model evaluations do not establish those behaviors.

## Validation approach

Regression tests cover premature replacements from the question auditor, a local “No,” manual checks with gaps, explicit stops, additions after a final check, assessment failures, required dimensions, citation boundaries, scoped uncertainty and stale live snapshots. Synthetic real-model checks test question selection and semantic coverage separately from those contracts. See the dated build verification entry for exact outcomes and limitations.

No fine-tuning or model-weight changes are involved. This release changes the application instructions, evidence assessment, response validation and live context.
