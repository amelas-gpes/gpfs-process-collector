"""Inspect the synthetic knowledge store without depending on an application UI."""
import json


def _rows(graph, query):
    with graph.lock:
        return [dict(row) for row in graph.db.execute(query)]


def submissions(graph):
    return [graph._submission(row) for row in _rows(graph, "SELECT * FROM revisions ORDER BY rowid")]


def entities(graph):
    return [{**row, "data": json.loads(row["data"])} for row in _rows(graph, "SELECT * FROM entities")]


def edges(graph):
    return [{**row, "evidence": json.loads(row["evidence"])} for row in _rows(graph, "SELECT * FROM edges")]


def jobs(graph):
    return [{**row, "detail": json.loads(row["detail"] or "{}")} for row in _rows(graph, "SELECT * FROM jobs")]


def proposals(graph):
    result = []
    for row in _rows(graph, "SELECT id, data, status, review_version, stale_reason FROM proposals ORDER BY rowid"):
        proposal = json.loads(row.pop("data"))
        result.append({**proposal, **row})
    return result
