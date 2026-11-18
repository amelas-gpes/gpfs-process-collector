#!/usr/bin/env python3
"""Objective scoring of stress cases from their case files.

  score.py table [CASE...]        one line per case: timings, map and draft shape, failures
  score.py questions CASE...      every interviewer turn, numbered, with the length of the answer before it
  score.py loss CASE...           anchor terms from the participant's answers that appear in none of notes, map, draft
  score.py json OUT               everything as JSON for the write-up
"""
import json, os, re, statistics as st, sys

CASES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cases")
STOP = set("the a an and or of to in on for with by at from that this it is are was were be been as we i you they he she our my your their not no do does did have has had will would can could should may might then than when if so but also only just very more most each every any all some into out up down over under again once here there what which who whom whose how why where while before after during between both few other such own same too".split())


def load(name):
    return json.load(open(os.path.join(CASES, name + ".json")))


def names(args):
    return args or sorted(f[:-5] for f in os.listdir(CASES) if f.endswith(".json") and not f.startswith(("SMOKE", "PSMOKE")))


def groups(wf):
    steps, conns = (wf or {}).get("steps") or [], (wf or {}).get("connections") or []
    ids = [x["id"] for x in steps]
    adj = {i: set() for i in ids}
    for e in conns:
        if e.get("from") in adj and e.get("to") in adj:
            adj[e["from"]].add(e["to"]); adj[e["to"]].add(e["from"])
    seen, out = set(), []
    for i in ids:
        if i in seen:
            continue
        stack, g = [i], set()
        while stack:
            x = stack.pop()
            if x not in g:
                g.add(x); stack += list(adj[x])
        seen |= g; out.append(len(g))
    types = [x.get("type") for x in steps]
    return {"steps": len(steps), "connections": len(conns), "groups": sorted(out, reverse=True),
            "start": types.count("start"), "end": types.count("end"), "decisions": types.count("decision")}


def med(v):
    return round(st.median(v), 1) if v else None


def metrics(s):
    ev = s.get("events") or []
    q = [e["seconds"] for e in ev if e["kind"] == "question" and e.get("status") == 200]
    notes = [e["seconds"] for e in ev if e["kind"].endswith(".notes_ready")]
    users = [t for t in s.get("turns", []) if t["role"] == "user"]
    shown = [e for e in ev if e["kind"].endswith((".map_shown", ".map_ready")) and e["kind"].startswith(("turn.", "doc."))]
    draft = next((e for e in ev if e["kind"] == "draft"), None)
    wrap = next((e for e in ev if e["kind"] == "wrap.sync"), None)
    review = next((e for e in ev if e["kind"] == "wrap.review"), None)
    wrapmap = next((e["seconds"] for e in ev if e["kind"] == "wrap.map_ready"), None)
    fails = [e for e in ev if (e.get("error") or e.get("status") not in (None, 200, 202)) and not e["kind"].startswith("doc.") or e["kind"].endswith(("notes_error", "map_error"))]
    docq = next((e["seconds"] for e in ev if e["kind"] == "doc.first_question"), None)
    tr = [e for e in ev if e["kind"] == "transcribe"]
    return {"case": s["case"], "process": s["context"]["process_name"], "answers": len(users),
            "words": sum(len(t["text"].split()) for t in users),
            "q_med": med(q), "q_max": round(max(q), 1) if q else None, "notes_med": med(notes), "notes_seen": len(notes),
            "map_during": len(shown), "first_map_s": round(min((e["seconds"] for e in shown), default=0), 1) or None,
            "wrap_s": round(wrap["seconds"], 1) if wrap else None, "wrap_kind": (wrap or {}).get("reply_kind"),
            "review_s": round(review["seconds"], 1) if review else None, "map_after_wrap_s": wrapmap,
            "map": groups(s.get("workflow")), "map_checked": s.get("workflow_checked"),
            "draft_s": round(draft["seconds"]) if draft else None, "draft_ok": bool(s.get("draft")),
            "draft_error": (s.get("draft_error") or {}).get("error"), "draft_map": groups(s.get("draft")) if s.get("draft") else None,
            "file_to_question_s": docq, "wer": [e.get("wer") for e in tr], "transcribe_s": [round(e["seconds"], 1) for e in tr],
            "failures": [{"kind": e["kind"], "status": e.get("status"), "error": (e.get("error") or "")[:120]} for e in fails]}


def text_of(obj):
    out = []
    def walk(v):
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, dict):
            for k, x in v.items():
                if k not in ("evidence_turns", "id", "from", "to", "generated_by", "agent_team", "fact_provenance", "fact_history"):
                    walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(obj)
    return " ".join(out)


def anchors(answer):
    """Numbers with their unit word, and capitalised names: the tokens most easily checked for loss."""
    found = set()
    for m in re.finditer(r'(?<![A-Za-z])(\$?\d[\d,]*(?:\.\d+)?%?)(?:\s+(?:business |calendar )?(days?|hours?|weeks?|months?|years?|percent|million|thousand|bps|basis points))?', answer):
        if len(m.group(1).strip("$%,.")) >= 1:
            found.add(m.group(0).strip())
    for m in re.finditer(r'\b([A-Z][a-zA-Z0-9]+(?:[ -][A-Z][a-zA-Z0-9]+){0,3})\b', answer):
        term = m.group(1)
        if term.lower() not in STOP and not re.match(r'^(I|If|The|That|Then|Next|After|Once|Before|What|We|It|To|Following|Yes|No|One|Since|Everything)\b', term):
            found.add(term)
    return found


def loss(s):
    haystack = " ".join(text_of(s.get(k)) for k in ("capture", "workflow", "draft")).lower()
    hay = re.sub(r'[^a-z0-9$%]+', ' ', haystack)
    missing = {}
    for t in s.get("turns", []):
        if t["role"] != "user":
            continue
        for term in sorted(anchors(t["text"])):
            norm = re.sub(r'[^a-z0-9$%]+', ' ', term.lower()).strip()
            if norm and norm not in hay:
                missing.setdefault(t["id"], []).append(term)
    return missing


def main():
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "table":
        print(f"{'case':5} {'ans':>3} {'words':>5} {'q_med':>5} {'q_max':>5} {'notes':>5} {'map@':>5} {'wrap':>5} {'kind':14} {'map steps/conns/groups':30} {'S/E':4} {'draft_s':>7} {'draft groups':22} failures")
        for n in names(args):
            m = metrics(load(n)); g = m["map"]; d = m["draft_map"]
            print(f"{m['case']:5} {m['answers']:3} {m['words']:5} {str(m['q_med']):>5} {str(m['q_max']):>5} {str(m['notes_med']):>5} {str(m['first_map_s']):>5} {str(m['wrap_s']):>5} {str(m['wrap_kind'])[:14]:14} "
                  f"{(str(g['steps']) + '/' + str(g['connections']) + ' ' + str(g['groups'])[:20]):30} {str(g['start']) + '/' + str(g['end']):4} "
                  f"{str(m['draft_s']) if m['draft_ok'] else 'FAIL' + str(m['draft_s']):>7} {(str(d['steps']) + ' ' + str(d['groups'])[:16]) if d else '-':22} "
                  f"{'; '.join(f['kind'] + ':' + str(f['status']) for f in m['failures'])[:80]}")
    elif cmd == "questions":
        for n in names(args):
            s = load(n); print(f"\n=== {n} — {s['context']['process_name']}")
            last = 0
            for t in s["turns"]:
                if t["role"] == "user":
                    last = len(t["text"].split())
                else:
                    print(f"  [{t['id']}] (after a {last}-word answer) {t['text'][:330]}")
    elif cmd == "loss":
        for n in names(args):
            s = load(n); miss = loss(s)
            total = sum(len(anchors(t["text"])) for t in s["turns"] if t["role"] == "user")
            print(f"\n=== {n}: {sum(len(v) for v in miss.values())} of {total} anchor terms in none of notes, map, draft")
            for turn, terms in miss.items():
                print(f"  {turn}: {terms[:25]}")
    elif cmd == "json":
        json.dump([metrics(load(n)) for n in names([])], open(args[0], "w"), indent=1)
        print("wrote", args[0])


if __name__ == "__main__":
    main()
