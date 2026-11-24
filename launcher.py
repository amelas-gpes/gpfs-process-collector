"""Start/stop this local prototype without installing or modifying the computer."""
import argparse
import http.client
import importlib.util
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import time
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler
import webbrowser

APP_DIR = Path(__file__).resolve().parent
WORK_DIR = APP_DIR / "work"
_build_spec = importlib.util.spec_from_file_location('collector_launcher_build', Path(__file__).with_name('runtime_build.py'))
_build_module = importlib.util.module_from_spec(_build_spec)
_build_spec.loader.exec_module(_build_module)


# Something accepts connections on the port but did not answer as this app: an instance
# that is busy or slow, or another program. Never the same as "nothing is listening".
OCCUPIED = type("Occupied", (), {"__repr__": lambda self: "OCCUPIED"})()


def config(url, timeout=1):
    """This app's public configuration at url, None when nothing listens there, else OCCUPIED."""
    address = urlsplit(url)
    connection = http.client.HTTPConnection(address.hostname, address.port, timeout=timeout)
    try:
        try:
            connection.connect()
        except OSError:
            return None
        try:
            connection.request("GET", "/api/config")
            response = connection.getresponse()
            result = json.loads(response.read(1_000_000)) if response.status == 200 else None
        except (OSError, ValueError, http.client.HTTPException):
            return OCCUPIED
    finally:
        connection.close()
    return result if isinstance(result, dict) and result.get("app_id") == "voice-interviewer" else OCCUPIED


def settled(url):
    """config(url), giving a listener that has not answered yet a few seconds to do so."""
    for _ in range(8):
        current = config(url)
        if current is not OCCUPIED:
            break
        time.sleep(.25)
    return current


def startup_failure(port, log_path, log_start, exit_code):
    """Why the server this launcher started is not serving, in the server's own words.

    The log is append-only and shared by every attempt, so only what this attempt's
    child wrote (from log_start) is shown: its last lines, which hold the reason.
    """
    try:
        with log_path.open("rb") as log:
            log.seek(max(log_start, log.seek(0, 2) - 200_000))
            written = log.read(200_000).decode("utf-8", "replace")
    except OSError:
        written = ""
    lines = [line.rstrip() for line in written.splitlines() if line.strip()][-12:]
    said = ("\n" + "\n".join("  " + line[:300] for line in lines)) if lines else ""
    if exit_code is None:
        reason = f"the server did not answer on port {port} in time and was stopped."
    else:
        reason = f"the server stopped while starting (exit code {exit_code})."
    return (f"Could not start the prototype: {reason}" + (" It reported:" + said if said else "")
            + f"\nFull log: {log_path}")


def exited(pid, timeout):
    if type(pid) is not int or pid <= 0:
        return True  # Older builds only report the listener.
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        api.OpenProcess.restype = wintypes.HANDLE
        api.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        api.CloseHandle.argtypes = (wintypes.HANDLE,)
        process = api.OpenProcess(0x00100000, False, pid)
        if not process:
            return ctypes.get_last_error() == 87  # No process with this id.
        try:
            return api.WaitForSingleObject(process, int(timeout * 1000)) == 0
        finally:
            api.CloseHandle(process)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        time.sleep(.1)
    return False


def run_foreground(port, open_browser):
    original = sys.argv
    path = APP_DIR / "server.py"
    sys.argv = [str(path), "--port", str(port)] + (["--open"] if open_browser else [])
    try:
        runpy.run_path(str(path), run_name="__main__")
    finally:
        sys.argv = original


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--foreground", action="store_true", help="Keep the server attached to this managed terminal session.")
    parser.add_argument("--port", type=int, default=8774)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535.")
    url = f"http://127.0.0.1:{args.port}/"
    current = settled(url)
    if current is OCCUPIED:
        # Starting a second server here, or reporting that none is running, would both be wrong.
        raise SystemExit(f"Port {args.port} is in use, but what is listening there did not answer as AI Process Collector. "
                         "If the app is running and busy, try again in a moment; otherwise choose another --port.")
    if current and current.get("instance_id") and current["instance_id"] != _build_module.instance_id(APP_DIR):
        raise SystemExit(f"Another copy of AI Process Collector is using {url} from a different folder. "
                         "Use that folder's launcher to stop it or choose another --port.")
    if args.stop:
        if not current:
            print("No AI Process Collector is running on this port.")
            return
        request = Request(url + "api/shutdown", data=b"{}", method="POST",
                          headers={"X-CSRF-Token": current["csrf_token"], "Content-Type": "application/json", "Origin": url[:-1]})
        with build_opener(ProxyHandler({})).open(request, timeout=5) as response:
            json.load(response)
        if not exited(current.get("server_pid"), 10):
            raise SystemExit("Shutdown requested. The server is still finishing work. Try starting again once it has exited.")
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
        raise SystemExit(f"A different app build is running at {url}. Save its interview before restarting it. "
                         f"Use --stop --port {args.port} to stop that instance, or start on another --port to keep it open.")
    if not current and args.foreground:
        # Tool-launched background children can be stopped when their short-lived
        # launch job closes. Keep an explicitly managed session open instead;
        # ordinary desktop starts retain their existing hidden-child behavior.
        return run_foreground(args.port, not args.no_browser)
    if not current:
        log_path = WORK_DIR / "voice-interviewer-server.log"
        try:
            WORK_DIR.mkdir(exist_ok=True)
            if log_path.exists() and log_path.stat().st_size >= 1024 * 1024:
                log_path.replace(log_path.with_suffix(".previous.log"))
            log = log_path.open("ab")
        except OSError:
            raise SystemExit(f"Cannot write the server log in {WORK_DIR}. "
                             "Use a writable application folder with a shorter path.") from None
        print("Starting AI Process Collector...", flush=True)
        with log:
            log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} launcher: start on port {args.port}\n".encode())
            log.flush()
            log_start = log.tell()
            process = subprocess.Popen([sys.executable, "-I", "-B", str(APP_DIR / "server.py"), "--port", str(args.port)],
                                       cwd=APP_DIR, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                       creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                                       start_new_session=sys.platform != "win32")
        deadline = time.monotonic() + 45
        for _ in range(300):
            current = config(url)
            if isinstance(current, dict):
                break
            if process.poll() is not None or time.monotonic() >= deadline:
                break
            time.sleep(.15)
        ours = (isinstance(current, dict) and current.get("build_id") == expected_build
                and current.get("instance_id", _build_module.instance_id(APP_DIR)) == _build_module.instance_id(APP_DIR)
                and current.get("server_pid", process.pid) == process.pid)
        if not ours:
            # Only clean up the child launched by this invocation. A slow or
            # failed startup must not leave an unseen server behind after the
            # launcher reports that it could not start.
            exit_code = process.poll()
            if exit_code is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            # The child says why it stopped (a busy port, a settings file it cannot
            # read, a traceback). Repeat that instead of guessing at the port.
            raise SystemExit(startup_failure(args.port, log_path, log_start, exit_code))
        print("Started AI Process Collector at " + url)
    else:
        print("AI Process Collector is already running at " + url + ". Stop and start it to apply changes to settings.")
    if not args.no_browser:
        webbrowser.open(url)


if __name__ == "__main__":
    main()
