import json, sys, glob, os, statistics as st
S = sys.argv[1]
J = "<workflow journal.jsonl>"
res = {}; live = {}
for l in open(J):
    try: r = json.loads(l)
    except ValueError: continue
    if r.get("type") != "result": continue
    v = r.get("result") or r.get("value") or r.get("output")
    if isinstance(v, str):
        try: v = json.loads(v)
        except ValueError: continue
    if not isinstance(v, dict): continue
    if "utterances" in v: live[v["case_id"]] = v
    elif "case_id" in v: res[v["case_id"]] = v
json.dump(res, open(f"{S}/evals.json", "w"), indent=1); json.dump(live, open(f"{S}/live_scripts.json", "w"), indent=1)
print("evals", len(res), "live", list(live))
def pct(v, q):
    v = sorted(v); return v[min(len(v) - 1, int(round(q * (len(v) - 1))))] if v else None
rows = []; Q = []; N = []; M = []; allq = []
print(f"{'case':5} {'ans':>3} {'q_med':>6} {'q_max':>6} {'notes_med':>9} {'maps_mid':>8} {'wrap_s':>7} {'final_map':>10} {'map_s':>7} {'steps':>5} {'mapAcc':>6} {'notes':>5} {'ques':>4}  file: accepted/extracted/reviewed/firstQ")
for f in sorted(glob.glob(f"{S}/cases/*.json")):
    c = json.load(open(f)); cid = c["case"]
    if cid == "SMOKE": continue
    ev = c["events"]
    q = [e["seconds"] for e in ev if e["kind"] == "question" and e.get("status") == 200]
    n = [e["seconds"] for e in ev if e["kind"] in ("turn.notes_ready", "doc.notes_ready")]
    m = [e["seconds"] for e in ev if e["kind"] in ("turn.map_ready", "doc.map_ready")]
    pend = sum(1 for e in ev if e["kind"] in ("turn.left_pending", "doc.left_pending"))
    w = next((e for e in ev if e["kind"] == "wrap.sync"), {})
    wm = [e for e in ev if e["kind"] in ("wrap.map_ready", "wrap.map_error")]
    fm = "in-wrap" if w.get("workflow_state") == "ready" else (wm[-1]["kind"][5:] if wm else "pending")
    fms = wm[-1]["seconds"] if wm else (w.get("seconds") if fm == "in-wrap" else None)
    d = {e["kind"]: e["seconds"] for e in ev if e["kind"].startswith("doc.") and "seconds" in e}
    up = [e["seconds"] for e in ev if e["kind"] == "doc.upload"]
    e_ = res.get(cid, {})
    wf = c.get("workflow") or {}
    Q += q; N += n; M += m
    filecol = ""
    if up: filecol = f"{sum(up):.1f}/{d.get('doc.extracted','-')}/{d.get('doc.review_complete','-')}/{d.get('doc.first_question','-')}"
    print(f"{cid:5} {len(q):3} {st.median(q) if q else 0:6.1f} {max(q) if q else 0:6.1f} {st.median(n) if n else 0:9.1f} {len(m):3}/{len(m)+pend:<4} {w.get('seconds',0):7.1f} {fm:>10} {fms if fms is not None else 0:7.1f} {len(wf.get('steps',[])):5} {e_.get('map_accuracy_score','-'):>6} {e_.get('notes_accuracy_score','-'):>5} {e_.get('question_quality_score','-'):>4}  {filecol}")
    rows.append({"case": cid, "q": q, "notes": n, "maps_mid": m, "pending": pend, "wrap": w.get("seconds"), "final_map": fm, "final_map_s": fms, "steps": len(wf.get("steps", [])), "graph": c.get("graph_checks"), "doc": d, "upload": up})
json.dump(rows, open(f"{S}/timings.json", "w"), indent=1)
print(f"\nquestions n={len(Q)} median={st.median(Q):.1f} p90={pct(Q,.9):.1f} max={max(Q):.1f}")
print(f"notes     n={len(N)} median={st.median(N):.1f} p90={pct(N,.9):.1f} max={max(N):.1f}")
print(f"mid-interview maps that arrived before the next answer: {len(M)} of {len(M)+sum(r['pending'] for r in rows)} answers; their times: {sorted(M)}")
fm = [r for r in rows]
print("final map:", {k: sum(1 for r in fm if r['final_map']==k) for k in set(r['final_map'] for r in fm)})
ok=[r['final_map_s'] for r in fm if r['final_map'] in ('map_ready','in-wrap') and r['final_map_s']]
print(f"final map wait after Wrap up (successes) median={st.median(ok):.0f} p90={pct(ok,.9):.0f} max={max(ok):.0f}")
tr = [e for f in glob.glob(f"{S}/cases/*.json") for e in json.load(open(f))["events"] if e["kind"]=="transcribe"]
if tr: print(f"transcribe n={len(tr)} median={st.median([e['seconds'] for e in tr]):.1f} max={max(e['seconds'] for e in tr):.1f} audio_s={[e.get('audio_seconds') for e in tr]} secs={[e['seconds'] for e in tr]} wer={[e.get('wer') for e in tr]}")
sc = lambda k: [v[k] for v in res.values() if isinstance(v.get(k), int)]
print("avg map accuracy", round(st.mean(sc('map_accuracy_score')),2), "notes", round(st.mean(sc('notes_accuracy_score')),2), "questions", round(st.mean(sc('question_quality_score')),2))
import collections
c = collections.Counter(i["type"] for v in res.values() for i in v.get("map_issues", []))
print("map issue types:", c.most_common())
print("cases with no map:", [k for k,v in res.items() if not v.get("map_produced")])
