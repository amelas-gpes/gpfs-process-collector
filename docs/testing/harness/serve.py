"""Start the isolated copy on a port with the real checkout's settings passed as environment."""
import os, sys, re
env_file, app_dir, port = sys.argv[1], sys.argv[2], sys.argv[3]
for line in open(env_file, encoding="utf-8"):
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line: continue
    k, v = line.split("=", 1)
    v = re.split(r"\s+#", v.strip(), 1)[0].strip().strip("\"'")
    if v: os.environ[k.strip()] = v
os.environ["RAW_TRACE_MODE"] = "content"
for kv in sys.argv[4:]:
    k, v = kv.split("=", 1); os.environ[k] = v
os.chdir(app_dir)
os.execv(sys.executable, [sys.executable, "-I", "-B", os.path.join(app_dir, "server.py"), "--port", port])
