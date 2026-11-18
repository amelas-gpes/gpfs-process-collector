#!/usr/bin/env python3
"""Isolated test servers for the stress run. Never touches the working checkout's work/ folder or port 8774.
Set PC_SCRATCH to a scratch folder outside the checkout; RIG_SRC serves another source tree with the checkout's settings.

  rig.py up N [N...] [--fresh] [KEY=VALUE...]   copy the checkout to copies/app-N and serve it on port 8800+N
  rig.py down N [N...] | all                    stop servers this rig started (by recorded PID)
  rig.py status                                 one line per copy
  rig.py port N                                 print the port of copy N

Settings come from the checkout's .env.local and are passed as environment (the key is never printed).
"""
import hashlib, json, os, shutil, signal, subprocess, sys, time, http.client

HERE = os.path.dirname(os.path.abspath(__file__))


def checkout():
    """The working checkout: PC_REPO, or the repository this file lives in."""
    if os.environ.get("PC_REPO"):
        return os.environ["PC_REPO"]
    folder = HERE
    while os.path.dirname(folder) != folder:
        if os.path.exists(os.path.join(folder, "launcher.py")):
            return folder
        folder = os.path.dirname(folder)
    sys.exit("Set PC_REPO to the Process Collector checkout.")


REPO = checkout()
# Isolated copies go under PC_SCRATCH/copies, or copies/ beside lib/ when this file was copied to a scratch folder.
SCRATCH = os.environ.get("PC_SCRATCH") or os.path.dirname(HERE)
COPIES = os.path.join(SCRATCH, "copies")
SRC = os.environ.get("RIG_SRC", REPO)
BASE_PORT = 8800
SKIP = {".git", "work", ".env.local", ".local", "tests", "desktop", ".github", ".claude", "__pycache__", ".DS_Store"}


def copy_dir(n):
    return os.path.join(COPIES, f"app-{n}")


def port_of(n):
    return BASE_PORT + int(n)


def settings(extra):
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "USER")}
    for line in open(os.path.join(REPO, ".env.local"), encoding="utf-8-sig"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        if " #" in v:
            v = v.split(" #", 1)[0].strip()
        v = v.strip("\"'")
        if v:
            env[k.strip()] = v
    env["RAW_TRACE_MODE"] = "content"
    for kv in extra:
        k, v = kv.split("=", 1)
        env[k] = v
    return env


def config(port, timeout=2):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        c.request("GET", "/api/config")
        r = c.getresponse()
        return json.loads(r.read()) if r.status == 200 else None
    except (OSError, ValueError, http.client.HTTPException):
        return None
    finally:
        c.close()


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def ours(pid, n):
    try:
        cmd = subprocess.run(["/bin/ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True).stdout
    except OSError:
        return False
    return copy_dir(n) + "/server.py" in cmd


def read_pid(n):
    try:
        return int(open(os.path.join(copy_dir(n), "server.pid")).read().strip())
    except (OSError, ValueError):
        return None


def up(n, fresh, extra):
    d, port = copy_dir(n), port_of(n)
    pid = read_pid(n)
    if pid and alive(pid) and ours(pid, n):
        print(f"app-{n}: already serving on {port} (pid {pid})")
        return True
    if config(port) is not None:
        print(f"app-{n}: port {port} is in use by something else; not starting")
        return False
    if fresh and os.path.isdir(d):
        shutil.rmtree(d)
    if not os.path.isdir(d):
        os.makedirs(d)
        for name in os.listdir(SRC):
            if name in SKIP:
                continue
            src, dst = os.path.join(SRC, name), os.path.join(d, name)
            if os.path.isdir(src):
                shutil.copytree(src, dst, ignore=shutil.ignore_patterns("testing", "__pycache__", ".DS_Store"))
            else:
                shutil.copy2(src, dst)
    log = open(os.path.join(d, "server.log"), "ab")
    p = subprocess.Popen([sys.executable, "-I", "-B", os.path.join(d, "server.py"), "--port", str(port)], cwd=d,
                         env=settings(extra), stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    open(os.path.join(d, "server.pid"), "w").write(str(p.pid))
    deadline = time.time() + 40
    while time.time() < deadline:
        c = config(port)
        if c:
            open(os.path.join(d, "build.txt"), "w").write(str(c.get("build")) + "\n")
            print(f"app-{n}: serving on {port} (pid {p.pid}, build {c.get('build')}, voice {c.get('voice_mode') or ''})")
            return True
        if p.poll() is not None:
            break
        time.sleep(0.3)
    print(f"app-{n}: FAILED to start on {port}; see {d}/server.log")
    return False


def down(n):
    pid = read_pid(n)
    if not pid or not alive(pid):
        print(f"app-{n}: not running")
        return
    if not ours(pid, n):
        print(f"app-{n}: pid {pid} is not this copy's server; left alone")
        return
    os.kill(pid, signal.SIGTERM)
    for _ in range(50):
        if not alive(pid):
            break
        time.sleep(0.1)
    else:
        os.kill(pid, signal.SIGKILL)
    print(f"app-{n}: stopped (pid {pid})")


def copies():
    if not os.path.isdir(COPIES):
        return []
    return sorted((int(x[4:]) for x in os.listdir(COPIES) if x.startswith("app-") and x[4:].isdigit()))


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    cmd, rest = a[0], a[1:]
    if cmd == "up":
        fresh = "--fresh" in rest
        extra = [x for x in rest if "=" in x]
        ns = [x for x in rest if x.isdigit()]
        ok = all([up(n, fresh, extra) for n in ns])
        sys.exit(0 if ok else 1)
    if cmd == "down":
        for n in (copies() if rest == ["all"] else rest):
            down(n)
        return
    if cmd == "status":
        for n in copies():
            pid = read_pid(n)
            state = "up" if pid and alive(pid) and ours(pid, n) else "down"
            build = ""
            try:
                build = open(os.path.join(copy_dir(n), "build.txt")).read().strip()
            except OSError:
                pass
            print(f"app-{n}: {state} port {port_of(n)} pid {pid} build {build}")
        return
    if cmd == "port":
        print(port_of(rest[0]))
        return
    sys.exit(__doc__)


if __name__ == "__main__":
    main()
