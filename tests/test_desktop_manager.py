"""Focused checks of desktop/manage.py against a throwaway installation.

No network is used: every "remote" is a local folder or a loopback listener. Git must be on PATH.
"""
import io
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
import zipfile

import test_desktop_updates
from test_desktop_updates import SETUP, STUB, Installation, config, git


DESKTOP = Path(__file__).resolve().parents[1] / "desktop"


class StalledEndpoint:
    """A loopback listener that accepts connections and then says nothing, as a captive
    portal, a half-open VPN route or a stalled proxy does. It hangs up after `hold` seconds,
    so that code which waits for the remote fails its test instead of blocking the suite."""

    def __init__(self, case, hold=40):
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(8)
        self.address = "http://127.0.0.1:%d/stalled.git" % self.listener.getsockname()[1]
        self.held = []
        threading.Thread(target=self._accept, daemon=True).start()
        release = threading.Timer(hold, self.close)
        release.daemon = True
        release.start()
        case.addCleanup(release.cancel)
        case.addCleanup(self.close)
        # The loopback endpoint must never be routed through a proxy.
        direct = {"NO_PROXY": "*", "no_proxy": "*", "GIT_CONFIG_COUNT": "1",
                  "GIT_CONFIG_KEY_0": "http.proxy", "GIT_CONFIG_VALUE_0": ""}
        patch = mock.patch.dict(os.environ, direct)
        patch.start()
        case.addCleanup(patch.stop)
        for name in [x for x in os.environ if x.lower() in ("http_proxy", "https_proxy", "all_proxy")]:
            del os.environ[name]

    def _accept(self):
        while True:
            try:
                self.held.append(self.listener.accept()[0])
            except OSError:
                return

    def close(self):
        for connection in [self.listener, *self.held]:
            try:
                connection.close()
            except OSError:
                pass

    def abandoned(self, seconds):
        """True once every client that connected has gone away (its process ended)."""
        deadline = time.monotonic() + seconds
        for connection in list(self.held):
            while True:
                connection.settimeout(max(.1, deadline - time.monotonic()))
                try:
                    if not connection.recv(65536):
                        break
                except (ConnectionError, OSError) as error:
                    if isinstance(error, socket.timeout):
                        return False
                    break
        return bool(self.held)


@unittest.skipUnless(sys.platform == "win32", "Windows desktop installation")
class FetchTimeout(unittest.TestCase):
    """A fetch that stalls ends at its timeout; it does not hold the window or the update lock."""

    FETCH = ["fetch", "--quiet", "--no-tags", "--no-recurse-submodules", "--no-write-fetch-head"]

    def test_stalled_fetch_ends_at_its_timeout_with_every_git_process_stopped(self):
        site = Installation(self)
        endpoint = StalledEndpoint(self)
        started = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            site.app.run_git([*self.FETCH, endpoint.address, "refs/heads/main:" + site.app.REF], 3)
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 15, "the fetch outlived its 3 second timeout while the remote stayed silent")
        self.assertTrue(endpoint.held, "the fetch never reached the endpoint, so nothing was tested")
        # git.exe starts git-remote-http.exe, which holds the connection. It must be gone too.
        self.assertTrue(endpoint.abandoned(10), "a git helper process was left running after the timeout")

    def test_download_gives_up_on_a_silent_remote_and_releases_the_update_lock(self):
        site = Installation(self)
        endpoint = StalledEndpoint(self)
        site.app.REMOTE = endpoint.address
        started = time.monotonic()
        with self.assertRaises((site.app.DesktopError, subprocess.TimeoutExpired)):
            site.app.update(4, .2)
        self.assertLess(time.monotonic() - started, 15, "the download waited on a remote that never answered")
        self.assertIn("fetch-failed", site.log())
        with site.app.locked(site.state / "update.lock", 0):
            pass  # The next launch or scheduled run is not locked out.
        self.assertTrue(endpoint.abandoned(10), "a git helper process was left running")

    def test_git_output_and_exit_status_are_still_reported(self):
        site = Installation(self)
        head = site.publish("c1")
        site.app.update(90, 90)
        self.assertEqual(site.app.git(["rev-parse", "--verify", site.app.REF + "^{commit}"], 8), head)
        missing = site.app.run_git(["rev-parse", "--verify", "refs/heads/no-such-branch"], 8)
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn(b"fatal", missing.stderr)
        self.assertEqual(missing.stdout, b"")
        with self.assertRaises(site.app.DesktopError):
            site.app.git(["rev-parse", "--verify", "refs/heads/no-such-branch"], 8)


CONSTRUCTED = "        super().__init__(address, handler)\n"
# Stand-in builds that pass the static checks made at download but cannot be hosted.
BROKEN_MAIN = STUB + "\ndef main():\n    raise RuntimeError('this build cannot start')\n"
OPENS_STORES_THEN_FAILS = STUB.replace(CONSTRUCTED, (
    "        Path(documents_root).mkdir(parents=True, exist_ok=True)\n"
    "        (Path(documents_root) / ('opened-by-' + MARK)).write_text('x')\n"
    "        raise RuntimeError('this build cannot start')\n"))
FAILS_ON_SAVED_DATA = STUB.replace(CONSTRUCTED, (
    "        if (Path(documents_root) / 'saved-by-another-build').exists():\n"
    "            raise RuntimeError('this build cannot read the saved data')\n" + CONSTRUCTED))
# A build that reports how it was started: which key, which stores, which folder, which environment.
REPORTS = STUB.replace("def load_settings():\n    return {}\n", (
    "def load_settings():\n"
    "    path = APP_DIR / '.env.local'\n"
    "    return dict(line.split('=', 1) for line in path.read_text().splitlines() if '=' in line) if path.is_file() else {}\n"
)).replace(CONSTRUCTED, (
    "        import os\n"
    "        with open(r'__PROOF__.calls', 'a', encoding='utf-8') as calls:\n"
    "            calls.write(json.dumps({'key': load_settings().get('OPENAI_API_KEY'), 'documents': str(documents_root),\n"
    "                                    'knowledge': str(knowledge_root), 'cwd': os.getcwd(), 'port': address[1],\n"
    "                                    'secret': os.environ.get('DESKTOP_QA_SECRET')}) + '\\n')\n" + CONSTRUCTED))
# A build that opens a store and then never answers. While it runs it holds a lock that a
# test can wait for, and it says which process it is and in which folder it was started.
HANGS_WITH_A_STORE_OPEN = STUB.replace(CONSTRUCTED, (
    "        import msvcrt, os, time\n"
    "        Path(documents_root).mkdir(parents=True, exist_ok=True)\n"
    "        self.store = open(Path(documents_root) / 'store', 'wb')\n"
    "        self.running = open(r'__PROOF__.running', 'a+b')\n"
    "        self.running.seek(0)\n"
    "        msvcrt.locking(self.running.fileno(), msvcrt.LK_NBLCK, 1)\n"
    "        Path(r'__PROOF__.where').write_text(json.dumps([os.getpid(), os.getcwd()]))\n"
    "        time.sleep(600)\n"))
assert CONSTRUCTED in STUB and len({STUB, OPENS_STORES_THEN_FAILS, FAILS_ON_SAVED_DATA, REPORTS,
                                    HANGS_WITH_A_STORE_OPEN}) == 5
# The installation's launcher with the port test answering "free", as it does when another
# program takes the port between that test and the moment a build binds it.
PORT_TAKEN_AFTER_ITS_TEST = SETUP.replace("app.cli()", "app.port_available=lambda port: True; app.cli()")
assert PORT_TAKEN_AFTER_ITS_TEST != SETUP


def another_program():
    """A listener on a port of its own, as another program holding the window's port."""
    holder = socket.socket()
    holder.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    holder.bind(("127.0.0.1", 0))
    holder.listen()
    return holder


def approve_next(site, mark, source=STUB):
    """Publish, download and approve one more build, as a Yes in the window does."""
    revision = site.publish(mark, source=source)
    site.app.update(90, 90)
    site.app.approve(revision)
    return revision


def open_once(case, site):
    """Open and close the window. Returns the build that answered and any line after READY."""
    window, address = site.window()
    build = config(address)["build_id"]
    return build, site.close(window).strip()


@unittest.skipUnless(sys.platform == "win32", "Windows desktop installation")
class StartupFailures(unittest.TestCase):
    """An approved build that cannot be hosted here is found before it is given the real
    stores, is not tried first at every later launch, and the window is told about it."""

    def runs(self, site, mark):
        return site.proof.read_text().split().count(mark)

    def test_build_that_cannot_start_never_opens_the_stores_and_is_not_tried_first_again(self):
        site = Installation(self)
        first = approve_next(site, "c1")
        self.assertEqual(open_once(self, site), ("stub-c1", ""))
        second = approve_next(site, "c2", OPENS_STORES_THEN_FAILS)
        fallback = f"Running the previous build: the latest update failed to start (using {first[:12]}, not {second[:12]})."
        build, notice = open_once(self, site)
        self.assertEqual(build, "stub-c1")
        self.assertFalse((site.root / "work").exists(), "a build that cannot start was given the real stores")
        self.assertEqual(notice, "NOTICE-NEW " + fallback)
        self.assertIn("startup-check-failed " + second[:12], site.log())
        self.assertEqual(site.app.failed(), {second: "startup-check-failed"})
        self.assertEqual(self.runs(site, "c2"), 1)
        # Later launches go straight to the build that works, and keep saying which one runs.
        for _ in range(2):
            self.assertEqual(open_once(self, site), ("stub-c1", "NOTICE " + fallback))
        self.assertEqual(self.runs(site, "c2"), 1, "the build that failed was run again at a later launch")
        self.assertEqual(site.log().count("startup-check-failed"), 1)
        self.assertEqual(site.app.approved(), [second, first])
        # The next approved build is tried as usual, and nothing more is reported once it runs.
        third = approve_next(site, "c3")
        self.assertEqual(open_once(self, site), ("stub-c3", ""))
        self.assertEqual(site.app.approved()[0], third)

    def test_build_that_fails_only_with_the_saved_data_is_skipped_after_one_failure(self):
        site = Installation(self)
        first = approve_next(site, "c1")
        self.assertEqual(open_once(self, site), ("stub-c1", ""))
        (site.root / "work" / "documents").mkdir(parents=True)
        (site.root / "work" / "documents" / "saved-by-another-build").write_text("x")
        second = approve_next(site, "c2", FAILS_ON_SAVED_DATA)
        fallback = f"Running the previous build: the latest update failed to start (using {first[:12]}, not {second[:12]})."
        build, notice = open_once(self, site)
        attempts = self.runs(site, "c2")
        again, reminder = open_once(self, site)
        self.assertEqual((build, again), ("stub-c1", "stub-c1"))
        self.assertEqual(self.runs(site, "c2"), attempts, "the build that failed was tried first again at the next launch")
        # It passed the check with empty stores, then failed with the real ones: once.
        self.assertEqual(attempts, 2)
        self.assertNotIn("startup-check-failed", site.log())
        self.assertEqual(site.log().count("startup-failed " + second[:12]), 1)
        self.assertEqual(site.app.failed(), {second: "startup-failed"})
        self.assertEqual((notice, reminder), ("NOTICE-NEW " + fallback, "NOTICE " + fallback))

    def port_refusal(self, port):
        return ("ERROR Port " + port + " is not available: another program may be using it. Close that program, "
                "or wait a moment, and reopen Process Collector.")

    def test_busy_port_fails_the_launch_without_running_or_condemning_a_build(self):
        site = Installation(self)
        approve_next(site, "c1")
        with another_program() as holder:
            port = str(holder.getsockname()[1])
            code, out, err = site.run("serve", "--port", port)
        self.assertNotEqual(code, 0)
        self.assertFalse(site.proof.exists(), "a build was run although the port was taken")
        self.assertEqual(site.app.failed(), {}, "a build was marked as failed because the port was in use")
        self.assertEqual(out.strip(), self.port_refusal(port))
        self.assertIn("port-unavailable", site.log())
        self.assertNotIn("startup-", site.log())
        self.assertEqual(open_once(self, site), ("stub-c1", ""))

    def test_busy_port_does_not_demote_the_chosen_build_behind_its_fallbacks(self):
        # The chosen build was opened before. Of its two fallbacks, the first cannot start.
        site = Installation(self)
        older = approve_next(site, "b")
        broken = approve_next(site, "a", BROKEN_MAIN)
        head = approve_next(site, "h")
        self.assertEqual(site.app.approved(), [head, broken, older])
        self.assertEqual(open_once(self, site), ("stub-h", ""))
        with another_program() as holder:
            port = str(holder.getsockname()[1])
            code, out, err = site.run("serve", "--port", port)
        self.assertNotEqual(code, 0)
        self.assertEqual(site.app.failed(), {}, "a launch on a busy port marked a build as failed")
        self.assertEqual(set(site.proof.read_text().split()), {"h"}, "a fallback was run because the port was busy")
        self.assertEqual(out.strip(), self.port_refusal(port))
        self.assertEqual(open_once(self, site), ("stub-h", ""))

    def test_port_that_is_busy_only_for_a_moment_does_not_open_or_keep_an_older_build(self):
        site = Installation(self)
        approve_next(site, "c1")
        approve_next(site, "c2")
        self.assertEqual(open_once(self, site), ("stub-c2", ""))
        holder = another_program()
        self.addCleanup(holder.close)
        port = str(holder.getsockname()[1])

        def release():
            # The other program lets go as soon as the chosen build has been refused the port.
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline and not any(
                    event in site.log() for event in ("port-unavailable", "startup-failed")):
                time.sleep(.05)
            holder.close()

        watcher = threading.Thread(target=release, daemon=True)
        watcher.start()
        code, out, err = site.run("serve", "--port", port, setup=PORT_TAKEN_AFTER_ITS_TEST)
        watcher.join(70)
        self.assertNotEqual(code, 0, "an older build was opened because the port was busy for a moment: " + out)
        self.assertEqual(out.strip(), self.port_refusal(port))
        self.assertNotIn("startup-failed", site.log())
        self.assertEqual(site.app.failed(), {}, "the chosen build was marked as failed because the port was busy")
        self.assertEqual(set(site.proof.read_text().split()), {"c2"})
        self.assertEqual(open_once(self, site), ("stub-c2", ""))

    def test_failed_check_of_a_fallback_does_not_condemn_the_build_tried_before_it(self):
        site = Installation(self)
        broken = approve_next(site, "c1", BROKEN_MAIN)
        head = approve_next(site, "c2", FAILS_ON_SAVED_DATA)
        self.assertEqual(open_once(self, site), ("stub-c2", ""))
        (site.root / "work" / "documents").mkdir(parents=True)
        (site.root / "work" / "documents" / "saved-by-another-build").write_text("x")
        code, out, err = site.run("serve", "--port", site.free_port())
        self.assertNotEqual(code, 0)
        self.assertTrue(out.startswith("ERROR Could not start an approved desktop release."), out)
        self.assertIn("startup-failed " + head[:12], site.log())
        self.assertIn("startup-check-failed " + broken[:12], site.log())
        # No build answered, so nothing shows that the chosen build's failure was its own.
        self.assertEqual(site.app.failed(), {broken: "startup-check-failed"})

    def test_window_closed_during_the_startup_check_leaves_no_process_and_no_scratch_folder(self):
        site = Installation(self)
        approve_next(site, "c1", HANGS_WITH_A_STORE_OPEN)
        where, running = Path(str(site.proof) + ".where"), Path(str(site.proof) + ".running")
        window = site.launch("serve", "--port", site.free_port())
        started, deadline = None, time.monotonic() + 60
        while not started and time.monotonic() < deadline:
            try:
                started = json.loads(where.read_text())
            except (OSError, ValueError):
                time.sleep(.1)
        self.assertTrue(started, "the startup check never started the build")
        build, scratch = started[0], Path(started[1])

        def stop_leftover():
            try:
                with site.app.locked(running, 0):
                    return
            except site.app.DesktopError:  # Still held, so that process is still the build.
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(build)], capture_output=True, stdin=subprocess.DEVNULL)

        self.addCleanup(stop_leftover)
        self.assertTrue((scratch / "work" / "documents" / "store").is_file())
        self.assertFalse(scratch.resolve().is_relative_to(site.root.resolve()))
        # The window host stops a backend that is still starting the way this does: at once.
        window.kill()
        window.communicate(timeout=30)
        try:
            with site.app.locked(running, 30):
                pass
        except site.app.DesktopError:
            self.fail("the build being checked kept running after the window's backend was stopped")
        deadline = time.monotonic() + 30
        while scratch.exists() and time.monotonic() < deadline:
            time.sleep(.2)
        self.assertFalse(scratch.exists(), "the startup check left its scratch folder behind")
        with site.app.locked(site.state / "update.lock", 0):
            pass  # Nothing is left holding the installation.

    def test_only_approved_build_is_tried_again_and_its_failure_is_forgotten_when_it_starts(self):
        site = Installation(self)
        only = approve_next(site, "c1", BROKEN_MAIN)
        for _ in range(2):  # With nothing else to run, each launch checks it again; none opens the stores.
            code, out, err = site.run("serve", "--port", site.free_port())
            self.assertNotEqual(code, 0)
            self.assertEqual(out.strip(), "ERROR Could not start an approved desktop release. The update log "
                             "(.local\\desktop\\updates.log) names each build that failed.")
        self.assertEqual(site.app.failed(), {only: "startup-check-failed"})
        self.assertEqual(site.log().count("startup-check-failed " + only[:12]), 2)
        self.assertNotIn("startup-failed", site.log())
        # Whatever stopped it is put right (here, by repairing the unpacked build).
        good = STUB.replace("__MARK__", "c1").replace("__PROOF__", str(site.proof))
        tree = site.state / "releases" / only
        (tree / "server.py").write_text(good)
        # This fixture now represents a verified, working release after its local prerequisite was repaired.
        (tree / ".desktop-manifest").write_text(json.dumps(site.app.release_manifest(tree)))
        self.assertEqual(open_once(self, site), ("stub-c1", ""))
        self.assertEqual(site.app.failed(), {})

    def test_startup_check_gets_a_placeholder_key_empty_stores_and_a_plain_environment(self):
        site = Installation(self)
        first = approve_next(site, "c1", REPORTS)
        with mock.patch.dict(os.environ, {"DESKTOP_QA_SECRET": "must-not-reach-the-check"}):
            port = site.free_port()
            window = site.launch("serve", "--port", port)
            self.assertEqual(window.stdout.readline().decode().strip(), "READY http://127.0.0.1:" + port + "/")
            self.assertEqual(site.close(window), "")
            self.assertEqual(open_once(self, site), ("stub-c1", ""))
        calls = [json.loads(line) for line in Path(str(site.proof) + ".calls").read_text().splitlines()]
        # One check, then the window; the second launch opens a build it has opened before.
        self.assertEqual(len(calls), 3)
        check, real = calls[0], calls[1]
        self.assertEqual(check["key"], "startup-check-placeholder")
        self.assertEqual(check["port"], 0)
        self.assertIsNone(check["secret"], "the startup check inherited the caller's environment")
        inside = site.root.resolve()
        for folder in (check["documents"], check["knowledge"], check["cwd"]):
            self.assertFalse(Path(folder).resolve().is_relative_to(inside), folder)
            self.assertFalse(Path(folder).exists(), "the check's scratch folder was left behind")
        self.assertEqual(Path(check["documents"]).parent, Path(check["cwd"]) / "work")
        # The window itself gets this checkout's settings and stores, as before.
        self.assertEqual(real["key"], "synthetic-offline-fixture")
        self.assertEqual(real["port"], int(port))
        self.assertEqual(Path(real["documents"]), site.root / "work" / "documents")
        self.assertEqual(Path(real["knowledge"]), site.root / "work" / "knowledge")
        self.assertEqual(real["secret"], "must-not-reach-the-check")
        self.assertEqual(calls[2]["documents"], real["documents"])
        # The check is not a way to run a build nobody approved, or to run one inside the checkout.
        waiting = site.publish("c2", source=REPORTS)
        site.app.update(90, 90)
        self.assertEqual(site.app.pending(), waiting)
        with tempfile.TemporaryDirectory() as outside:
            self.assertNotEqual(site.run("_rehearse", waiting, cwd=outside)[0], 0)
            self.assertNotEqual(site.run("_rehearse", "0" * 40, cwd=outside)[0], 0)
        self.assertNotEqual(site.run("_rehearse", first)[0], 0)
        # `_check` answers for the build only while its input stays open (see `checked`): the
        # approved build passes, so the refusal of the one that is waiting is the build's own.
        self.assertEqual(self.checked(site, first), 0, "the startup check failed a healthy approved build")
        self.assertEqual(self.runs(site, "c1"), 4)
        self.assertNotEqual(self.checked(site, waiting), 0, "the startup check passed a build nobody approved")
        self.assertNotIn("c2", site.proof.read_text().split())
        self.assertEqual(self.runs(site, "c1"), 4)

    def checked(self, site, revision):
        """Exit status of the internal `_check` command with its input held open, as `serve`
        holds it. `_check` reads the end of its input as "the asker has gone" and then fails
        whatever the build is, so a caller that closes the input learns nothing from the status."""
        process = site.launch("_check", revision)
        try:
            return process.wait(150)
        finally:
            for pipe in (process.stdin, process.stdout, process.stderr):
                pipe.close()


@unittest.skipUnless(sys.platform == "win32", "Windows desktop installation")
class KnownGoodRollbackAndHold(unittest.TestCase):
    """Opening a build does not prove it works. The build last seen working is kept, the
    user can go back to it, and can stop the updater."""

    def test_build_counts_as_working_only_after_its_page_loaded_and_the_window_stayed_open(self):
        site = Installation(self)
        first = approve_next(site, "c1")
        self.assertEqual(site.app.KNOWN_GOOD_AFTER, 300)
        with mock.patch.dict(os.environ, {"DESKTOP_QA_KNOWN_GOOD_AFTER": "60"}):
            # Opened, looked at, closed again within the minute: the build started, nothing more is known.
            window, address = site.window()
            self.assertEqual(config(address)["build_id"], "stub-c1")
            site.close(window)
            self.assertEqual((site.state / "last-opened.txt").read_text(), first)
            self.assertIsNone(site.app.known_good(), "one launch made the build the one to fall back to")
        with mock.patch.dict(os.environ, {"DESKTOP_QA_KNOWN_GOOD_AFTER": "2"}):
            # Left open for longer than that, but the window never loaded the page.
            window, address = site.window()
            time.sleep(5)
            site.close(window)
            self.assertIsNone(site.app.known_good(), "a window that never loaded its page counted as working")
            # The page was requested and the window stayed open.
            window, address = site.window()
            self.assertEqual(config(address)["build_id"], "stub-c1")
            deadline = time.monotonic() + 60
            while site.app.known_good() != first and time.monotonic() < deadline:
                time.sleep(.25)
            site.close(window)
        self.assertEqual(site.app.known_good(), first)
        self.assertEqual(site.log().count("known-good " + first[:12]), 1)

    def test_build_last_known_to_work_survives_later_approvals_and_is_the_default_rollback(self):
        site = Installation(self)
        good = approve_next(site, "c1")
        self.assertEqual(open_once(self, site), ("stub-c1", ""))
        (site.state / "known-good.txt").write_text(good)
        # Three later builds each start, are opened once, and are replaced by the next.
        for mark in ("c2", "c3", "c4"):
            latest = approve_next(site, mark)
            self.assertEqual(open_once(self, site), ("stub-" + mark, ""))
            site.app.update(90, 90)  # The scheduled task's clean-up runs here.
            self.assertIn(good, site.app.approved(), "the last build known to work is no longer a fallback")
            self.assertTrue((site.state / "releases" / good / "server.py").is_file(),
                            "the last build known to work was deleted")
        # It is the first fallback, ahead of builds that were merely opened.
        self.assertEqual(site.app.approved()[:2], [latest, good])
        self.assertLessEqual(len(site.app.approved()), 4)
        # Going back needs no commit ID, and takes effect at the next launch.
        code, out, err = site.run("rollback")
        self.assertEqual((code, out.strip()), (0, "Process Collector will open build " + good[:12]
                                               + " the next time its window opens."), err)
        self.assertEqual(site.app.approved()[0], good)
        self.assertIn("release-selected " + good[:12], site.log())
        self.assertEqual(open_once(self, site), ("stub-c1", ""))
        # The build that was left is still on GitHub main. It is not offered again, and it stays approved.
        self.assertEqual(site.app.update(90, 90), latest)
        self.assertIn("not-selected " + latest[:12], site.log())
        self.assertIsNone(site.app.pending())
        self.assertEqual(site.app.offer(), "")
        self.assertEqual(open_once(self, site), ("stub-c1", ""))
        self.assertIn(latest, site.app.approved())
        # A newer commit is offered as usual and can be approved from the rolled-back build.
        newer = site.publish("c5")
        self.assertEqual(site.app.update(90, 90), newer)
        self.assertEqual(site.app.offer().splitlines()[0], "UPDATE " + newer)
        site.app.approve(newer)
        self.assertEqual(site.app.approved()[:2], [newer, good])
        self.assertEqual(open_once(self, site), ("stub-c5", ""))

    def test_rollback_chooses_only_among_approved_builds(self):
        site = Installation(self)
        first = approve_next(site, "c1")
        with self.assertRaises(site.app.DesktopError):
            site.app.rollback()  # Nothing earlier to go back to.
        second = approve_next(site, "c2")
        waiting = site.publish("c3")
        site.app.update(90, 90)
        self.assertEqual(site.app.pending(), waiting)
        for revision in (waiting, waiting[:12], "0" * 40, "main", first[:6], first.upper(), first + "0", "..", " "):
            with self.assertRaises(site.app.DesktopError):
                site.app.rollback(revision)
        self.assertEqual(site.app.approved(), [second, first])
        self.assertEqual(site.app.pending(), waiting, "a rollback attempt changed what is waiting for approval")
        # No build known to work yet: the previous choice. By prefix: that build. Naming the
        # build that was left returns to it, and asks for a build that failed to be tried again.
        self.assertEqual(site.app.rollback(), first)
        self.assertEqual(site.app.approved(), [first, second])
        site.app.note_failures({second: "startup-failed"})
        self.assertEqual(site.app.rollback(second[:7]), second)
        self.assertEqual(site.app.approved(), [second, first])
        self.assertEqual(site.app.failed(), {})
        self.assertEqual(site.app.rollback(first), first)
        code, out, err = site.run("rollback", waiting)
        self.assertNotEqual(code, 0)
        self.assertIn(first[:12] + ", " + second[:12], err)
        self.assertFalse(site.proof.exists(), "choosing a build ran one")

    def test_hold_stops_downloads_offers_and_approvals_until_resumed(self):
        site = Installation(self)
        first = approve_next(site, "c1")
        self.assertEqual(open_once(self, site), ("stub-c1", ""))
        second = site.publish("c2")
        site.app.update(90, 90)
        self.assertEqual(site.app.offer().splitlines()[0], "UPDATE " + second)
        code, out, err = site.run("hold")
        self.assertEqual(code, 0, err)
        self.assertIn("on hold", out)
        self.assertTrue((site.state / "hold").is_file())
        # A build downloaded before the hold is no longer offered and cannot be approved.
        self.assertEqual(site.app.offer(), "")
        self.assertEqual(site.run("pending")[:2], (0, ""))
        with self.assertRaises(site.app.DesktopError):
            site.app.approve(second)
        self.assertEqual(site.app.approved(), [first])
        # Nothing new is fetched, unpacked or cleaned up, and the task ends normally.
        third = site.publish("c3")
        fetched = git(site.root, "rev-parse", site.app.REF)
        code, out, err = site.run("update")
        self.assertEqual(code, 0, err)
        self.assertIn("on hold", out)
        self.assertIsNone(site.app.update(90, 90))
        self.assertEqual(git(site.root, "rev-parse", site.app.REF), fetched)
        self.assertFalse((site.state / "releases" / third).exists())
        self.assertIn("on-hold", site.log())
        # The window opens the approved build and says why nothing is offered.
        build, notice = open_once(self, site)
        self.assertEqual(build, "stub-c1")
        self.assertTrue(notice.startswith("NOTICE Updates are on hold"), notice)
        code, out, err = site.run("resume")
        self.assertEqual(code, 0, err)
        self.assertFalse((site.state / "hold").exists())
        self.assertEqual(site.app.update(90, 90), third)
        self.assertEqual(site.app.offer().splitlines()[0], "UPDATE " + third)
        self.assertEqual(open_once(self, site), ("stub-c1", ""))
        for event in ("updates-held", "updates-resumed"):
            self.assertIn(event, site.log())


def archive(path, names):
    """A zip whose member names are exactly as given: [(name, mode or None), ...]."""
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as bundle:
        for name, mode in names:
            member = zipfile.ZipInfo(name)
            member.create_system = 3
            member.external_attr = (mode or (stat.S_IFREG | 0o644)) << 16
            member.filename = name  # ZipInfo() rewrote backslashes; an archive can carry them.
            bundle.writestr(member, b"x")
    path.write_bytes(data.getvalue())
    return path


@unittest.skipUnless(sys.platform == "win32", "Windows desktop installation")
class ArchivePaths(unittest.TestCase):
    """What a downloaded commit may unpack: nothing outside its own folder, nothing that
    Windows treats specially, and none of the checkout's private names at its top level."""

    REFUSED = {
        "parent folder": "../evil.txt",
        "nested parent folder": "a/../../evil.txt",
        "absolute": "/abs.txt",
        "drive": "C:/x.txt",
        "drive-relative": "C:x.txt",
        "alternate data stream": "a/b.txt:hidden",
        "backslash parent": "..\\evil.txt",
        "backslash nested parent": "web\\..\\..\\evil.txt",
        "empty name": "",
        "current folder": "./",
        "dots only": "a/.../b",
        "device NUL": "NUL",
        "device with extension": "web/con.txt",
        "device as folder": "aux/x.js",
        "device COM1": "COM1",
        "device CONIN$": "CONIN$",
        "device with space and extension": "NUL .txt",
        "trailing dot": "web/app.js.",
        "trailing space": "web/app.js ",
        "folder with trailing dot": "web./app.js",
        "git folder": ".git/config",
        "git folder, other case": ".GIT/config",
        "desktop state": ".local/desktop/approved.json",
        "saved data": "work/documents/documents.sqlite3",
        "saved data, other case": "Work/x",
        "settings": ".env",
        "local settings": ".env.local",
        "local settings, other case": ".ENV.LOCAL",
        "settings look-alike": ".envrc",
    }
    ACCEPTED = ["server.py", "web/index.html", "web/vendor/library.min.js", "docs/Guide (v2).md", ".env.example",
                ".gitignore", "desktop/manage.py", "a/b/c/d.txt", "tests/fixtures/sample.csv"]

    def setUp(self):
        self.site = Installation(self)
        self.scratch = self.site.folder / "unpack"
        self.scratch.mkdir()

    def unpack(self, label, names):
        destination = self.scratch / "out" / label.replace(" ", "-").replace(",", "")
        self.site.app.extract_release(archive(self.scratch / "case.zip", names), destination)
        return destination

    def contained(self):
        """Nothing was written beside the destination folders, or above the scratch folder."""
        self.assertLessEqual({item.name for item in self.scratch.iterdir()}, {"case.zip", "out"})
        self.assertFalse((self.site.folder / "evil.txt").exists())
        for item in (self.scratch / "out").glob("*") if (self.scratch / "out").is_dir() else ():
            self.assertTrue(item.is_dir(), item)

    def test_unsafe_member_names_are_refused(self):
        for label, name in self.REFUSED.items():
            with self.subTest(case=label, name=name):
                with self.assertRaises(self.site.app.DesktopError):
                    self.unpack(label, [(name, None)])
                self.contained()
                self.assertEqual([item for item in (self.scratch / "out").rglob("*") if item.is_file()], [])
        with self.subTest(case="symbolic link"):
            with self.assertRaises(self.site.app.DesktopError):
                self.unpack("link", [("link", stat.S_IFLNK | 0o777)])
        with self.subTest(case="one unsafe member among good ones"):
            with self.assertRaises(self.site.app.DesktopError):
                self.unpack("mixed", [("server.py", None), ("web/index.html", None), (".env.local", None)])
            self.assertFalse((self.scratch / "out" / "mixed" / ".env.local").exists())

    def test_ordinary_application_files_are_unpacked_in_place(self):
        destination = self.unpack("ordinary", [(name, None) for name in self.ACCEPTED] + [("empty-folder/", stat.S_IFDIR | 0o755)])
        found = sorted(item.relative_to(destination).as_posix() for item in destination.rglob("*") if item.is_file())
        self.assertEqual(found, sorted(self.ACCEPTED))
        self.assertTrue((destination / "empty-folder").is_dir())
        self.contained()
        # A network-style name stays inside the destination whether or not it is accepted.
        try:
            self.unpack("network", [("//server/share/x", None)])
        except self.site.app.DesktopError:
            pass
        self.contained()

    def test_commit_carrying_a_private_name_is_not_staged_or_offered(self):
        site = self.site
        for mark, name in (("c1", ".env.local"), ("c2", "work/knowledge/knowledge.sqlite3"), ("c3", ".local/desktop/approved.json")):
            with self.subTest(name=name):
                planted = site.publish(mark, files={name: "planted by the commit\n"})
                with self.assertRaises(site.app.DesktopError):
                    site.app.update(90, 90)
                self.assertIn("staging-failed " + planted[:12], site.log())
                self.assertIsNone(site.app.pending())
                self.assertEqual(site.app.offer(), "")
                self.assertEqual(list((site.state / "releases").iterdir()), [])
                self.assertEqual([item.name for item in site.state.glob("stage-*")], [])
                # Take the planted name out of the remote again before the next case.
                top = site.remote / name.split("/")[0]
                git(site.remote, "rm", "-r", "--quiet", "--cached", top.name)
                if top.is_dir():
                    shutil.rmtree(top)
                else:
                    top.unlink()
        self.assertEqual((site.root / ".env.local").read_text(), "OPENAI_API_KEY=synthetic-offline-fixture\n")
        self.assertFalse((site.root / "work").exists())
        self.assertFalse(site.proof.exists())


@unittest.skipUnless(sys.platform == "win32", "Windows desktop installation")
class LocksAndCleanup(unittest.TestCase):
    def test_cleanup_removes_only_unused_releases_and_never_one_a_window_holds(self):
        site = Installation(self)
        app, releases = site.app, site.state / "releases"
        kept, leased, unused = "a" * 40, "b" * 40, "c" * 40
        for name in (kept, leased, unused, "notes-not-a-release"):
            (releases / name / "web").mkdir(parents=True)
            (releases / name / "server.py").write_text("raise SystemExit('never run')\n")
        (releases / ("d" * 40)).write_text("a file, not a release folder\n")
        (site.state / (unused + ".lock")).write_bytes(b"")
        outside = site.folder / "outside"
        outside.mkdir()
        (outside / "precious.txt").write_text("not part of any release\n")
        junction = releases / ("e" * 40)
        try:
            import _winapi
            _winapi.CreateJunction(str(outside), str(junction))
        except (ImportError, AttributeError, OSError):
            junction = None
        with app.locked(site.state / (leased + ".lock"), 0):  # A window is serving this release.
            app.clean_old_releases({kept, None})
            self.assertTrue((releases / leased / "server.py").is_file(), "a release in use by a window was deleted")
        self.assertTrue((releases / kept / "server.py").is_file())
        self.assertFalse((releases / unused).exists())
        self.assertFalse((site.state / (unused + ".lock")).exists())
        self.assertTrue((releases / "notes-not-a-release" / "server.py").is_file())
        self.assertTrue((releases / ("d" * 40)).is_file())
        self.assertEqual((outside / "precious.txt").read_text(), "not part of any release\n",
                         "cleanup followed a link out of the releases folder")
        if junction:
            self.assertTrue(junction.exists())
        # Once the window has closed, the next cleanup removes that release too.
        app.clean_old_releases({kept})
        self.assertFalse((releases / leased).exists())
        self.assertTrue((releases / kept).is_dir())

    def test_download_keeps_approved_waiting_opened_and_known_good_builds_and_removes_the_rest(self):
        site = Installation(self)
        builds = [approve_next(site, mark) for mark in ("c1", "c2", "c3", "c4", "c5")]
        self.assertEqual(site.app.approved(), [builds[4], builds[3], builds[2]])
        (site.state / "last-opened.txt").write_text(builds[1])
        waiting = site.publish("c6")
        self.assertEqual(site.app.update(90, 90), waiting)
        on_disk = {item.name for item in (site.state / "releases").iterdir()}
        self.assertEqual(on_disk, {builds[4], builds[3], builds[2], builds[1], waiting},
                         "kept: the three approved builds, the one last opened, the one waiting")
        self.assertFalse((site.state / (builds[0] + ".lock")).exists())
        self.assertFalse(site.proof.exists())

    def test_lock_is_exclusive_times_out_and_is_released_on_error_or_when_its_holder_dies(self):
        site = Installation(self)
        path = site.state / "example.lock"
        with self.assertRaises(RuntimeError):
            with site.app.locked(path, 0):
                started = time.monotonic()
                with self.assertRaises(site.app.DesktopError):
                    with site.app.locked(path, .4):
                        self.fail("two holders of one lock")
                self.assertGreaterEqual(time.monotonic() - started, .3)
                raise RuntimeError("the holder fails")
        with site.app.locked(path, 0):
            pass
        holder = subprocess.Popen(
            [sys.executable, "-I", "-B", "-c",
             "import msvcrt,sys,time; f=open(sys.argv[1],'a+b'); f.seek(0); "
             "msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1); print('held',flush=True); time.sleep(300)", str(path)],
            stdout=subprocess.PIPE, stdin=subprocess.DEVNULL)
        self.addCleanup(lambda: holder.kill() if holder.poll() is None else None)
        self.assertEqual(holder.stdout.readline().strip(), b"held")
        with self.assertRaises(site.app.DesktopError):
            with site.app.locked(path, .2):
                self.fail("the lock was not held by the other process")
        holder.kill()
        holder.wait(30)
        holder.stdout.close()
        with site.app.locked(path, 10):
            pass

    def test_window_launch_is_not_held_up_by_a_download_in_progress(self):
        site = Installation(self)
        approve_next(site, "c1")
        second = site.publish("c2")
        site.app.update(90, 90)
        third = site.publish("c3")
        with site.app.locked(site.state / "update.lock", 0):  # The scheduled task is downloading.
            started = time.monotonic()
            code, out, err = site.run("pending")
            self.assertEqual(code, 0, err)
            self.assertLess(time.monotonic() - started, 30)
            self.assertEqual(out.splitlines()[0], "UPDATE " + second)  # What was downloaded earlier.
            with self.assertRaises(site.app.DesktopError):
                site.app.update(90, .3)
        self.assertFalse((site.state / "releases" / third).exists())
        self.assertEqual(site.app.update(90, 90), third)

    def test_log_holds_only_event_names_and_commit_ids_and_rolls_over(self):
        site = Installation(self)
        site.app.record("window-ready", "f" * 40)
        site.app.record("fetch-failed", r"C:\Users\someone OPENAI_API_KEY=not-a-commit")
        first, second = site.log().splitlines()
        self.assertRegex(first, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ window-ready f{12}$")
        self.assertRegex(second, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ fetch-failed $")
        (site.state / "updates.log").write_bytes(b"x" * (64 * 1024))
        site.app.record("up-to-date", "a" * 40)
        self.assertEqual((site.state / "updates.previous.log").stat().st_size, 64 * 1024)
        self.assertEqual(len(site.log().splitlines()), 1)


@unittest.skipUnless(sys.platform == "win32", "Windows desktop installation")
class DamagedState(unittest.TestCase):
    """Whatever happens to the state files or to an unpacked build, a build nobody approved is
    not run, and the command ends with a message instead of a traceback."""

    def test_unreadable_approval_list_never_runs_the_build_that_is_waiting(self):
        site = Installation(self)
        approve_next(site, "c1")
        self.assertEqual(open_once(self, site), ("stub-c1", ""))
        waiting = site.publish("c2")
        site.app.update(90, 90)
        self.assertEqual(site.app.pending(), waiting)
        for label, content in (("empty", b""), ("NUL bytes", b"\0" * 64), ("an object", b"{}"), ("text", b'"main"'),
                               ("not UTF-8", b"\xff\xfe\x00["), ("no commit IDs", b"[1, null, {}, \"main\"]"),
                               ("truncated", b'["' + waiting[:20].encode())):
            with self.subTest(content=label):
                (site.state / "approved.json").write_bytes(content)
                code, out, err = site.direct("serve", "--port", site.free_port())
                self.assertNotIn("c2", site.proof.read_text().split(), "the build awaiting approval was run")
                self.assertNotIn("Traceback", err)
                if code:
                    self.assertTrue(err.startswith("Process Collector desktop: "), err)
                    self.assertNotIn("READY", out)

    def test_unreadable_side_records_are_ignored(self):
        site = Installation(self)
        first = approve_next(site, "c1")
        for name in ("pending.txt", "failed.json", "known-good.txt", "last-opened.txt"):
            for content in (b"", b"\0" * 40, b"\xff\xfe", b"{", b"[]", b"not a commit"):
                (site.state / name).write_bytes(content)
                self.assertIsNone(site.app.pending())
                self.assertEqual(site.app.failed(), {})
                self.assertIsNone(site.app.known_good())
                self.assertIsNone(site.app.last_opened())
                self.assertEqual(site.app.offer(), "")
        self.assertEqual(site.app.approved(), [first])
        # The scheduled task and the window carry on, and the window records again what it opened.
        (site.state / "last-opened.txt").write_bytes(b"\xff\xfe")
        code, out, err = site.run("update")
        self.assertEqual(code, 0, err)
        self.assertEqual(open_once(self, site), ("stub-c1", ""))
        self.assertEqual(site.app.last_opened(), first)
        self.assertEqual(site.app.update(90, 90), first)

    def test_damaged_build_is_neither_approved_nor_served(self):
        site = Installation(self)
        first = approve_next(site, "c1")
        self.assertEqual(open_once(self, site), ("stub-c1", ""))
        # A downloaded build that lost a file after it was checked cannot be approved.
        waiting = site.publish("c2")
        site.app.update(90, 90)
        (site.state / "releases" / waiting / "web" / "index.html").unlink()
        with self.assertRaises(site.app.DesktopError):
            site.app.approve(waiting)
        self.assertEqual(site.app.approved(), [first])
        self.assertEqual(site.app.update(90, 90), waiting)
        self.assertTrue(site.app.intact(site.state / "releases" / waiting))
        # An approved build whose server file is gone is passed over for the next approved one.
        shutil.rmtree(site.state / "releases" / waiting)
        second = approve_next(site, "c3")
        self.assertEqual(site.app.approved(), [second, first])
        (site.state / "releases" / second / "server.py").unlink()
        self.assertEqual(site.app.approved(), [first])
        self.assertEqual(open_once(self, site), ("stub-c1", ""))
        self.assertEqual(set(site.proof.read_text().split()), {"c1"})


@unittest.skipUnless(sys.platform == "win32", "Windows desktop installation")
class ConcurrentWindows(unittest.TestCase):
    def test_second_window_on_the_same_port_is_refused_and_the_first_keeps_serving(self):
        site = Installation(self)
        approve_next(site, "c1")
        port = site.free_port()
        window = site.launch("serve", "--port", port)
        address = "http://127.0.0.1:" + port + "/"
        self.assertEqual(window.stdout.readline().decode().strip(), "READY " + address)
        token = config(address)["csrf_token"]
        busy = ("Process Collector is still closing its previous session, or is already open in another window. "
                "Wait a few seconds and open it again.")
        # The second launch waits for a window that may be closing (see test_desktop_window_close.py),
        # then says which of the two it is waiting for instead of a general failure.
        started = time.monotonic()
        code, out, err = site.direct("serve", "--port", port)
        self.assertGreaterEqual(time.monotonic() - started, site.app.WINDOW_PATIENCE - 1)
        self.assertNotEqual(code, 0)
        self.assertEqual(out.strip(), "ERROR " + busy)
        self.assertEqual(err.strip(), "Process Collector desktop: " + busy)
        self.assertIn("window-busy", site.log())
        # A newer build approved meanwhile is not started beside the open window either: the
        # refusal comes before any build is chosen, checked or run.
        approve_next(site, "c2")
        with mock.patch.dict(os.environ, {"DESKTOP_QA_WINDOW_PATIENCE": "1"}):
            for _ in range(2):
                code, out, err = site.run("serve", "--port", port)
                self.assertNotEqual(code, 0)
                self.assertEqual(out.strip(), "ERROR " + busy)
        self.assertEqual(site.log().count("window-busy"), 3)
        self.assertNotIn("c2", site.proof.read_text().split(), "a second launch ran a build beside the open window")
        self.assertEqual(config(address)["csrf_token"], token, "the first window's server was replaced")
        self.assertEqual(site.log().count("window-ready"), 1)
        self.assertNotIn("startup-", site.log())
        self.assertEqual(site.app.failed(), {})
        self.assertEqual(site.close(window), "")
        self.assertEqual(open_once(self, site), ("stub-c2", ""))


class FreshClone(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "Windows desktop installation")
    def test_fixture_needs_no_existing_local_folder(self):
        with tempfile.TemporaryDirectory() as fresh:
            clone = Path(fresh) / "checkout"
            (clone / "desktop").mkdir(parents=True)
            shutil.copyfile(DESKTOP / "manage.py", clone / "desktop" / "manage.py")
            self.assertFalse((clone / ".local").exists())
            with mock.patch.object(test_desktop_updates, "ROOT", clone):
                site = Installation(self)
                first = site.publish("c1")
                self.assertEqual(site.app.update(90, 90), first)
                self.assertFalse((clone / ".local").exists())
                self.assertTrue(site.state.is_relative_to(site.folder))
                self.assertFalse(site.folder.is_relative_to(clone))
                self.doCleanups()

    def test_readme_says_what_the_desktop_tests_need(self):
        readme = (DESKTOP.parent / "README.md").read_text(encoding="utf-8")
        tests = readme[readme.index("## Offline tests"):]
        self.assertIn("test_desktop_", tests)
        self.assertIn("`git`", tests)


class DesktopHostSources(unittest.TestCase):
    """The window host and the two installer scripts are never run by the suite (they change
    the computer). These checks only compile and parse them, with what is already installed."""

    def test_native_host_compiles_without_warnings(self):
        compiler = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
        sdk = Path.home() / ".nuget" / "packages" / "microsoft.web.webview2" / "1.0.4258.31" / "lib" / "net462"
        references = [sdk / "Microsoft.Web.WebView2.Core.dll", sdk / "Microsoft.Web.WebView2.WinForms.dll"]
        if not compiler.is_file() or not all(reference.is_file() for reference in references):
            self.skipTest("the .NET Framework C# compiler or the WebView2 SDK is not on this computer")
        with tempfile.TemporaryDirectory() as scratch:
            # The same switches as desktop/install.ps1. The result is discarded, never started.
            result = subprocess.run(
                [str(compiler), "/nologo", "/target:winexe", "/platform:x64", "/optimize+", "/codepage:65001",
                 "/win32icon:" + str(DESKTOP / "ProcessCollector.ico"), "/out:" + str(Path(scratch) / "host.exe"),
                 *("/reference:" + str(reference) for reference in references),
                 "/reference:System.Drawing.dll", "/reference:System.Windows.Forms.dll",
                 str(DESKTOP / "NativeHost.cs")],
                capture_output=True, stdin=subprocess.DEVNULL, timeout=300)
            report = (result.stdout + result.stderr).decode(errors="replace")
            self.assertEqual(result.returncode, 0, report)
            self.assertNotIn("warning", report.lower(), report)
            self.assertTrue((Path(scratch) / "host.exe").is_file())

    def test_installer_scripts_parse(self):
        shell = shutil.which("powershell") or shutil.which("pwsh")
        if not shell:
            self.skipTest("PowerShell is not on this computer")
        # Parse only: nothing in either script is executed.
        check = ("$failed = 0; foreach ($path in $env:DESKTOP_QA_SCRIPTS -split '\\|') { $errors = $null; "
                 "[void][System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$null, [ref]$errors); "
                 "foreach ($problem in $errors) { $failed++; Write-Output ($path + ': ' + $problem) } }; exit $failed")
        scripts = [DESKTOP / "install.ps1", DESKTOP / "register-updates.ps1"]
        self.assertTrue(all(script.is_file() for script in scripts))
        result = subprocess.run(
            [shell, "-NoProfile", "-NonInteractive", "-Command", check], capture_output=True, timeout=300,
            stdin=subprocess.DEVNULL, env={**os.environ, "DESKTOP_QA_SCRIPTS": "|".join(map(str, scripts))})
        self.assertEqual(result.returncode, 0, (result.stdout + result.stderr).decode(errors="replace"))
        # The parser check itself works: a broken script is reported.
        with tempfile.TemporaryDirectory() as scratch:
            broken = Path(scratch) / "broken.ps1"
            broken.write_text("param([switch]$BuildOnly\nif ($BuildOnly { 'x' }\n")
            result = subprocess.run(
                [shell, "-NoProfile", "-NonInteractive", "-Command", check], capture_output=True, timeout=300,
                stdin=subprocess.DEVNULL, env={**os.environ, "DESKTOP_QA_SCRIPTS": str(broken)})
            self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
