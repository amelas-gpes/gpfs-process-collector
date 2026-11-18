"""clone_case.py SRC NEW PORT : copy a finished case so its draft can be requested again from another server."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); CASES = os.path.join(os.path.dirname(HERE), "cases")
src, new, port = sys.argv[1], sys.argv[2], int(sys.argv[3])
s = json.load(open(os.path.join(CASES, src + ".json")))
s["case"] = new; s["port"] = port
for key in ("csrf", "draft", "draft_error", "draft_meta", "draft_keys"):
    s.pop(key, None)
json.dump(s, open(os.path.join(CASES, new + ".json"), "w"), indent=1)
print("cloned", src, "->", new, "port", port, "turns", len(s.get("turns", [])), "map steps", len((s.get("workflow") or {}).get("steps", [])))
