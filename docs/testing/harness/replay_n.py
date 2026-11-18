"""replay_n.py SRC NEW PORT N THINK : give the first N answers of a finished case to a new interview and list the questions."""
import json, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__)); S = os.path.dirname(HERE)
src, new, port, n, think = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5]
PC = [sys.executable, "-I", "-B", os.path.join(HERE, "pc.py")]
case = json.load(open(f"{S}/cases/{src}.json"))
answers = [t["text"] for t in case["turns"] if t["role"] == "user"][:n]
print(subprocess.run(PC + ["start", new, "--port", port, "--name", case["context"]["process_name"]], capture_output=True, text=True).stdout.strip(), flush=True)
for i, a in enumerate(answers, 1):
    out = subprocess.run(PC + ["answer", new, a, "--think", think], capture_output=True, text=True).stdout
    line = next((l for l in out.splitlines() if "INTERVIEWER:" in l), out[:200])
    print(f"after answer {i}: {line}", flush=True)
print(subprocess.run(PC + ["wrap", new], capture_output=True, text=True).stdout[:500], flush=True)
