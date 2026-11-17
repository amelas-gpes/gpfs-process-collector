"""Provider stage timings and worker events from each isolated server's raw trace."""
import json, glob, sys, os, statistics as st, collections
S = sys.argv[1]
rows = []
for n in range(1, 8):
    for f in sorted(glob.glob(f"{S}/srv{n}/work/raw-trace/*.jsonl")):
        for l in open(f):
            try: r = json.loads(l)
            except ValueError: continue
            t = r.get("type")
            if t in ("server.provider_request_finished", "worker.workflow.error", "worker.workflow.published", "worker.workflow.started",
                     "worker.workflow.queued", "worker.capture.error", "interview.question.guard"):
                p = dict(r.get("payload") or {}); p.pop("content", None)
                rows.append({"srv": n, "at": r.get("observed_at"), "type": t, **p})
json.dump(rows, open(f"{S}/stages.json", "w"))
fin = [r for r in rows if r["type"] == "server.provider_request_finished"]
by = collections.defaultdict(list)
for r in fin: by[r.get("stage")].append(r)
def pct(v, q):
    v = sorted(v); return v[min(len(v) - 1, int(round(q * (len(v) - 1))))]
print(f"{'stage':34} {'n':>4} {'ok':>4} {'med_s':>7} {'p90_s':>7} {'max_s':>7} {'in_tok':>7} {'out_tok':>7} {'reason':>7} {'tok/s':>6}  models")
for k, v in sorted(by.items(), key=lambda kv: -sum(x.get("duration_ms", 0) for x in kv[1])):
    ok = [x for x in v if x.get("outcome") == "success"]
    d = [x["duration_ms"] / 1000 for x in ok] or [0]
    med = lambda f: int(st.median([x.get(f) or 0 for x in ok])) if ok else 0
    tps = st.median([(x.get("output_tokens") or 0) / max(.001, x["duration_ms"] / 1000) for x in ok]) if ok else 0
    print(f"{str(k):34} {len(v):4} {len(ok):4} {st.median(d):7.1f} {pct(d,.9):7.1f} {max(d):7.1f} {med('input_tokens'):7} {med('output_tokens'):7} {med('reasoning_tokens'):7} {tps:6.0f}  {sorted({str(x.get('model')) for x in ok})}")
bad = [r for r in fin if r.get("outcome") != "success"]
print("\nfailed/cancelled provider calls:", len(bad))
c = collections.Counter((r.get("stage"), r.get("outcome"), r.get("status"), r.get("error_category")) for r in bad)
for k, v in c.most_common(): print(" ", v, k)
for r in bad[:0]: print(r)
print("\nworkflow worker errors:", collections.Counter((r.get("error_type"), r.get("error_category")) for r in rows if r["type"] == "worker.workflow.error"))
print("maps published:", sum(1 for r in rows if r["type"] == "worker.workflow.published"), " started:", sum(1 for r in rows if r["type"] == "worker.workflow.started"))
print("question guard:", collections.Counter((r.get("stage"), r.get("reason") or r.get("outcome")) for r in rows if r["type"] == "interview.question.guard"))
