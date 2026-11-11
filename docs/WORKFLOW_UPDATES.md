# Targeted workflow corrections

Version 0.13.1 changes how the working map responds to corrections. Previously, each request
sent the transcript without the current graph and asked the model for a complete replacement.
A valid smaller response could therefore erase unrelated steps. The saved backlog-refinement
example demonstrated this: replacing the first board-preparation step with getting water also
discarded later prioritization, idea updates and Jira/Confluence references.

The workflow request now includes a detached, validated `previous_capture`: the working graph,
eleven-topic memo, summary, focus and parked items. It is an earlier interpretation, not additional
evidence. Question, voice-connection and draft requests do not inherit that payload. Reviewer edits
to a separate draft remain outside this update path.

The configured interview model produces targeted changes with medium reasoning effort:

- `upsert_steps` creates or revises surviving actions. Existing IDs stay stable.
- `upsert_connections` creates or revises routes identified by their exact source, destination and label.
- `remove_steps` and `remove_connections` explicitly name existing components and cite a participant
  correction with a reason and an exact quoted source. Assistant, file-notification and context
  references cannot authorize removal. An edit and a removal cannot target the same component.
- `memo_findings` updates only the supplied topics; omitted topics retain their previous assessment.
  A known topic can become unknown only with participant evidence supporting its withdrawal.

Omission never deletes a prior step, route or memo topic. Removing a step removes its incident
routes, without guessing a new connection between its neighbors. Unsupported links remain questions.

When a new or changed route is reviewed, the reviewer supplies the source passages supporting its
direction and condition. The app checks those passages against the cited participant answers,
document excerpts or supplied background. An explicitly unsupported proposed link becomes an
open question. If the reviewer omits a required decision, the update fails and the last accepted
map stays in place. Correcting an existing step's title or type also triggers review of its incident
routes before the new version is accepted. Draft generation uses the same source checks in its
existing audit. Direct transcript-only working-map requests can now make an additional audit call.

A required dependency can be known even when the handoff mechanism or timing is unknown.
For example, if release requires two sign-offs, the map can show both dependencies under the joint
release condition and leave the order of the two reviews open.
The final merged graph and memo are validated before either is applied. Invalid responses and
responses whose source text was rewritten or removed retain the previous capture and retry action.
Version 0.13.2 accepts completed checkpoints while later answers or append-only captions continue,
shows that the latest answers are updating, and queues one follow-up. This prevents continuous speech
from suppressing every completed result. Readiness is withheld while newer evidence is pending.

The shared spoken/typed interviewing instructions also preserve unrelated facts. A first-step
correction is not a withdrawal of later steps. “That's about it” does not retract earlier answers.
Ambiguous scope should prompt one clarification. Summaries and gap lists describe the cumulative
account. An explicit whole-account withdrawal can still remove the complete graph.

Since 0.23.0 the working-map request starts when an answer is sent, alongside the lead's capture
call, instead of after it and only while Workflow is visible. It still carries the detached previous
capture, runs the document audit when file evidence is present, and waits for document intake and
for a completion review. A newer answer during a map update schedules one follow-up once it finishes.

The output remains a working interpretation. An exact quote establishes where an edit came from;
it cannot prove that the model understood its scope correctly. The ordinary bounded request-size
limit still applies, including the prior-capture payload. No new dependencies or runtimes are needed.

See [build verification](BUILD_VERIFICATION.md) for executed checks and their limits.
