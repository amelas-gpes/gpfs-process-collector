import json, glob, sys
S = sys.argv[1]
for f in sorted(glob.glob(f"{S}/cases/[ABC]-*.json")):
    c = json.load(open(f)); ev = c["events"]
    t_first = next((e["at"] - e["seconds"] for e in ev if e["kind"] == "question"), None)
    users = sum(1 for t in c["turns"] if t["role"] == "user")
    shown = [e for e in ev if e["kind"].endswith(("map_shown", "map_ready"))]
    line = []
    for e in shown:
        line.append(f"{e['at'] - t_first:5.0f}s:{'audited' if e['kind'].endswith('map_ready') or e.get('audited') else 'drawn'}/{e.get('steps')}st" + (f"/-{e['answers_behind']}" if e.get('answers_behind') else ""))
    w = next((e for e in ev if e["kind"] == "wrap.sync"), None)
    wrap_at = (w["at"] - w["seconds"] - t_first) if w else None
    fin = [e for e in ev if e["kind"] in ("wrap.map_ready", "wrap.map_error", "wrap.left_pending")]
    q = [e["seconds"] for e in ev if e["kind"] == "question"]
    first = (shown[0]["at"] - t_first) if shown else None
    print(f"{c['case']:7} answers={users} wrap_at={wrap_at and round(wrap_at)}s first_map_visible={first and round(first)}s  final={[(e['kind'][5:], e.get('seconds'), e.get('steps'), e.get('code')) for e in fin]}")
    print("        maps seen (s after first answer : kind / steps / answers behind): " + "  ".join(line))
