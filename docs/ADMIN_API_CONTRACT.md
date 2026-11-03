# Bounded Admin read contract

All routes are same-origin authenticated administrative POSTs, with existing CSRF and example-mode isolation.

- `/api/knowledge/admin/browse`: `{section,filters?,offset?:0,limit?:25,example?}`
- `/api/knowledge/admin/detail`: `{kind,id,revision?,example?}`
- `/api/knowledge/admin/history`: `{kind,id,offset?:0,limit?:25,example?}`
- `/api/knowledge/admin/graph`: `{filters?,level:"overview"|"steps"|"all",submission_id?,example?}`

Pagination integers reject booleans, offset is nonnegative, limit is 1–50. Ordered offset pages include `{offset,limit,total,has_more}`. New/changed records may move between pages; Refresh begins again. No whole-dataset client cache or accumulation is required.

Filters: `team,system,scope,query,type` (strings <=500), `state` (all/reported/proposed/awaiting_clarification/confirmed/disputed/rejected/stale/superseded/active/pending/processing/completed/failed/unknown), `freshness` (all/recent/older), `submission_id` UUID, `revision` positive integer, `latest_only` boolean. Entity/group type uses `type`; entity member selection also accepts `exclude_group_id` UUID. Empty strings mean no text filter. Text matches use Unicode case folding and literal substrings (percent/underscore are not wildcards). Revisions are matched together with their submission for system filtering.

Browse sections: `overview,submissions,connections,entities,groups,jobs`.
Response: `{section,items,page,counts,analysis_limitations}`.
- submissions: metadata with context process_name/process_owner only, revision attribution/job_status; no transcript/draft.
- connections: proposal metadata, endpoint IDs/revisions/names, status/review_version/relationship_type/explanation/condition/scope/stale_reason; no evidence/history.
- entities: `{id,submission_id,revision,type,label,latest,canonical_id?}`; no data.
- groups: group metadata plus member_count, alias_count, history_count; no full lists.
- jobs: job metadata plus process_name.
- overview items empty; counts includes submissions, awaiting_review, confirmed_connections, processing_failures, entities,groups,jobs,connections.

Detail kinds: `submission,entity,relationship,proposal,group`.
Response: `{kind,item,submissions,entities,edges:[],proposals:[]}`.
- Submission requires revision and returns its full saved account, including complete transcript.
- Entity item includes data; relationship item includes evidence; proposal item includes exact evidence, but history is empty and history_count is provided.
- Group item has counts and empty members/aliases/history; use related pages below.
- Related submissions include metadata and ONLY cited user turns with `transcript_partial:true`. This is enough for exact excerpts; Open answer fetches submission detail for the full transcript.
- Related entities are metadata/label references only.

History/related kinds: `proposal,group,group_members,group_aliases,entity_neighbors,downstream`.
Response: `{kind,id,items,page}`.
- proposal/group: chronological review-history records (full records retained on subsequent pages).
- group_members: entity metadata (id/type/label/submission_id/revision/latest).
- group_aliases: `{alias}`.
- entity_neighbors/downstream: relationship metadata with `source_label,target_label`; confirmed cross-process relationships use `proposal_id` and `id` for opening proposal detail. Downstream follows reported sequence and confirmed handoffs, not mere containment or inferred effects.

Browse and related route states reflect the last source check. Resolving sources while filtering a page by status would move rows and could require an unbounded refill scan. Proposal detail, graph and review instead check only selected source evidence. Related pages include `source_verification:"stored_status"` and a visible `analysis_limitations` note directing the administrator to open a connection before relying on its source evidence.

Creating a reviewed group requires 2–100 current same-type entities. Corrections may remove members afterward, leaving a single member or an empty group; explicit revalidation still requires current retained members. Group mutations return metadata and counts without loading all members, aliases or history.

Graph response: `{entities,edges,proposals,submissions,too_large,counts:{nodes,connections},message,analysis_limitations}`.
Only latest revisions are graphed; selected submission_id restricts to one latest process and confirmed connections to relevant visible endpoints. Entities retain actor/system/evidence_turns needed for drawing but do not include full step bodies. Edges/proposals are graph metadata, without source quotes/history. A complete selected view exceeding 80 nodes or150 connections yields `too_large:true` and empty graph arrays with an explicit refine/select message, never a truncated partial graph. Process choices remain accessible through paged submissions. Full detail and every retained history/member/alias remain reachable through bounded routes.
