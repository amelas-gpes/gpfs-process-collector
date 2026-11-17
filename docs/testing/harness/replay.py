"""replay.py PORT THINK TAG CASE [CASE...] : replay the typed answers of finished cases concurrently on one server."""
import json, os, subprocess, sys, threading, time
HERE = os.path.dirname(os.path.abspath(__file__)); S = os.path.dirname(HERE)
think, tag, pairs = sys.argv[1], sys.argv[2], sys.argv[3:]
cases = pairs
PC = [sys.executable, "-I", "-B", os.path.join(HERE, "pc.py")]
def run(pair):
    cid, port = pair.split("@")
    src = json.load(open(f"{S}/cases/{cid}.json")); new = f"{tag}-{cid}"
    answers = [t["text"] for t in src["turns"] if t["role"] == "user"]
    out = [subprocess.run(PC + ["start", new, "--port", port, "--name", src["context"]["process_name"]], capture_output=True, text=True).stdout]
    for a in answers:
        out.append(subprocess.run(PC + ["answer", new, a, "--think", think], capture_output=True, text=True).stdout)
    out.append(subprocess.run(PC + ["wrap", new, "--mapwait", "540"], capture_output=True, text=True).stdout[:400])
    open(f"{S}/work/{new}.log", "w").write("\n".join(out))
th = [threading.Thread(target=run, args=(c,)) for c in cases]
[t.start() for t in th]; [t.join() for t in th]
print("replay done", tag, cases)
