"""The independent audit of an unpublished draft: applying its corrections and describing them."""
import copy

# Sections the audit replaces whole when it names them in changed_sections. Steps, connections
# and memo findings are corrected one by one instead.
SECTIONS = ("title", "overview", "trigger", "inputs", "outputs", "exceptions", "controls", "open_questions",
            "validation_notes", "lifecycle_items", "variations", "taxonomy", "connections_out")
FIELDS = ("trigger", "inputs", "outputs", "exceptions", "controls")


def _route(edge):
    return edge.get("from"), edge.get("to"), edge.get("label")


def _rows(value):
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def changed_map(baseline, changes):
    """Apply step and route edits while preserving the order and evidence of retained work."""
    removed = {step for step in changes.get("drop_steps") or [] if isinstance(step, str)}
    corrected = {step.get("id"): step for step in _rows(changes.get("steps"))}
    steps, seen = [], set()
    for step in _rows(baseline.get("steps")):
        if step.get("id") in corrected:
            steps.append(copy.deepcopy(corrected[step["id"]]))
        elif step.get("id") not in removed:
            steps.append(copy.deepcopy(step))
        else:
            continue
        seen.add(step.get("id"))
    added = [step for step in _rows(changes.get("steps")) if step.get("id") not in seen]
    seen.update(step.get("id") for step in added)

    dropped = {_route(edge) for edge in _rows(changes.get("drop_connections"))}
    replaced = {_route(edge): edge for edge in _rows(changes.get("connections"))}
    connections, drawn = [], set()
    for edge in [*_rows(baseline.get("connections")), *_rows(changes.get("connections"))]:
        key = _route(edge)
        if key in drawn or edge.get("from") not in seen or edge.get("to") not in seen:
            continue
        if key in replaced:
            edge = replaced[key]
        elif key in dropped:
            continue
        connections.append(copy.deepcopy(edge))
        drawn.add(key)

    # A newly added step stands where its routes put it: before the first step it leads to when
    # nothing leads into it (a start event), otherwise after the last step that leads into it. The
    # report numbers steps in this order.
    for step in added:
        order = [row.get("id") for row in steps]
        targets = [order.index(edge["to"]) for edge in connections if edge.get("from") == step.get("id") and edge.get("to") in order]
        origins = [order.index(edge["from"]) for edge in connections if edge.get("to") == step.get("id") and edge.get("from") in order]
        position = max(origins) + 1 if origins else min(targets) if targets else len(steps)
        steps.insert(position, copy.deepcopy(step))

    return steps, connections


def draft_from_map(baseline, reply):
    """Apply first-pass changes. Refuse ambiguous edits before the candidate is cached."""
    step_ids = {step["id"] for step in baseline["steps"]}
    route_ids = {_route(edge) for edge in baseline["connections"]}
    steps = [step["id"] for step in reply["steps"]]
    routes = [_route(edge) for edge in reply["connections"]]
    drop_steps = reply["drop_steps"]
    drop_routes = [_route(edge) for edge in reply["drop_connections"]]
    if any(len(ids) != len(set(ids)) for ids in (steps, routes, drop_steps, drop_routes)):
        raise ValueError("The draft repeats a map change.")
    if (not set(drop_steps) <= step_ids or not set(drop_routes) <= route_ids
            or set(steps).intersection(drop_steps) or set(routes).intersection(drop_routes)):
        raise ValueError("The draft removes an unknown or updated map item.")
    final_ids = step_ids.union(steps).difference(drop_steps)
    if any(start not in final_ids or end not in final_ids for start, end, _ in routes):
        raise ValueError("A changed draft connection references a nonexistent step.")
    candidate = {key: value for key, value in reply.items() if key not in ("drop_steps", "drop_connections")}
    candidate["steps"], candidate["connections"] = changed_map(baseline, reply)
    return candidate


def merge(candidate, audit):
    """Return the audited draft: the candidate with the audit's corrections applied.

    The audit returns only what it changes (see DRAFT_AUDIT_SCHEMA in server.py). A returned
    step replaces the candidate step with its id, or is added where its routes put it; a returned connection replaces
    the candidate connection with its from, to and label, or is added; a returned finding
    replaces the finding with its key. A section named in changed_sections is replaced whole.
    A connection left without one of its steps goes with the step. Field evidence is bound to
    the entries as they now stand: a row whose text matches no entry is dropped, which leaves
    that entry marked for owner review instead of failing the whole draft.

    A reply without changed_sections is a complete corrected draft and is returned as it is.
    """
    if not isinstance(audit, dict) or "changed_sections" not in audit or not isinstance(candidate, dict):
        return audit
    merged = copy.deepcopy(candidate)
    changed = set(audit.get("changed_sections") or [])
    for key in SECTIONS:
        if key in changed and key in audit:
            merged[key] = copy.deepcopy(audit[key])

    merged["steps"], merged["connections"] = changed_map(candidate, audit)
    seen = {step["id"] for step in merged["steps"]}

    findings = {row.get("key"): row for row in _rows(audit.get("memo_summary"))}
    memo = [copy.deepcopy(findings.pop(row.get("key"), row)) for row in _rows(candidate.get("memo_summary"))]
    merged["memo_summary"] = memo + [copy.deepcopy(row) for row in findings.values()]

    for variation in _rows(merged.get("variations")):
        if variation.get("standard_route_ref") and variation["standard_route_ref"] not in seen:
            variation["standard_route_ref"] = ""

    evidence, bound = [], set()
    for row in _rows(audit.get("field_evidence")):
        field, text = row.get("field"), row.get("text")
        if field not in FIELDS:
            continue
        values = [merged.get("trigger")] if field == "trigger" else list(merged.get(field) or [])
        index = row.get("index")
        if not (isinstance(index, int) and 0 <= index < len(values) and values[index] == text and (field, index) not in bound):
            index = next((n for n, value in enumerate(values) if value == text and (field, n) not in bound), None)
        if index is None:
            continue
        bound.add((field, index))
        evidence.append({**copy.deepcopy(row), "index": index})
    merged["field_evidence"] = evidence
    merged["route_support"] = copy.deepcopy(audit.get("route_support") or [])
    return merged


def _count(number, noun):
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def removal_notes(candidate, reviewed, labels=None):
    """Tell the process owner what the source check took out, in a reader's words.

    labels names the memo sections (key to heading). The notes used to read as a log of the
    pipeline ("The independent audit changed or removed 1 proposed exception(s)."); a reviewer
    needs to know what to look at again, not which stage did it.
    """
    notes = []
    old_steps = {row.get("id") for row in candidate.get("steps", []) if isinstance(row, dict)}
    new_steps = {row.get("id") for row in reviewed.get("steps", []) if isinstance(row, dict)}
    removed = old_steps - new_steps
    if removed:
        notes.append(f"The source check removed {_count(len(removed), 'step')} that the answers and files did not support.")
    old_exceptions = {str(text).casefold().strip() for text in candidate.get("exceptions", [])}
    new_exceptions = {str(text).casefold().strip() for text in reviewed.get("exceptions", [])}
    if old_exceptions - new_exceptions:
        notes.append(f"The source check reworded or removed {_count(len(old_exceptions - new_exceptions), 'exception')} "
                     "to match what was reported; confirm the exceptions listed.")
    old = {item["key"]: item for item in candidate.get("memo_summary", []) if isinstance(item, dict) and "key" in item}
    for item in reviewed.get("memo_summary", []):
        prior = old.get(item.get("key"), {})
        if set(prior.get("evidence_turns", [])) - set(item.get("evidence_turns", [])):
            name = (labels or {}).get(item["key"]) or item["key"]
            notes.append(f"The source check removed a cited source from “{name}” that did not support it.")
    return notes
