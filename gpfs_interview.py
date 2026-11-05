"""Shared GPFS discovery policy and evidence-bound classification contracts.

Vocabulary guides questions; it never establishes a client's practice or an
approved GPFS standard. No provider, filesystem or runtime work occurs here.
"""
import copy

CONTEXT = """
GPFS CONTEXT
Capture current business processes at GP Fund Solutions (GPFS). Relevant entity
types include funds, GP/carry vehicles, management companies (ManCos), feeders,
blockers, holding companies, SPVs and co-investment vehicles. Enterprise work
such as HR, IT and internal operations need not be entity-specific. These are
questioning vocabulary, never evidence that an entity, system or control applies.
Entrilia and Allvue are possible systems, not assumed systems of record.
Distinguish the participant's normal route from an approved GPFS standard.
Ask their basis, and preserve unknown, disputed or client-only practice. A route
is gold_standard only when a participant describes general GPFS practice AND
independent written material or a second account corroborates that exact scope;
this is corroborated reported practice, not owner approval or legal verification.
Classify differences as structural, client_specific, presentation or unclassified,
with their reported source and substantive-versus-presentation nature. Keep
charging and removal constraints where relevant; never infer that a variant is
unnecessary or a review redundant. Record who interprets rules; do not interpret
contracts or decide which source ought to prevail.
"""

SELECTION = """
NATURAL DISCOVERY AND COVERAGE
The sixteen topics are a private completeness guide, not a script or an entrance
exam. Build the account through an ordinary conversation about the work. Let the
participant finish their thought, including hesitations and short pauses. A caption
fragment, listening sound or quiet checkpoint is not a complete spoken answer.
Before asking, read the full account and extract what is already established.
An overview already establishes the steps, roles, outputs and events it names.
Do not make the person repeat that overview one step at a time. Ask only for a
missing dimension. If they said a senior checks the amounts before the manager
and client approve the notices, do not ask who checks them or what happens next.
Ask what the senior compares, if that is still unexplained. If they said a bank
email confirms receipt, do not ask how they know the money arrived; ask about an
unexplained receipt check or another gap. These are examples, not assumed facts.

Respond to a direct question, correction or confusion FIRST. If the participant
says they already answered, find and use that answer. Acknowledge the actual fact
briefly and move on; do not rephrase the same question, apologise in a loop or jump
to an unrelated heading. Distinguish a start email from a bank's completion email;
keep the participant's explanation attached to the right event. Do not ask
"you were saying 'We/It'" from a partial caption or make them finish a single word.

Start with the work they name. If it is broad (such as capital activity), narrow
it once to the work they want to explain. Once they say capital calls, retain it.
Invite a practical walkthrough, for example "Talk me through how a capital call
normally goes." Follow its steps and handoffs; ask ONE short, concrete request.
Clarify a consequential ambiguity when needed, otherwise let the story move on.
Do not drill every mechanism as soon as it is named. After one or two useful
follow-ups on a detail, continue the route or park an unavailable detail.
When they say they do not know, accept that answer once and move to a different
part of the work. Do not immediately ask the same need as how they find it, who
knows it or where they could look it up. Capture a resolver only if volunteered.
For example, after "I don't know what sets the payment date", leave that date's
basis open and continue the workflow; do not ask how they find the payment date.

Learn entity/client applicability, normal-versus-client practice, start, finish
and parent/dependencies from the story. Clarify scope at the point it matters,
without holding the walkthrough until every scope slot is filled. Use everyday
language anchored to reported work: "Does that work the same across your funds?"
rather than "Which entity types or part of GPFS does this serve?" Do not make a
participant certify the GPFS standard before describing their own work. Unknown
standard status/basis remains a gap; do not keep asking it in new words.

Use conditional modules only where relevant to this participant's work. Attach
rule questions to an actual calculation or decision: "Where do the investor
amounts come from?" or "What sets the payment date?" Never ask about "the main
rule", business-rule lineage, entity applicability or taxonomy in the abstract.
If the calculation is upstream, capture its source/output and continue this route.
Record mentioned documentation as existing, unreviewed material; an attachment
is not required to remember that it exists. Ask only for genuinely missing detail.

Briefly recap a useful stretch of the walkthrough or a material correction when
it helps the person check your understanding; avoid compulsory scoping recaps or
recapping the same facts repeatedly. After the route is clear, naturally fill
material gaps in rules, controls, connections, data, variants, volume, effort,
purpose, accountability, risk and materials. Avoid a questionnaire or a barrage
of new subjects. The background reviewers still assess every relevant dimension.
Unknown is not N/A, and a friendly conversation does not establish completeness.
Only the application owns the final omissions check, confirmation and completion.
"""

MODULES = """
CONDITIONAL MODULES (contextual signals, not a keyword checklist):
FUND: fund/LP/investor/NAV/LPA context suggests governing documents, side letters,
investor dimensions, allocation rules and notices where relevant to this work.
GP_CARRY: GP/carry/deemed contribution/fee waiver suggests partner economics,
commitment funding, related-party flows and GP-side approvals where in scope.
MANCO: management company/adviser/payroll/intercompany suggests fee and expense
flows, settlement, corporate approvals and accounting-policy sources.
MULTI_ENTITY: several reported entity types suggests whether logic actually
branches, where, why and whether differences are substantive or presentation.
CALCULATION: a calculated amount suggests inputs and origins, governing rule and
source, sequence/dependencies, investor/fund/entity dimensions, dates/periods,
mid-period treatment, prior-period inputs, rounding/tie-out, override authority
and recording, and amendments/corrections. Separate economic rule from its
implementation. Probe material missing details progressively, not all at once.
SPREADSHEET: workbook/model/macro suggests external rule versus logic existing
only in the sheet, logic ownership, re-keying, outputs and repeated calculation.
CLIENT_APPROVAL: reported client review/sign-off suggests exact approval point,
review versus approval, what is blocked, rejection/delay handling and evidence.
CLIENT_SPECIFIC: an actual reported client difference suggests GPFS standard
(if known), changed step, class/source, effort/controls/tools, charge and removal
constraints. A client name alone does not establish a difference.
Modules may overlap. Questions apply only to material unanswered slots within
the participant's boundary. An upstream calculation or approval is a dependency:
capture its source, output, owner and gap; do not expand into a different process.
Ask a neutral exception question once if still unanswered: what most often stops
this work or sends it back? Accept an explicit absence. Frequent reported returns
belong in the main route without assuming every run fails.
"""

FACETS = {
    "entity_type": ["fund", "gp_carry", "manco", "feeder", "blocker", "holding", "spv", "co_invest", "enterprise", "other"],
    "applicability": ["single_entity", "multi_same", "multi_variant", "enterprise", "unknown"],
    "functional_area": ["capital_activity", "fund_accounting", "investor_reporting", "financial_reporting", "fees_and_carry", "allocations", "treasury_payments", "tax", "compliance_regulatory", "investor_services", "onboarding", "data_management", "hr", "it", "internal_operations", "other"],
    "process_level": ["process", "subprocess", "activity", "unknown"],
    "client_applicability": ["gpfs_standard", "client_specific", "multi_client_variant", "enterprise", "unknown"],
    "rule_source": ["lpa_governing_doc", "side_letter", "subscription_docs", "client_methodology", "gpfs_methodology", "accounting_policy", "regulatory", "tax", "system_configuration", "prior_period_practice", "spreadsheet", "institutional_knowledge", "other", "unknown"],
    "system": ["entrilia", "allvue", "excel_workbook", "email", "sharepoint_folder", "client_portal", "bank_platform", "other", "none"],
    "control_type": ["gpfs_operational", "gpfs_supervisory", "client_review", "client_approval", "system_enforced", "exception_escalation", "none_reported"],
    "variant_class": ["gold_standard", "structural", "client_specific", "presentation", "unclassified"],
}
RELATIONSHIPS = ["provides_input_to", "consumes", "hands_off_to", "requires_approval_from", "happens_after", "variant_of", "subprocess_of", "parallel_with", "shares_calculation_with"]

def obj(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}

TEXT = {"type": "string"}
REFS = {"type": "array", "items": TEXT}
TAG_FIELDS = ("facet", "value", "note", "evidence_turns")
TAG = {"anyOf": [obj({"facet": {"type": "string", "enum": [facet]},
    "value": {"type": "string", "enum": values}, "note": TEXT, "evidence_turns": REFS})
    for facet, values in FACETS.items()]}
CONNECTION = obj({"relationship_type": {"type": "string", "enum": RELATIONSHIPS}, "counterpart": TEXT, "condition": TEXT, "evidence_turns": REFS})
CLASSIFICATIONS = {"type": "array", "items": TAG}
CONNECTIONS = {"type": "array", "items": CONNECTION}
TAG_OPERATION = {"anyOf": [obj({"op": {"type": "string", "enum": ["add", "replace", "remove"]},
    "target_id": TEXT, **branch["properties"]}) for branch in TAG["anyOf"]]}

CAPTURE_POLICY = """
BACKGROUND CLASSIFICATION
Populate taxonomy from cited evidence, never ask participants to select taxonomy.
Emit tag_operations with facet/value from the supplied controlled vocabulary and
note preserving scope, qualifiers and reported versus documented provenance.
Use other with a note for an unlisted value. No source means no tag. Add with an
empty target_id; replace/remove only a supplied active tag ID with correction
evidence. Empty operations retain existing tags. A correction must also retire
contradicted tags. Never promote a client's normal practice to gold_standard.
connections_out is the complete accumulated list of reported external process
dependencies; preserve prior entries unless evidence corrects them. A name is
allowed when no submission ID exists. These are reported leads, not confirmed
cross-submission graph links. Do not imply counterpart evidence was checked.
Report active_modules as relevant module names; recap_due is scope_boundary,
walkthrough or none. Check prior assistant turns before marking a recap due.
"""

def legacy_defaults(value, schema):
    """Upgrade only newly added empty/unknown fields, never invent business facts."""
    if not isinstance(value, dict):
        return
    defaults = {"taxonomy": [], "connections_out": [], "tag_operations": [],
                "active_modules": [], "recap_due": "none", "control_type": [],
                "data_origin": "", "entry_mode": "unknown", "rule_source_ref": "",
                "entity_scope": [], "parent_process": "", "variant_class": "unclassified",
                "substantive_or_presentation": "unknown", "source": "", "standard_route_ref": ""}
    fields = set(schema.get("properties", {}))
    allowed = set()
    if {"memo_findings", "question"} <= fields or "memo_summary" in fields:
        allowed.update(("taxonomy", "connections_out", "active_modules", "recap_due"))
    if {"fact_operations", "topic_states", "base_revision"} <= fields:
        allowed.update(("tag_operations", "connections_out", "active_modules", "recap_due"))
    if {"id", "actor", "system", "input", "output", "handoff", "completion_criteria"} <= fields:
        allowed.update(("control_type", "data_origin", "entry_mode", "rule_source_ref", "entity_scope", "parent_process"))
    if {"applies_to", "difference", "reason", "cost", "charging", "removability", "boundary_reason"} <= fields:
        allowed.update(("variant_class", "substantive_or_presentation", "source", "standard_route_ref"))
    for key in fields & allowed:
        if key not in value:
            value[key] = copy.deepcopy(defaults[key])

def validate_metadata(value, valid_sources):
    """Provenance/value guards; semantic classification still needs review."""
    if len(value.get("taxonomy", [])) > 128 or len(value.get("connections_out", [])) > 100:
        raise ValueError("Too many classifications or external process connections.")
    for item in value.get("taxonomy", []):
        if item["value"] not in FACETS[item["facet"]]:
            raise ValueError("Unsupported taxonomy value for its facet.")
        if item["value"] == "other" and not item["note"].strip():
            raise ValueError("An other classification needs a descriptive note.")
    for item in value.get("taxonomy", []) + value.get("connections_out", []):
        if not item["evidence_turns"] or not set(item["evidence_turns"]) <= set(valid_sources):
            raise ValueError("A classification or process connection requires exact authorized evidence.")
        if "counterpart" in item and not item["counterpart"].strip():
            raise ValueError("A process connection requires a named counterpart.")
    for item in value.get("taxonomy", []):
        if item["value"] == "gold_standard" and len(set(item["evidence_turns"])) < 2:
            raise ValueError("A gold standard requires corroborating sources, not a single report.")

def validate_corroboration(value, turns, documents):
    users = {t["id"] for t in turns if t.get("role") == "user" and not t.get("document_event")}
    docs = {d["id"] for d in documents or [] if not d.get("retained_only") and not d.get("provenance_only")}
    for item in value.get("taxonomy", []) + value.get("variations", []):
        if item.get("value") != "gold_standard" and item.get("variant_class") != "gold_standard":
            continue
        refs = set(item["evidence_turns"])
        # Several turns from one interview are still one account. A second
        # account is validated in the graph; this local path requires a document.
        if not refs & users or not refs & docs:
            raise ValueError("Gold standard needs participant testimony and independent documentary corroboration; multiple turns are one account.")
