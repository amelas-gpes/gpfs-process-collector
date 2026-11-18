"""Construct the provider's per-request schema without mutating shared app contracts."""
import copy
import json


def _enum_count(node):
    if isinstance(node, dict):
        return len(node.get("enum", [])) + sum(_enum_count(value) for value in node.values())
    if isinstance(node, list):
        return sum(_enum_count(value) for value in node)
    return 0


def _shared_enum(values):
    # Each ID may be 80 characters. Splitting long enums also respects the length ceiling.
    chunks = [{"type": "string", "enum": values[i:i + 180]} for i in range(0, len(values), 180)]
    return chunks[0] if len(chunks) == 1 else {"anyOf": chunks}


def wire_schema(schema, sources=None, participant_ids=(), topic_dimensions=None):
    # JSON round-tripping unfolds aliased schema objects into independent wire properties.
    result = json.loads(json.dumps(schema))
    if sources is None:
        return result
    if topic_dimensions:
        topics = result.get("properties", {}).get("topics")
        if topics:
            branches = []
            for key, dimensions in topic_dimensions.items():
                branch = copy.deepcopy(topics["items"])
                branch["properties"]["key"] = {"type": "string", "enum": [key]}
                array = branch["properties"]["dimensions"]
                array.update(minItems=len(dimensions), maxItems=len(dimensions))
                array["items"]["properties"]["key"] = {"type": "string", "enum": list(dimensions)}
                if "owner_followups" in branch["properties"]:
                    followup_fields = branch["properties"]["owner_followups"]["items"]["properties"]
                    followup_fields["dimension"] = {"type": "string", "enum": list(dimensions)}
                branches.append(branch)
            topics["items"] = {"anyOf": branches}
    references = []
    participant_refs = []
    participant_ids = list(participant_ids)

    def visit(node):
        if isinstance(node, list):
            for value in node:
                visit(value)
            return
        if not isinstance(node, dict):
            return
        fields = node.get("properties", {})
        status = fields.get("status", {}).get("enum", [])
        if not participant_ids and "owner_followup" in status:
            status.remove("owner_followup")
        if "key" in fields and "evidence_turns" in fields and set(status) == {"unknown", "partial", "captured", "not_applicable"}:
            unknown, reported = copy.deepcopy(node), copy.deepcopy(node)
            unknown["properties"]["status"]["enum"] = ["unknown"]
            unknown["properties"]["evidence_turns"].update(minItems=0, maxItems=500)
            reported["properties"]["status"]["enum"] = ["partial", "captured", "not_applicable"]
            reported["properties"]["evidence_turns"].update(minItems=1, maxItems=500)
            node.clear()
            node["anyOf"] = [unknown, reported] if sources else [unknown]
            fields = {}
        for name, prop in fields.items():
            if name in ("remove_steps", "remove_connections") and not participant_ids:
                prop["maxItems"] = 0
            if name == "owner_followups" and not participant_ids:
                prop["maxItems"] = 0
            if name.endswith("evidence_turns") and prop.get("type") == "array":
                participant_only = "source_quote" in fields or "interim_action" in fields
                allowed = participant_ids if participant_only else sources
                if not allowed:
                    prop.pop("minItems", None)
                    prop["maxItems"] = 0
                    continue
                prop["items"] = {"type": "string", "enum": allowed.copy()}
                (participant_refs if participant_only else references).append(prop["items"])
                if name == "evidence_turns" and set(fields).intersection(
                        {"from", "actor", "boundary_reason", "stages", "facet", "relationship_type", "source_quote", "interim_action"}):
                    prop["minItems"] = 1
            elif name == "source_id" and prop.get("type") == "string" and sources:
                prop["enum"] = sources.copy()
                references.append(prop)
        for value in node.values():
            visit(value)
    visit(result)
    if _enum_count(result) <= 900 and (len(sources) <= 250 or sum(map(len, sources)) <= 15000):
        return result
    if not references and not participant_refs:
        return result
    definitions = result.setdefault("$defs", {})
    def shared(name, definition, holders):
        while name in definitions:
            name += "_"
        definitions[name] = definition
        reference = {"$ref": "#/$defs/" + name}
        for holder in holders:
            holder.clear()
            holder.update(reference)
        return reference
    if participant_refs and sources != participant_ids:
        participant = shared("correction_participant_id", _shared_enum(participant_ids), participant_refs)
        participant_set = set(participant_ids)
        extra = [item for item in sources if item not in participant_set]
        if references:
            shared("participant_evidence_source", {"anyOf": [participant, _shared_enum(extra)]}, references)
    else:
        shared("participant_evidence_source", _shared_enum(sources), references + participant_refs)
    return result
