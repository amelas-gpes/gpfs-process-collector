"""Every way the desktop manager refuses says which way it was: a fixed reason code (and the
commit) in the update log, and one sentence for the person, which the window can show.

No network is used: the "remote" is a local folder. Git must be on PATH.
"""
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

from test_desktop_updates import Installation, config

OFFLINE = ("The download from GitHub did not complete: this computer may be offline, or the connection stalled. "
           "Nothing was changed.")
NO_GIT = ("Git was not found on this computer's PATH. The desktop app needs Git to download and check builds: "
          "install Git for Windows, or add it to PATH, and try again.")
UNREADABLE = ("The list of approved builds (.local\\desktop\\approved.json) cannot be read, so no build was started or "
              "changed. Close Process Collector, delete that file and open it again: the build the window last opened "
              "stays approved, and anything newer asks for approval again.")
PREFIX = "Process Collector desktop: "


def events(site):
    """The update log as [event, commit] pairs, oldest first."""
    return [line.split()[1:] for line in site.log().splitlines()]


def without_git():
    """An environment in which git.exe cannot be found, as on a computer that has no Git."""
    system = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
    return mock.patch.dict(os.environ, {"PATH": system})


@unittest.skipUnless(sys.platform == "win32", "Windows desktop installation")
class FirstRun(unittest.TestCase):
    """With nothing approved and nothing downloaded, the window is told why nothing can open."""

    def test_window_is_told_why_nothing_could_be_downloaded(self):
        site = Installation(self)
        code, out, err = site.run("pending", remote=site.folder / "missing-remote")
        self.assertEqual((code, out), (0, "PROBLEM " + OFFLINE + "\n"), err)
        self.assertEqual(events(site), [["fetch-failed"]])
        # No Git at all is a different reason, and is not logged as a failed download.
        (site.state / "updates.log").unlink()
        with without_git():
            code, out, err = site.run("pending")
        self.assertEqual((code, out), (0, "PROBLEM " + NO_GIT + "\n"), err)
        self.assertEqual(events(site), [["git-missing"]])
        # A build that is refused on a first run: the refusal is the reason.
        site.publish("c1")
        site.signers.parent.mkdir()
        site.signers.write_text("")          # A signer list that trusts nobody.
        code, out, err = site.run("pending")
        self.assertEqual((code, out), (0, "PROBLEM GitHub main is not signed by a trusted signer, so it was not accepted.\n"), err)
        self.assertFalse(site.proof.exists())

    def test_reason_never_replaces_a_question_or_an_approved_build(self):
        site = Installation(self)
        first = site.publish("c1")
        site.app.update(90, 90)
        offline = site.folder / "missing-remote"
        # Downloaded earlier and waiting: offline, the first-run question is still asked.
        code, out, err = site.run("pending", remote=offline)
        self.assertEqual((code, out.splitlines()[0]), (0, "FIRST " + first), err)
        # An approved build opens whatever happened to the download: nothing is printed.
        site.app.approve(first)
        self.assertEqual(site.run("pending", remote=offline)[:2], (0, ""))
        with without_git():
            self.assertEqual(site.run("pending")[:2], (0, ""))
        window, address = site.window(offline)
        self.assertEqual(config(address)["build_id"], "stub-c1")
        site.close(window)
        # On hold there is no failure to report either.
        site.app.hold(True)
        fresh = Installation(self)
        fresh.app.hold(True)
        self.assertEqual(fresh.run("pending")[:2], (0, ""))


@unittest.skipUnless(sys.platform == "win32", "Windows desktop installation")
class ReasonCodes(unittest.TestCase):
    def test_scheduled_download_without_git_says_so(self):
        site = Installation(self)
        site.publish("c1")
        with without_git():
            code, out, err = site.run("update")
        self.assertEqual((code, out, err.strip()), (1, "", PREFIX + NO_GIT))
        self.assertEqual(events(site), [["git-missing"], ["operation-failed"]])
        # Offline is logged as before, and now ends with a sentence instead of an error's name.
        (site.state / "updates.log").unlink()
        code, out, err = site.run("update", remote=site.folder / "missing-remote")
        self.assertEqual((code, err.strip()), (1, PREFIX + OFFLINE))
        self.assertEqual(events(site), [["fetch-failed"], ["operation-failed"]])

    def test_unreadable_approval_list_is_named_and_its_remedy_works(self):
        site = Installation(self)
        first = site.publish("c1")
        site.app.update(90, 90)
        site.app.approve(first)
        window, address = site.window()
        site.close(window)
        listed = site.state / "approved.json"
        for content in (b"", b"\xff\xfe\x00[", b"{}", b'["' + first[:20].encode()):
            with self.subTest(content=content):
                listed.write_bytes(content)
                (site.state / "updates.log").unlink(missing_ok=True)
                code, out, err = site.direct("serve", "--port", site.free_port())
                self.assertEqual((code, out.strip(), err.strip()), (1, "ERROR " + UNREADABLE, PREFIX + UNREADABLE))
                self.assertEqual(events(site), [["approved-list-unreadable"], ["operation-failed"]])
        # The scheduled task says the same, and changes nothing.
        code, out, err = site.run("update")
        self.assertEqual((code, err.strip()), (1, PREFIX + UNREADABLE))
        self.assertEqual(listed.read_bytes(), b'["' + first[:20].encode())
        # What the sentence tells the person to do: the build the window last opened runs again.
        listed.unlink()
        self.assertEqual(site.app.approved(), [first])
        window, address = site.window()
        self.assertEqual(config(address)["build_id"], "stub-c1")
        site.close(window)

    def test_each_refusal_has_its_own_code_before_the_general_one(self):
        site = Installation(self)

        def refused(*command, code_and_commit, sentence):
            (site.state / "updates.log").unlink(missing_ok=True)
            code, out, err = site.direct(*command)
            self.assertEqual((code, err.strip()), (1, PREFIX + sentence), command)
            self.assertEqual(events(site), [code_and_commit, ["operation-failed"]], command)
            return out

        out = refused("serve", "--port", site.free_port(), code_and_commit=["nothing-approved"],
                      sentence="No Process Collector build has been approved to run yet.")
        self.assertEqual(out.strip(), "ERROR No Process Collector build has been approved to run yet.")
        refused("rollback", code_and_commit=["rollback-refused"], sentence="There is no earlier approved build to go back to.")
        first = site.publish("c1")
        site.app.update(90, 90)
        site.app.approve(first)
        refused("rollback", "0123456", code_and_commit=["rollback-refused"],
                sentence="That does not name one build you approved that is still on this computer. "
                         "Approved builds: " + first[:12] + ".")
        # Repair or cleanup holds an exclusive lease across every window's port.
        with site.app.locked(site.state / (first + ".lock"), 0, length=65536):
            out = refused("serve", "--port", site.free_port(), code_and_commit=["build-in-use", first[:12]],
                          sentence="Another desktop operation is in progress.")
        # A download, approval or rollback is under way.
        with site.app.locked(site.state / "update.lock", 0):
            (site.state / "updates.log").unlink()
            with self.assertRaises(site.app.DesktopError):
                site.app.update(90, .3)
            self.assertEqual(events(site), [["update-busy"]])
        # Approvals that are refused name the commit they were asked for.
        second = site.publish("c2")
        (site.state / "updates.log").unlink()
        for revision in (second, first):
            with self.assertRaises(site.app.DesktopError):
                site.app.approve(revision)
        self.assertEqual(events(site), [["approval-refused", second[:12]], ["approval-refused", first[:12]]])
        # Git answering with an error (here: a ref that does not exist) is not a missing Git.
        (site.state / "updates.log").unlink()
        with self.assertRaises(site.app.DesktopError):
            site.app.git(["rev-parse", "--verify", "refs/heads/no-such-branch"], 8)
        self.assertEqual(events(site), [["git-failed"]])
        self.assertFalse(site.proof.exists())

    def test_unexpected_error_is_a_sentence_and_shows_no_path(self):
        site = Installation(self)
        releases = site.state / "releases"
        releases.rmdir()
        releases.write_text("in the way")     # The manager cannot create its folder: an error it does not foresee.
        code, out, err = site.direct("serve", "--port", site.free_port())
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(err.strip(), PREFIX + "The desktop command stopped on an unexpected error (FileExistsError).")
        self.assertNotIn(str(site.root), err)
        self.assertEqual(events(site), [["operation-failed"]])

    def test_guide_explains_every_reason_code_the_manager_logs(self):
        root = Path(__file__).resolve().parents[1]
        manager = (root / "desktop" / "manage.py").read_text(encoding="utf-8")
        guide = (root / "docs" / "DESKTOP.md").read_text(encoding="utf-8")
        import re
        logged = set(re.findall(r'(?:record|failure)\(\s*"([a-z][a-z-]+)"', manager))
        logged |= set(re.findall(r'\("([a-z][a-z-]+)",(?: selected| revision)?\)(?:\)|,)', manager))  # A lock's busy reason.
        logged |= set(re.findall(r'"((?:updates|startup|release)-[a-z-]+)"', manager))        # codes chosen in expressions
        for code in ("git-missing", "git-failed", "update-busy", "build-in-use", "approved-list-unreadable",
                     "nothing-approved", "approval-refused", "rollback-refused", "window-busy", "fetch-failed"):
            self.assertIn(code, logged)
        missing = sorted(code for code in logged if "`" + code + "`" not in guide)
        self.assertEqual(missing, [], "docs/DESKTOP.md does not explain these update-log events")


if __name__ == "__main__":
    unittest.main()
