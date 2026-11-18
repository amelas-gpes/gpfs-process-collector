"""Run the project's test suites in an isolated copy and write one JSON summary.

  runtests.py SRC LABEL [--only PATTERN] [--skip-node] [--skip-python] [--jobs N]

SRC is the tree to test (the checkout or a patched copy). It is copied to <scratch>/tests/LABEL/app without
.git, work, .env.local and .local, and every suite runs there, never in SRC.
"""
import concurrent.futures, fnmatch, json, os, shutil, subprocess, sys, time

# PC_SCRATCH: a scratch folder outside the checkout (default: the folder that holds lib/). PC_NODE: the Node to use.
SCRATCH = os.environ.get("PC_SCRATCH") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
NODE = os.environ.get("PC_NODE", "node")
RESULTS = os.path.join(SCRATCH, "logs")


def run(cmd, cwd, timeout):
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
                           env={k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "TMPDIR", "LANG", "USER")})
        return p.returncode, (p.stdout + "\n" + p.stderr)[-6000:], round(time.time() - t0, 1)
    except subprocess.TimeoutExpired as e:
        out = ((e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")) + \
              ((e.stderr or b"").decode("utf-8", "replace") if isinstance(e.stderr, bytes) else (e.stderr or ""))
        return "timeout", out[-3000:], round(time.time() - t0, 1)


def main():
    a = sys.argv[1:]
    src, label = a[0], a[1]
    only = a[a.index("--only") + 1] if "--only" in a else "*"
    jobs = int(a[a.index("--jobs") + 1]) if "--jobs" in a else 1
    app = os.path.join(SCRATCH, "tests", label, "app")
    if os.path.isdir(os.path.dirname(app)):
        shutil.rmtree(os.path.dirname(app))
    shutil.copytree(src, app, ignore=shutil.ignore_patterns(".git", "work", ".env.local", ".local", "__pycache__", ".DS_Store", ".claude"))
    os.makedirs(RESULTS, exist_ok=True)
    summary = {"label": label, "src": src, "python": {}, "node": {}}
    if "--skip-python" not in a:
        files = sorted(f for f in os.listdir(os.path.join(app, "tests")) if f.startswith("test_") and f.endswith(".py") and fnmatch.fnmatch(f, only))
        def one(f):
            code, out, secs = run([PY, "-I", "-B", "-m", "unittest", "discover", "-s", "tests", "-p", f], app, 300)
            tail = [l for l in out.strip().splitlines() if l.strip()][-3:]
            ran = next((l for l in reversed(out.splitlines()) if l.startswith("Ran ")), "")
            return f, {"exit": code, "seconds": secs, "ran": ran, "result": (tail[-1] if tail else ""), "failures": [l for l in out.splitlines() if l.startswith(("FAIL:", "ERROR:"))][:20],
                       "tail": out[-1500:] if code != 0 else ""}
        with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as ex:
            for f, r in ex.map(one, files):
                summary["python"][f] = r
                print(f"py  {f:52} {str(r['exit']):8} {r['seconds']:6}s  {r['ran']} {r['result'][:60]}", flush=True)
    if "--skip-node" not in a:
        files = sorted(f for f in os.listdir(os.path.join(app, "tests")) if f.endswith(".cjs") and f != "run_all.cjs" and fnmatch.fnmatch(f, only))
        def onej(f):
            code, out, secs = run([NODE, os.path.join("tests", f)], app, 600)
            tail = [l for l in out.strip().splitlines() if l.strip()][-1:] or [""]
            return f, {"exit": code, "seconds": secs, "result": tail[0][:200], "tail": out[-1500:] if code != 0 else ""}
        with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as ex:
            for f, r in ex.map(onej, files):
                summary["node"][f] = r
                print(f"js  {f:52} {str(r['exit']):8} {r['seconds']:6}s  {r['result'][:80]}", flush=True)
    bad_py = sorted(f for f, r in summary["python"].items() if r["exit"] != 0)
    bad_js = sorted(f for f, r in summary["node"].items() if r["exit"] != 0)
    summary["failing_python"], summary["failing_node"] = bad_py, bad_js
    json.dump(summary, open(os.path.join(RESULTS, f"tests-{label}.json"), "w"), indent=1)
    print(f"\npython: {len(summary['python']) - len(bad_py)}/{len(summary['python'])} files pass; failing: {bad_py}")
    print(f"node:   {len(summary['node']) - len(bad_js)}/{len(summary['node'])} files pass; failing: {bad_js}")


if __name__ == "__main__":
    main()
