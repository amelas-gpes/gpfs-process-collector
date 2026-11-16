# Targeted workflow corrections

The current interview worker retains a validated map, sixteen memo topics and source references. Notes and map work use the accepted interview snapshot, with revision checks before publication. A later answer can supersede queued work. Draft generation can compare its evidence against the previously displayed map. A free-text handoff remains a reported note. A drawn arrow requires support for the transition.

A parallel join means all incoming branches must finish. A merge allows alternative branches to continue. When the testimony leaves this rule open, the map records a clarification question. The editor, diagram and exported step type preserve that distinction.

## Historical implementation in 0.13.1

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

A route is accepted when at least one passage comes from a source the route cites and every
returned passage occurs in the source it names. Passages are compared on their wording: letter
case, runs of spaces or line breaks, typographic quotation marks, apostrophes and dashes, and
Unicode compatibility forms of the same characters (a ligature, a fullwidth or superscript digit,
a one-character fraction or ellipsis) are not differences. The reviewer does not have to quote
every cited source; the published route keeps only the cited sources that were quoted. A verified passage from a source the route does not cite
is ignored. A route supported only by such a passage, by an assistant question, or by a quotation
that does not occur in its source stays an open question.

A new proposal for a route that is already on the map and stays there (same source, destination
and label; the update neither removes the route or one of its steps nor retitles or retypes a
step) does not cost that route citations an earlier review verified.
When the passages verify, the route keeps those citations, as far as the proposal still lists them
and they are still active sources, and gains the newly quoted ones. When they do not verify and
the proposal only added citations to the ones the route has, the route stays exactly as it was:
no question is added about a connection the map still shows, and no second request is made for
it. A failed proposal that drops citations the route has replaces its evidence and is handled as
before: the map keeps the route as it was and gains an open question about the handoff. Every such
proposal is still reviewed, so a map model that repeats a route with a longer citation list causes
a review request.

In a map review, a reviewer that corrects only the citations of a proposed route supplies the
route again under the same source, destination and label. If it also lists that route among the
discarded proposals, the supplied route replaces the proposal; it is checked like any other.

When the reviewer returned passages that could not be verified, the app asks it once more about
those routes only: one further request for the whole map or draft, inside the time the first two
requests left unused, checked exactly like the first answer. A route returned with no passage is
the reviewer's decision and is not asked about again. If the second request fails in any way, is
late or still cannot be verified, a newly proposed route becomes an open question as before. An
existing handoff of a step whose title or type the update changes is different: if it cannot be
verified, the whole update still fails and the previous map stays. The local diagnostics log
records each route whose first passages failed: the review stage, the category of the reason (no
passage, wrong source, quotation not found) and the outcome (left open, verified by the second
request, rejected by it, second request unavailable, or published route kept). A typed-interview
map run that was cancelled or replaced before this check records nothing. The log never records
the route or any quoted text.

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

Typed and dictated answers are mapped in the background, where the browser sends no baseline. The
server keeps it instead: the next background map starts from the five baseline fields of the last map
that conversation published, while the transcript that map was drawn from is still the beginning of
the current one. Omission therefore keeps a step or route on this path too, step IDs stay stable and
an accepted route is not reviewed again. A baseline that no longer validates (a replaced file) or an
edited earlier answer gives the empty baseline; so does the update that follows one the application
refused, so that a refusal cannot repeat on every retry. A browser-supplied baseline is ignored there.

The output remains a working interpretation. An exact quote establishes where an edit came from;
it cannot prove that the model understood its scope correctly. The ordinary bounded request-size
limit still applies, including the prior-capture payload. No new dependencies or runtimes are needed.

See [build verification](BUILD_VERIFICATION.md) for executed checks and their limits.
