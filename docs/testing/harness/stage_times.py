"""Provider stage timings and worker events from isolated copies' raw traces.

  stage_times.py [--calls] [--out FILE] N [N...]      N = copy number (copies/app-N)
"""
import collections, glob, json, os, statistics as st, sys

# Where rig.py keeps its isolated copies: PC_SCRATCH/copies, or copies/ beside lib/.
COPIES = os.path.join(os.environ.get("PC_SCRATCH") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "copies")
KEEP = ("server.provider_request_finished", "server.provider_request_started", "worker.workflow.error", "worker.workflow.published",
        "worker.workflow.started", "worker.workflow.queued", "worker.capture.error", "interview.question.guard")


def rows_for(n):
    rows = []
    for f in sorted(glob.glob(f"{COPIES}/app-{n}/work/raw-trace/*.jsonl")):
        for line in open(f, encoding="utf-8", errors="replace"):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            t = r.get("type") or ""
            if t in KEEP or t.startswith("worker.") or t.startswith("interview.question"):
                p = dict(r.get("payload") or {})
                p.pop("content", None)
                rows.append({"srv": n, "at": r.get("observed_at"), "type": t, **{k: v for k, v in p.items() if not isinstance(v, (dict, list)) or k in ("usage",)}})
    return rows


def pct(v, q):
    v = sorted(v)
    return v[min(len(v) - 1, int(round(q * (len(v) - 1))))]


def main():
    a = sys.argv[1:]
    calls = "--calls" in a
    out = a[a.index("--out") + 1] if "--out" in a else None
    ns = [x for x in a if x.isdigit()]
    rows = [r for n in ns for r in rows_for(n)]
    if out:
        json.dump(rows, open(out, "w"))
    fin = [r for r in rows if r["type"] == "server.provider_request_finished"]
    by = collections.defaultdict(list)
    for r in fin:
        by[r.get("stage")].append(r)
    print(f"{'stage':38} {'n':>4} {'ok':>4} {'med_s':>7} {'p90_s':>7} {'max_s':>7} {'in_tok':>7} {'out_tok':>7} {'reason':>7}  models")
    for k, v in sorted(by.items(), key=lambda kv: -sum(x.get("duration_ms", 0) for x in kv[1])):
        ok = [x for x in v if x.get("outcome") == "success"]
        d = [x["duration_ms"] / 1000 for x in ok] or [0]
        med = lambda f: int(st.median([x.get(f) or 0 for x in ok])) if ok else 0
        print(f"{str(k):38} {len(v):4} {len(ok):4} {st.median(d):7.1f} {pct(d, .9):7.1f} {max(d):7.1f} {med('input_tokens'):7} {med('output_tokens'):7} {med('reasoning_tokens'):7}  {sorted({str(x.get('model')) for x in ok})}")
    bad = [r for r in fin if r.get("outcome") != "success"]
    print("\nfailed/cancelled provider calls:", len(bad))
    c = collections.Counter((r.get("stage"), r.get("outcome"), r.get("status"), r.get("error_category")) for r in bad)
    for k, v in c.most_common():
        print(" ", v, k)
    w = collections.Counter(r["type"] for r in rows if r["type"].startswith("worker."))
    print("\nworker events:", dict(w))
    print("workflow worker errors:", collections.Counter((r.get("error_type"), r.get("error_category"), r.get("reason")) for r in rows if r["type"] == "worker.workflow.error"))
    print("question guard:", collections.Counter((r.get("stage"), r.get("reason") or r.get("outcome")) for r in rows if r["type"].startswith("interview.question")))
    if calls:
        print("\nevery finished call, in order:")
        for r in fin:
            print(f"  {r['at']}  {str(r.get('stage')):36} {str(r.get('model')):16} {r.get('duration_ms', 0) / 1000:7.1f}s  in={r.get('input_tokens')} out={r.get('output_tokens')} reason={r.get('reasoning_tokens')} effort={r.get('reasoning_effort')} cap={r.get('requested_output_token_ceiling')} outcome={r.get('outcome')} {r.get('error_category') or ''}")


if __name__ == "__main__":
    main()
