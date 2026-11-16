"""The manager's copy of GitHub main never lands on history that is refused.

No network is used: the "remote" is a local repository. Git must be on PATH.
"""
import sys
import unittest

from test_desktop_updates import IDENTITY, Installation, git


@unittest.skipUnless(sys.platform == "win32", "Windows desktop installation")
class CopyOfMain(unittest.TestCase):
    """refs/collector-desktop/main is what the next download must continue from. If it is
    missing (after the documented removal step, or in a fresh clone of an installed checkout)
    it must not be created on a commit that the approved build then refuses: every later
    commit of the real main would be refused against it until the ref was deleted by hand."""

    def setUp(self):
        self.site = Installation(self)
        self.first = self.site.publish("c1")
        self.second = self.site.publish("c2")
        self.site.app.update(90, 90)
        self.site.app.approve(self.second)

    def copy(self):
        return git(self.site.root, "for-each-ref", "--format=%(objectname)", self.site.app.REF)

    def refused_without_a_copy(self, revision):
        site = self.site
        git(site.remote, "update-ref", "refs/heads/main", revision)
        git(site.root, "update-ref", "-d", site.app.REF)
        with self.assertRaises(site.app.DesktopError):
            site.app.update(90, 90)
        self.assertEqual(site.log().splitlines()[-1].split()[1:], ["rejected-not-fast-forward", revision[:12]])
        self.assertEqual(self.copy(), "", "the copy of main was created on history that was refused")
        self.assertEqual(site.app.approved(), [self.second])
        self.assertIsNone(site.app.pending())
        self.assertFalse((site.state / "releases" / revision).exists())

    def real_main_is_accepted_again(self):
        site = self.site
        git(site.remote, "update-ref", "refs/heads/main", self.second)
        self.assertEqual(site.app.update(90, 90), self.second, "main as it was is refused after a refused rewrite")
        self.assertEqual(self.copy(), self.second)
        third = site.publish("c3")
        self.assertEqual(site.app.update(90, 90), third, "the next commit on the real main is refused")
        self.assertEqual(site.app.pending(), third)
        self.assertEqual(self.copy(), third)
        self.assertNotIn("fetch-failed", site.log())
        self.assertFalse(site.proof.exists())

    def test_rewritten_main_does_not_become_the_copy_when_no_copy_exists(self):
        orphan = git(self.site.remote, *IDENTITY, "commit-tree", self.second + "^{tree}", "-m", "Rewritten history")
        self.refused_without_a_copy(orphan)
        self.real_main_is_accepted_again()

    def test_older_main_does_not_become_the_copy_when_no_copy_exists(self):
        self.refused_without_a_copy(self.first)
        self.real_main_is_accepted_again()

    def test_first_download_and_a_missing_copy_on_good_history_still_work(self):
        site = self.site
        # Nothing approved and nothing fetched before: there is no anchor, so the first commit is taken.
        fresh = Installation(self)
        only = fresh.publish("f1")
        self.assertEqual(fresh.app.update(90, 90), only)
        self.assertEqual(git(fresh.root, "rev-parse", fresh.app.REF), only)
        # The copy is missing and main continues from the approved build: accepted, and recreated.
        third = site.publish("c3")
        git(site.root, "update-ref", "-d", site.app.REF)
        self.assertEqual(site.app.update(90, 90), third)
        self.assertEqual(self.copy(), third)
        # After a rollback the chosen build is an ancestor of main; main is still accepted without a copy.
        site.app.approve(third)
        self.assertEqual(site.app.rollback(self.second), self.second)
        git(site.root, "update-ref", "-d", site.app.REF)
        self.assertEqual(site.app.update(90, 90), third)
        self.assertEqual(self.copy(), third)
        self.assertIn("not-selected " + third[:12], site.log())


if __name__ == "__main__":
    unittest.main()
