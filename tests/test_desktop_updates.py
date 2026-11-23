"""Windows desktop integration with a disposable, local-only remote. No network is used."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.request import ProxyHandler, build_opener


ROOT = Path(__file__).resolve().parents[1]
IDENTITY = ("-c", "user.name=Desktop QA", "-c", "user.email=qa@localhost",
            "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false")

# Redirect the two machine-specific inputs of desktop/manage.py to the fixture: the remote,
# and the owner's optional trusted-signer list (absent unless a test writes one). A test may
# also shorten the minutes a window must stay open before its build counts as known to work,
# and the seconds a new window waits for one that is still closing.
SETUP = (
    "import importlib.util,os,sys; from pathlib import Path; "
    "spec=importlib.util.spec_from_file_location('desktop_manage',sys.argv.pop(1)); "
    "app=importlib.util.module_from_spec(spec); spec.loader.exec_module(app); "
    "app.REMOTE=sys.argv.pop(1); app.SIGNERS=Path(sys.argv.pop(1)); "
    "app.KNOWN_GOOD_AFTER=float(os.environ.get('DESKTOP_QA_KNOWN_GOOD_AFTER',getattr(app,'KNOWN_GOOD_AFTER',0))); "
    "app.WINDOW_PATIENCE=float(os.environ.get('DESKTOP_QA_WINDOW_PATIENCE',getattr(app,'WINDOW_PATIENCE',0))); "
    "app.cli()"
)

# A stand-in application with the entry points desktop/manage.py hosts. Importing it appends
# its mark to the proof file, so any execution of a downloaded release is visible to a test.
STUB = r'''
import argparse, json, secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
APP_DIR = Path(__file__).resolve().parent
MARK = "__MARK__"
with open(r"__PROOF__", "a", encoding="ascii") as proof:
    proof.write(MARK + "\n")
def load_settings():
    return {}
class OpenAIClient:
    def __init__(self, settings):
        pass
class InterviewServer(ThreadingHTTPServer):
    def __init__(self, address, handler, client=None, documents_root=None, knowledge_root=None,
                 knowledge_settings=None):
        self.build_id = "stub-" + MARK
        self.csrf_token = secrets.token_urlsafe(16)
        super().__init__(address, handler)
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass
    def do_GET(self):
        body = json.dumps({"app_id": "voice-interviewer", "build_id": self.server.build_id,
                           "csrf_token": self.server.csrf_token}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int)
    server = InterviewServer(("127.0.0.1", parser.parse_args().port), Handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()
'''


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], input="", text=True).strip()


def config(address):
    with build_opener(ProxyHandler({})).open(address + "api/config", timeout=10) as reply:
        return json.load(reply)


class Installation:
    """A throwaway checkout holding a copy of desktop/manage.py, and the local 'GitHub' it fetches."""

    def __init__(self, case):
        # The synthetic repositories use their own configuration, even when the test
        # runner supplies Git credentials or the user's profile installs a signing hook.
        case.enterContext(patch.dict(os.environ, {
            "GIT_CONFIG_COUNT": "0",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        }))
        folder = tempfile.TemporaryDirectory(prefix="update-qa-")
        case.addCleanup(folder.cleanup)
        self.case, self.folder = case, Path(folder.name).resolve()
        self.remote, self.root = self.folder / "remote", self.folder / "installed"
        self.proof = self.folder / "proof.txt"
        self.signers = self.folder / "trusted" / "allowed_signers"
        for repo in (self.remote, self.root):
            repo.mkdir()
            git(repo, "init", "--quiet", "-b", "main")
        self.manager = self.root / "desktop" / "manage.py"
        self.manager.parent.mkdir(exist_ok=True)
        shutil.copyfile(ROOT / "desktop" / "manage.py", self.manager)
        (self.root / ".env.local").write_text("OPENAI_API_KEY=synthetic-offline-fixture\n")
        self.state = self.root / ".local" / "desktop"
        # The same copy, loaded here, for direct calls to its functions.
        spec = importlib.util.spec_from_file_location("desktop_manage_fixture", self.manager)
        self.app = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.app)
        self.app.REMOTE, self.app.SIGNERS = str(self.remote), self.signers
        self.app.RELEASES.mkdir(parents=True, exist_ok=True)

    def publish(self, mark, source=STUB, subject=None, key=None, files=None):
        """Commit a new revision of the stand-in application to the remote's main branch."""
        (self.remote / "web").mkdir(exist_ok=True)
        (self.remote / "web" / "index.html").write_text("<!doctype html><title>stub</title>\n")
        (self.remote / "server.py").write_text(
            source.replace("__MARK__", mark).replace("__PROOF__", str(self.proof)))
        for name, content in (files or {}).items():
            (self.remote / name).parent.mkdir(parents=True, exist_ok=True)
            (self.remote / name).write_text(content)
        git(self.remote, "add", "-A")
        git(self.remote, *IDENTITY, *self.signing(key), "commit", "--quiet", *(["-S"] if key else []),
            "-m", subject or "Synthetic release " + mark)
        head = self.remote / ".git" / "refs" / "heads" / "main"  # Saves a process per commit.
        return head.read_text().strip() if head.is_file() else git(self.remote, "rev-parse", "HEAD")

    def key(self, name):
        """A throwaway SSH signing key. Returns the private key path."""
        tool = shutil.which("ssh-keygen")
        if not tool and shutil.which("git"):
            bundled = Path(shutil.which("git")).resolve().parents[1] / "usr" / "bin" / "ssh-keygen.exe"
            tool = str(bundled) if bundled.is_file() else None
        if not tool:
            self.case.skipTest("ssh-keygen is not available to create a test signing key")
        path = self.folder / "keys" / name
        path.parent.mkdir(exist_ok=True)
        subprocess.run([tool, "-q", "-t", "ed25519", "-N", "", "-C", name, "-f", str(path)],
                       check=True, capture_output=True, input=b"")
        return path

    @staticmethod
    def signing(key):
        return ("-c", "gpg.format=ssh", "-c", "user.signingkey=" + str(key)) if key else ()

    def trust(self, *keys):
        """Write the owner's trusted-signer list, as the documentation describes it."""
        self.signers.parent.mkdir(exist_ok=True)
        self.signers.write_text("".join(
            "owner@example.test " + key.with_suffix(".pub").read_text() for key in keys))

    def log(self):
        path = self.state / "updates.log"
        return path.read_text(encoding="ascii") if path.is_file() else ""

    def launch(self, *args, remote=None, cwd=None, setup=SETUP):
        environment = os.environ.copy()
        environment.pop("OPENAI_API_KEY", None)
        process = subprocess.Popen(
            [sys.executable, "-I", "-B", "-c", setup, str(self.manager), str(remote or self.remote),
             str(self.signers), *args],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment,
            cwd=cwd or self.root,
        )
        self.case.addCleanup(lambda: process.kill() if process.poll() is None else None)
        return process

    def run(self, *args, remote=None, cwd=None, setup=SETUP):
        """Run one manage.py command to completion, as the scheduled task or the window does."""
        process = self.launch(*args, remote=remote, cwd=cwd, setup=setup)
        out, err = process.communicate(timeout=90)
        return process.returncode, out.decode("utf-8"), err.decode(errors="replace")

    def direct(self, *args):
        """Run the installed manage.py itself, with its own error handling, as the window does.

        Its remote and signer list are then the real ones, so only commands that use neither
        (they never fetch and never check a signature) may be run this way.
        """
        assert args[0] in ("serve", "rollback", "hold", "resume"), args
        environment = os.environ.copy()
        environment.pop("OPENAI_API_KEY", None)
        result = subprocess.run([sys.executable, "-I", "-B", str(self.manager), *args], input=b"", capture_output=True,
                                env=environment, cwd=self.root, timeout=180)
        return result.returncode, result.stdout.decode("utf-8"), result.stderr.decode(errors="replace")

    @staticmethod
    def free_port():
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            return str(probe.getsockname()[1])

    def window(self, remote=None):
        """Open the desktop window's backend. Returns the process and the address it serves."""
        port = self.free_port()
        process = self.launch("serve", "--port", port, remote=remote)
        address = "http://127.0.0.1:" + port + "/"
        self.case.assertEqual(process.stdout.readline().decode().strip(), "READY " + address,
                              "the window backend did not start")
        return process, address

    def close(self, process):
        """Close the window. Returns what its backend printed after the READY line."""
        out, err = process.communicate(timeout=90)
        self.case.assertEqual(process.returncode, 0, err.decode(errors="replace"))
        return out.decode("utf-8")


@unittest.skipUnless(sys.platform == "win32", "Windows desktop installation")
class DesktopUpdateSafety(unittest.TestCase):
    """Downloading a build and running it are separate: only the user's approval joins them."""

    def test_scheduled_update_downloads_without_running_anything(self):
        site = Installation(self)
        first = site.publish("c1")
        code, _, err = site.run("update")
        self.assertEqual(code, 0, err)
        self.assertFalse(site.proof.exists(), "the scheduled update ran code it had just downloaded")
        self.assertTrue((site.state / "releases" / first / "server.py").is_file())
        self.assertEqual(site.app.pending(), first)
        self.assertEqual(site.app.approved(), [])
        self.assertIn("release-staged " + first[:12], site.log())
        # The checkout's working tree is left alone: only state under .local changed.
        self.assertEqual(sorted(item.name for item in site.root.iterdir()),
                         [".env.local", ".git", ".local", "desktop"])
        self.assertFalse(git(site.root, "ls-files"))

    def test_window_launch_never_runs_a_build_nobody_approved(self):
        site = Installation(self)
        first = site.publish("c1")
        refusal = "ERROR No Process Collector build has been approved to run yet."
        code, out, _ = site.run("serve", "--port", site.free_port())
        self.assertFalse(site.proof.exists(), "opening the window ran a build that nobody approved")
        self.assertNotEqual(code, 0)
        self.assertEqual(out.strip(), refusal)  # The reason, in place of the READY line.
        # Downloading it first changes nothing: it still waits for the user's decision.
        self.assertEqual(site.run("update")[0], 0)
        self.assertEqual(site.app.pending(), first)
        code, out, _ = site.run("serve", "--port", site.free_port())
        self.assertFalse(site.proof.exists(), "opening the window ran a build that nobody approved")
        self.assertNotEqual(code, 0)
        self.assertEqual(out.strip(), refusal)

    def test_window_keeps_the_approved_build_until_the_user_switches(self):
        site = Installation(self)
        first = site.publish("c1")
        code, offer, err = site.run("pending")  # The window downloads, then asks.
        self.assertEqual((code, offer.splitlines()[0]), (0, "FIRST " + first), err)
        self.assertEqual(site.run("approve", first)[0], 0)
        self.assertFalse(site.proof.exists(), "recording an approval must not run anything")
        self.assertEqual(json.loads((site.state / "approved.json").read_text()), [first])
        self.assertIn("release-approved " + first[:12], site.log())
        window, address = site.window()
        self.assertEqual(config(address)["build_id"], "stub-c1")

        second = site.publish("c2")
        # Only the build that was downloaded and offered can be approved.
        for revision in (second, first, "0" * 40, "main", ""):
            with self.assertRaises(site.app.DesktopError):
                site.app.approve(revision)
        self.assertEqual(site.app.approved(), [first])
        # The scheduled task downloads the newer commit while the window is open.
        self.assertEqual(site.run("update")[0], 0)
        self.assertEqual(config(address)["build_id"], "stub-c1")
        site.close(window)
        self.assertEqual(site.app.approved(), [first])
        # Reopening shows the question; until it is answered Yes the approved build is served.
        offer = site.app.offer()
        self.assertEqual(offer.splitlines()[0], "UPDATE " + second)
        self.assertIn("Switch to this build now?", offer)
        window, address = site.window()
        self.assertEqual(config(address)["build_id"], "stub-c1")
        site.close(window)
        self.assertEqual(set(site.proof.read_text().split()), {"c1"}, "the unapproved build was run")

        self.assertEqual(site.run("approve", second)[0], 0)
        self.assertEqual(json.loads((site.state / "approved.json").read_text()), [second, first])
        self.assertIn("release-approved " + second[:12], site.log())
        self.assertEqual(site.app.offer(), "")
        window, address = site.window()
        self.assertEqual(config(address)["build_id"], "stub-c2")
        site.close(window)

    def test_release_opened_before_approvals_existed_stays_pinned(self):
        # Earlier versions ran whatever was staged and kept current.json. Only the release the
        # window actually opened is carried over; a newer staged head still needs approval.
        site = Installation(self)
        first = site.publish("c1")
        site.app.update(90, 90)
        (site.state / "pending.txt").unlink()
        (site.state / "last-opened.txt").write_text(first)
        second = site.publish("c2")
        site.app.update(90, 90)
        (site.state / "current.json").write_text(json.dumps([second, first]))
        self.assertEqual(site.app.approved(), [first])
        self.assertEqual(site.app.pending(), second)
        window, address = site.window()
        self.assertEqual(config(address)["build_id"], "stub-c1")
        site.close(window)
        self.assertEqual(site.proof.read_text().split(), ["c1"])

    def test_fallback_of_the_earlier_scheme_is_not_deleted_before_the_first_approval(self):
        # Earlier versions kept two releases in current.json: the one they ran and its fallback.
        site = Installation(self)
        first = site.publish("c1")
        site.app.update(90, 90)
        (site.state / "last-opened.txt").write_text(first)
        second = site.publish("c2")
        site.app.update(90, 90)
        (site.state / "pending.txt").unlink()
        (site.state / "last-opened.txt").write_text(second)
        listed = site.state / "current.json"
        listed.write_text(json.dumps([second, first]))

        def unpacked():
            return {item.name for item in (site.state / "releases").iterdir()}

        # The scheduled task's first runs after the upgrade: nothing new, then a new commit.
        self.assertEqual(site.run("update")[0], 0)
        self.assertEqual(unpacked(), {first, second}, "the unattended download deleted the earlier fallback")
        third = site.publish("c3")
        self.assertEqual(site.run("update")[0], 0)
        self.assertEqual(unpacked(), {first, second, third})
        # Kept is not approved: only the build the window opened may run, and nothing was run.
        self.assertEqual(site.app.approved(), [second])
        self.assertEqual(site.app.pending(), third)
        with self.assertRaises(site.app.DesktopError):
            site.app.rollback(first)
        self.assertFalse(site.proof.exists())
        # An unreadable list keeps nothing and stops nothing.
        for content in (b"", b"{}", b"\xff\xfe", b'"' + first.encode() + b'"', b'[3, null, "main"]'):
            listed.write_bytes(content)
            self.assertEqual(site.app.earlier_scheme(), [])
        listed.write_text(json.dumps([second, first]))
        self.assertEqual(site.app.earlier_scheme(), [second, first])
        # From the owner's first decision on, the usual rule applies: what is approved is kept.
        site.app.approve(third)
        self.assertEqual(site.app.earlier_scheme(), [])
        site.app.update(90, 90)
        self.assertEqual(unpacked(), {second, third})
        self.assertEqual(site.app.approved(), [third, second])
        self.assertFalse(site.proof.exists())

    def test_question_names_the_build_and_quotes_its_description_as_plain_text(self):
        site = Installation(self)
        hostile = "Routine fix " + chr(0x202E) + chr(27) + "[2J" + chr(7) + "x" * 300
        first = site.publish("c1", subject=hostile)
        site.app.update(90, 90)
        # Offline, the build that was already downloaded is still offered.
        code, offer, err = site.run("pending", remote=site.folder / "missing-remote")
        self.assertEqual(code, 0, err)
        self.assertEqual(offer, site.app.offer())
        lines = offer.splitlines()
        self.assertEqual(lines[0], "FIRST " + first)
        self.assertIn("Build " + first[:12] + " from " + git(site.remote, "log", "-1", "--format=%cs"), lines)
        self.assertIn('Its author describes it as: "Routine fix', offer)
        self.assertIn("It has not been run.", offer)
        self.assertIn("Signature: not checked", offer)
        self.assertIn("Run this build now?", offer)
        self.assertTrue(all(character.isprintable() for line in lines for character in line), offer)
        self.assertLess(max(map(len, lines)), 200)
        self.assertFalse(site.proof.exists())

    def test_rewritten_or_older_main_is_refused(self):
        site = Installation(self)
        first = site.publish("c1")
        second = site.publish("c2")
        site.app.update(90, 90)
        site.app.approve(second)

        def refused(revision, forget, waiting=None):
            git(site.remote, "update-ref", "refs/heads/main", revision)
            if forget:
                # Even with no memory of what was fetched before, the approved build is the anchor.
                git(site.root, "update-ref", "-d", site.app.REF)
            with self.assertRaises(site.app.DesktopError):
                site.app.update(90, 90)
            # The log names the commit that was refused. It does not look like a failed download.
            self.assertEqual(site.log().splitlines()[-1].split()[1:], ["rejected-not-fast-forward", revision[:12]])
            self.assertNotIn("fetch-failed", site.log())
            self.assertEqual(site.app.approved(), [second])
            self.assertEqual(site.app.pending(), waiting)
            self.assertEqual(site.app.offer().splitlines()[:1], ["UPDATE " + waiting] if waiting else [])
            self.assertFalse((site.state / "releases" / revision).exists())

        orphan = git(site.remote, *IDENTITY, "commit-tree", second + "^{tree}", "-m", "Rewritten history")
        for revision in (orphan, first):  # Unrelated history forced over main; a downgrade to an ancestor.
            refused(revision, forget=False)
            self.assertEqual(git(site.root, "rev-parse", site.app.REF), second, "the copy of main moved to refused history")
        for revision in (orphan, first):
            refused(revision, forget=True)
        # Main as it was is accepted again, and so is the next commit on it.
        git(site.remote, "update-ref", "refs/heads/main", second)
        self.assertEqual(site.app.update(90, 90), second)
        third = site.publish("c3")
        self.assertEqual(site.app.update(90, 90), third)
        # A rewrite of what was downloaded but not approved yet is refused as well, although it
        # continues from the approved build. The downloaded build stays the one on offer.
        sibling = git(site.remote, *IDENTITY, "commit-tree", third + "^{tree}", "-p", second, "-m", "Rewritten update")
        refused(sibling, forget=False, waiting=third)
        self.assertEqual(git(site.root, "rev-parse", site.app.REF), third)
        git(site.remote, "update-ref", "refs/heads/main", third)
        self.assertEqual(site.app.update(90, 90), third)
        self.assertFalse(site.proof.exists())

    def test_failed_staging_is_logged_with_its_revision_and_never_offered(self):
        site = Installation(self)
        broken = site.publish("c1", source=STUB + "\ndef unfinished(:\n")
        with self.assertRaises(site.app.DesktopError):
            site.app.update(90, 90)
        self.assertIn("staging-failed " + broken[:12], site.log())
        # The check reads the unpacked files; it needs the page as well as the server.
        unpacked = site.folder / "unpacked"
        unpacked.mkdir()
        (unpacked / "server.py").write_text("raise SystemExit('this file must only be compiled')\n")
        with self.assertRaises(site.app.DesktopError):
            site.app.check_release(unpacked)
        (unpacked / "web").mkdir()
        (unpacked / "web" / "index.html").write_text("<!doctype html>\n")
        site.app.check_release(unpacked)
        self.assertIsNone(site.app.pending())
        self.assertEqual(list((site.state / "releases").iterdir()), [])
        self.assertFalse(site.proof.exists(), "a release that failed its checks was run")

    def test_trusted_signers_are_enforced_once_the_owner_lists_them(self):
        site = Installation(self)
        owner, stranger = site.key("owner"), site.key("stranger")

        def refused(revision):
            with self.assertRaises(site.app.DesktopError):
                site.app.update(90, 90)
            self.assertIn("rejected-untrusted-signature " + revision[:12], site.log())
            self.assertEqual(site.app.offer(), "")
            with self.assertRaises(site.app.DesktopError):
                site.app.approve(revision)

        # With no signer list the user's approval is the only gate, and the question says so.
        tagged = site.publish("tagged")
        site.app.update(90, 90)
        self.assertIn("Signature: not checked", site.app.offer())
        # A list applies to a build that was already downloaded. An empty list trusts
        # nobody; it does not switch the check off.
        git(site.remote, *IDENTITY, *site.signing(stranger), "tag", "-s", "-m", "Not ours", "stranger-1", tagged)
        site.signers.parent.mkdir()
        site.signers.write_text("")
        refused(tagged)
        # Listing the owner's key does not make a stranger's tag count.
        site.trust(owner)
        self.assertEqual(site.app.offer(), "")
        self.assertEqual(site.app.approved(), [])
        # A tag signed by a listed key vouches for the commit it names, whoever committed it.
        git(site.remote, *IDENTITY, *site.signing(owner), "tag", "-s", "-m", "Release", "desktop-1", tagged)
        self.assertEqual(site.app.update(90, 90), tagged)
        self.assertIn("Signature: verified", site.app.offer())
        site.app.approve(tagged)
        # That tag says nothing about later commits, and a stranger's signature is not enough.
        foreign = site.publish("stranger", key=stranger)
        refused(foreign)
        self.assertFalse((site.state / "releases" / foreign).exists())
        genuine = site.publish("owner", key=owner)
        self.assertEqual(site.app.update(90, 90), genuine)
        self.assertEqual(site.app.pending(), genuine)
        self.assertEqual(site.app.approved(), [tagged])
        self.assertTrue(site.app.signed(genuine))
        # Only an SSH signature by a listed key counts. A commit that this computer's
        # OpenPGP verifier calls good and ultimately trusted, so that git verify-commit
        # itself succeeds, is still not a listed signer.
        verifier = site.folder / "openpgp-verifier"
        verifier.write_bytes(
            b'#!/bin/sh\necho "[GNUPG:] NEWSIG"\n'
            b'echo "[GNUPG:] GOODSIG 0123456789ABCDEF Somebody <somebody@example.test>"\n'
            b'echo "[GNUPG:] VALIDSIG 0123456789ABCDEF0123456789ABCDEF01234567 2026-11-13 1700000000 0 4 0 1 10 00'
            b' 0123456789ABCDEF0123456789ABCDEF01234567"\n'
            b'echo "[GNUPG:] TRUST_ULTIMATE 0 pgp"\n')
        git(site.root, "config", "gpg.program", str(verifier))
        headers, _, body = subprocess.check_output(
            ["git", "-C", str(site.root), "cat-file", "commit", tagged]).partition(b"\n\n")
        openpgp = subprocess.run(
            ["git", "-C", str(site.root), "hash-object", "-t", "commit", "-w", "--stdin"], check=True,
            capture_output=True, input=headers + b"\ngpgsig -----BEGIN PGP SIGNATURE-----\n \n iQ\n"
            b" -----END PGP SIGNATURE-----\n\n" + body).stdout.decode().strip()
        verdict = site.app.run_git(["-c", "gpg.minTrustLevel=fully", "verify-commit", openpgp], 20)
        self.assertEqual(verdict.returncode, 0, verdict.stderr)
        self.assertFalse(site.app.signed(openpgp))
        self.assertFalse(site.proof.exists())


@unittest.skipUnless(sys.platform == "win32", "Windows desktop installation")
class DesktopUpdates(unittest.TestCase):
    def test_new_release_offline_launch_and_open_window(self):
        site = Installation(self)
        remote = site.remote
        # Seed the local remote from the sources under test, including edits made since HEAD.
        # This also works in an unpacked release without Git history.
        for module in ROOT.glob("*.py"):
            shutil.copyfile(module, remote / module.name)
        shutil.copyfile(ROOT / "FOUNDATION.md", remote / "FOUNDATION.md")
        shutil.copytree(ROOT / "web", remote / "web")
        shutil.copytree(ROOT / "vendor", remote / "vendor")
        git(remote, "-c", "core.autocrlf=false", "add", ":(top)*.py", "web", "vendor", "FOUNDATION.md")
        git(remote, *IDENTITY, "commit", "--quiet", "-m", "Current Process Collector sources")
        # Produce a second revision of the real application in this private local repository.
        initial = git(remote, "rev-parse", "HEAD")
        git(remote, "read-tree", initial)
        # The public build ID covers served assets. Change a real page script for the new build.
        script = remote / "web" / "theme.js"
        with script.open("ab") as file:
            file.write(b"\n// desktop update smoke test\n")
        git(remote, "-c", "core.autocrlf=false", "add", "web/theme.js")
        tree = git(remote, "write-tree")
        second = git(remote, *IDENTITY, "commit-tree", tree, "-p", initial, "-m", "Synthetic desktop advance")
        git(remote, "update-ref", "refs/heads/main", initial)

        def complete(*command, source=None):
            code, out, err = site.run(*command, remote=source)
            self.assertEqual(code, 0, err)
            return out

        complete("update")
        # Nothing opens until the user has approved the downloaded build in the window.
        self.assertNotEqual(site.run("serve", "--port", site.free_port())[0], 0)
        self.assertTrue(complete("pending").startswith("FIRST " + initial + "\n"))
        complete("approve", initial)
        window, address = site.window()
        old = config(address)
        # The real application names itself by the commit the manager unpacked for the window.
        self.assertEqual((old["build"], old["release_commit"]), (initial[:12], initial))
        git(remote, "update-ref", "refs/heads/main", second)
        complete("update")
        pointer = site.state / "approved.json"
        # The download alone never changes which build runs.
        self.assertEqual(json.loads(pointer.read_text()), [initial])
        self.assertEqual(config(address)["csrf_token"], old["csrf_token"])
        self.assertEqual(config(address)["build_id"], old["build_id"])
        site.close(window)
        offline = site.folder / "missing-remote"
        self.assertTrue(complete("pending", source=offline).startswith("UPDATE " + second + "\n"))
        window, address = site.window(offline)
        self.assertEqual(config(address)["build_id"], old["build_id"])
        site.close(window)
        complete("approve", second, source=offline)
        self.assertEqual(json.loads(pointer.read_text()), [second, initial])
        # Simulate an approved package that passed staging but cannot open here.
        deployed = pointer.parent / "releases" / second / "server.py"
        original_source = deployed.read_bytes()
        deployed.write_text("raise RuntimeError('simulated startup failure')\n")
        window, address = site.window(offline)
        self.assertEqual(config(address)["build_id"], old["build_id"])
        self.assertIn("NOTICE-NEW Running the previous build", site.close(window))
        self.assertIn("release-damaged " + second[:12], site.log())
        deployed.write_bytes(original_source)
        # A build that failed to start is not tried first again by itself, and the window says so.
        window, address = site.window(offline)
        self.assertEqual(config(address)["build_id"], old["build_id"])
        self.assertIn("NOTICE Running the previous build", site.close(window))
        # It is tried again when the user chooses it again.
        self.assertIn(second[:12], complete("rollback", second, source=offline))
        window, address = site.window(offline)
        self.assertNotEqual(config(address)["build_id"], old["build_id"])
        self.assertEqual(site.close(window), "")
        # A bad next release must fail staging before modifying the selection.
        bad_tree = git(remote, "mktree")
        broken = git(remote, *IDENTITY, "commit-tree", bad_tree, "-p", second, "-m", "Broken synthetic release")
        git(remote, "update-ref", "refs/heads/main", broken)
        self.assertNotEqual(site.run("update")[0], 0)
        self.assertEqual(json.loads(pointer.read_text()), [second, initial])
        self.assertEqual(complete("pending", source=offline), "")
        self.assertIn("staging-failed " + broken[:12], site.log())


if __name__ == "__main__":
    unittest.main()
