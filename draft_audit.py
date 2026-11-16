"""Describe material omissions in the independent audit of an unpublished draft."""


def removal_notes(candidate, reviewed):
    """Report removals for owner review without publishing unsupported candidate claims."""
    notes = []
    old_steps = {row.get("id") for row in candidate.get("steps", []) if isinstance(row, dict)}
    new_steps = {row.get("id") for row in reviewed.get("steps", []) if isinstance(row, dict)}
    removed = old_steps - new_steps
    if removed:
        notes.append(f"The independent audit removed {len(removed)} proposed workflow step(s).")
    old_exceptions = {str(text).casefold().strip() for text in candidate.get("exceptions", [])}
    new_exceptions = {str(text).casefold().strip() for text in reviewed.get("exceptions", [])}
    if old_exceptions - new_exceptions:
        notes.append(f"The independent audit changed or removed {len(old_exceptions - new_exceptions)} proposed exception(s).")
    old = {item["key"]: item for item in candidate.get("memo_summary", []) if isinstance(item, dict) and "key" in item}
    for item in reviewed.get("memo_summary", []):
        prior = old.get(item.get("key"), {})
        if set(prior.get("evidence_turns", [])) - set(item.get("evidence_turns", [])):
            notes.append(f"The independent audit removed one or more proposed citations from the {item['key']} section.")
    return notes
