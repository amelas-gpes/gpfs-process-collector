"""Closing the desktop window ends its local service within seconds, and reopening works at once.

A stand-in build that, like the real application, waits for the requests it has admitted before
it closes (daemon_threads = False). No network is used; Git must be on PATH.
"""
import sys
import threading
import time
import unittest
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

from test_desktop_updates import STUB, Installation, config


# GET /work/<seconds> takes that long to answer, and notes when it started and finished.
WORKS = STUB.replace("class InterviewServer(ThreadingHTTPServer):\n", (
    "class InterviewServer(ThreadingHTTPServer):\n"
    "    daemon_threads = False  # As the real server: close only after admitted requests end.\n")).replace(
    "    def do_GET(self):\n", (
        "    def do_GET(self):\n"
        "        if self.path.startswith('/work/'):\n"
        "            import time\n"
        "            seconds = self.path.rsplit('/', 1)[1]\n"
        "            with open(r'__PROOF__.work', 'a', encoding='ascii') as work:\n"
        "                work.write('started ' + seconds + '\\n')\n"
        "            time.sleep(float(seconds))\n"
        "            with open(r'__PROOF__.work', 'a', encoding='ascii') as work:\n"
        "                work.write('finished ' + seconds + '\\n')\n"))
assert WORKS.count("daemon_threads = False") == 1 and WORKS.count("/work/") == 1


@unittest.skipUnless(sys.platform == "win32", "Windows desktop installation")
class ClosingTheWindow(unittest.TestCase):
    def setUp(self):
        self.site = Installation(self)
        self.build = self.site.publish("c1", source=WORKS)
        self.site.app.update(90, 90)
        self.site.app.approve(self.build)
        self.work = Path(str(self.site.proof) + ".work")

    def open(self, port=None):
        port = port or self.site.free_port()
        process = self.site.launch("serve", "--port", port)
        self.addCleanup(lambda: [pipe.close() for pipe in (process.stdin, process.stdout, process.stderr)])
        first = process.stdout.readline().decode().strip()
        return process, port, first

    def begin_work(self, port, seconds):
        """Start one request that takes `seconds`; returns once the service is working on it."""
        outcome = {}

        def ask():
            try:
                with build_opener(ProxyHandler({})).open(
                        "http://127.0.0.1:%s/work/%s" % (port, seconds), timeout=120) as reply:
                    outcome["status"] = reply.status
            except OSError as error:
                outcome["error"] = type(error).__name__

        caller = threading.Thread(target=ask, daemon=True)
        caller.start()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and not (self.work.is_file() and "started " + str(seconds) in self.work.read_text()):
            time.sleep(.05)
        self.assertIn("started " + str(seconds), self.work.read_text() if self.work.is_file() else "")
        return caller, outcome

    def test_service_ends_soon_after_the_window_closes_although_a_request_is_still_running(self):
        site = self.site
        self.assertEqual((site.app.DRAIN_SECONDS, site.app.WINDOW_PATIENCE), (5, 10))
        window, port, first = self.open()
        self.assertEqual(first, "READY http://127.0.0.1:" + port + "/")
        caller, outcome = self.begin_work(port, 90)       # A provider-bound request: far longer than anyone waits.
        closed = time.monotonic()
        window.stdin.close()                              # The window closes.
        try:
            code = window.wait(45)
        except Exception:
            self.fail("the service was still running 45 seconds after its window closed")
        elapsed = time.monotonic() - closed
        self.assertEqual(code, 0)
        self.assertGreaterEqual(elapsed, site.app.DRAIN_SECONDS - 1, "requests in flight were given no time at all")
        self.assertLess(elapsed, 30)
        self.assertEqual(site.log().count("closed-while-working " + self.build[:12]), 1)
        self.assertNotIn("finished", self.work.read_text())
        caller.join(20)
        self.assertIn("error", outcome)                   # Its caller is told at once; it is not left waiting.
        # Nothing of that session is left holding the installation.
        with site.app.locked(site.state / ("window-" + port + ".lock"), 0):
            pass
        with site.app.locked(site.state / (self.build + ".lock"), 0):
            pass
        again, _, first = self.open(port)
        self.assertEqual(first, "READY http://127.0.0.1:" + port + "/")
        self.assertEqual(site.close(again), "")

    def test_reopening_at_once_waits_for_the_closing_session_instead_of_failing(self):
        site = self.site
        window, port, first = self.open()
        self.assertEqual(first, "READY http://127.0.0.1:" + port + "/")
        self.begin_work(port, 90)
        window.stdin.close()
        # The user reopens immediately. The old service is still closing and holds the window's lock.
        again, _, first = self.open(port)
        self.assertEqual(first, "READY http://127.0.0.1:" + port + "/",
                         "the reopened window failed while the previous session was still closing")
        self.assertEqual(config("http://127.0.0.1:" + port + "/")["build_id"], "stub-c1")
        self.assertEqual(window.wait(30), 0)
        self.assertNotIn("window-busy", site.log())
        self.assertEqual(site.log().count("window-ready"), 2)
        self.assertEqual(site.close(again), "")

    def test_short_request_in_flight_is_answered_before_the_service_ends(self):
        site = self.site
        window, port, first = self.open()
        self.assertEqual(first, "READY http://127.0.0.1:" + port + "/")
        caller, outcome = self.begin_work(port, 2)
        window.stdin.close()
        caller.join(30)
        self.assertEqual(outcome, {"status": 200}, "a request that needed two seconds was cut off by the close")
        self.assertEqual(window.wait(30), 0)
        self.assertIn("finished 2", self.work.read_text())
        self.assertNotIn("closed-while-working", site.log())
        # A window closed with nothing running ends at once, as before.
        window, port, first = self.open()
        closed = time.monotonic()
        self.assertEqual(site.close(window), "")
        self.assertLess(time.monotonic() - closed, site.app.DRAIN_SECONDS)
        self.assertNotIn("closed-while-working", site.log())


if __name__ == "__main__":
    unittest.main()
