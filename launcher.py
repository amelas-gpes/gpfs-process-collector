"""Start/stop this local prototype without installing or modifying the computer."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import Request, build_opener, ProxyHandler
import webbrowser

APP_DIR = Path(__file__).resolve().parent
WORK_DIR = APP_DIR / "work"
_build_spec = importlib.util.spec_from_file_location('collector_launcher_build', Path(__file__).with_name('runtime_build.py'))
_build_module = importlib.util.module_from_spec(_build_spec)
_build_spec.loader.exec_module(_build_module)


def config(url):
    try:
        with build_opener(ProxyHandler({})).open(url + "api/config", timeout=1) as response:
            result = json.load(response)
        return result if result.get("app_id") == "voice-interviewer" else None
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--port", type=int, default=8774)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535.")
    url = f"http://127.0.0.1:{args.port}/"
    current = config(url)
    if args.stop:
        if not current:
            print("No AI Process Collector is running on this port.")
            return
        request = Request(url + "api/shutdown", data=b"{}", method="POST",
                          headers={"X-CSRF-Token": current["csrf_token"], "Content-Type": "application/json", "Origin": url[:-1]})
        with build_opener(ProxyHandler({})).open(request, timeout=5) as response:
            json.load(response)
        for _ in range(30):
            if not config(url):
                break
            time.sleep(.1)
        else:
            raise SystemExit("The shutdown request was sent, but the server is still responding on this port.")
        print("AI Process Collector stopped. Unsaved sessions remain only in any open browser tab.")
        return
    expected_build = _build_module.build_id(APP_DIR)
    if current and current.get('build_id') != expected_build:
        raise SystemExit(f"An older app build is running at {url} Save its interview before restarting it. "
                         f"Use --stop --port {args.port} to stop that instance, or start on another --port to keep it open.")
    if not current:
        WORK_DIR.mkdir(exist_ok=True)
        log_path = WORK_DIR / "voice-interviewer-server.log"
        with log_path.open("ab") as log:
            process = subprocess.Popen([sys.executable, "-I", "-B", str(APP_DIR / "server.py"), "--port", str(args.port)],
                                       cwd=APP_DIR, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                       creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                                       start_new_session=sys.platform != "win32")
        for _ in range(40):
            current = config(url)
            if current and current.get('build_id') == expected_build:
                break
            if process.poll() is not None:
                break
            time.sleep(.15)
        if not current or current.get('build_id') != expected_build:
            # Only clean up the child launched by this invocation. A slow or
            # failed startup must not leave an unseen server behind after the
            # launcher reports that it could not start.
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            raise SystemExit(f"Could not start the prototype. Port {args.port} may be busy. See {log_path}.")
    print("AI Process Collector: " + url)
    if not args.no_browser:
        webbrowser.open(url)


if __name__ == "__main__":
    main()
