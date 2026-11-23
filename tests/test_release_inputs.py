import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import check_release_inputs as gate


class ReleaseInputs(unittest.TestCase):
    def test_scanner_reports_only_names_and_checks_the_staged_snapshot(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"GIT_CONFIG_COUNT": "0"}):
            repo = Path(folder)
            subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
            credential = "sk-proj-" + "a" * 48
            (repo / "sample.txt").write_text(credential)
            (repo / ".env.local").write_text("placeholder")
            (repo / ".env.example").write_text("OPENAI_API_KEY=")
            subprocess.run(["git", "add", "-f", "sample.txt", ".env.example", ".env.local"], cwd=repo, check=True)
            (repo / "sample.txt").write_text("unstaged replacement")
            self.assertEqual(gate.credential_files(repo), {".env.local", "sample.txt"})
            subprocess.run(["git", "rm", "--cached", ".env.local"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "add", "sample.txt"], cwd=repo, check=True)
            self.assertEqual(gate.credential_files(repo), set())

    def test_unpinned_or_empty_manifests_cannot_pass_a_version_specific_check(self):
        for content in ("", "# A note", "pypdf>=6.10", "pypdf==6.*", "-r more.txt"):
            with self.subTest(content=content), self.assertRaises(ValueError):
                gate.pinned_packages(content)

    def test_advisory_queries_cover_each_exact_version_at_both_blocking_severities(self):
        packages = gate.pinned_packages("# Document readers\npypdf==6.21.4\net_xmlfile==2.0.0\n")
        queries = []

        def lookup(pins, severity):
            queries.append((pins, severity))
            return ["GHSA-fixture"] if severity == "critical" else []

        self.assertEqual(gate.blocking_advisories(packages, lookup), {"GHSA-fixture"})
        self.assertEqual(queries, [
            (["pypdf@6.21.4", "et-xmlfile@2.0.0"], "high"),
            (["pypdf@6.21.4", "et-xmlfile@2.0.0"], "critical"),
        ])
        self.assertEqual(gate.blocking_advisories(packages, lambda *_: []), set())

        def unavailable(*_):
            raise ConnectionError("advisory service unavailable")

        with self.assertRaises(ConnectionError):
            gate.blocking_advisories(packages, unavailable)
