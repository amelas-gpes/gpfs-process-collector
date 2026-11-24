"""Which code is this? A build can be named, and the name follows it into what it produces.

A packaged release carries release.json beside its files; the server reports that commit (or,
for a working tree, "dev+" and a source hash); the source hash does not depend on line endings.
No network or provider is used.
"""
import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
import urllib.request



APP = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("collector_release_identity_server", APP / "server.py")
server = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = server
spec.loader.exec_module(server)
build_spec = importlib.util.spec_from_file_location("collector_release_identity_build", APP / "runtime_build.py")
runtime_build = importlib.util.module_from_spec(build_spec)
build_spec.loader.exec_module(runtime_build)

COMMIT = "0123456789abcdef0123456789abcdef01234567"


class SourceHash(unittest.TestCase):
    """build_id names the served source. A working tree checked out with Windows line endings
    and a git-archive release of the same commit (always LF) are the same source."""

    def tree(self, root, ending):
        files = {"server.py": "import os\nprint('x')\n", "FOUNDATION.md": "# Rules\n\ntext\n",
                 "web/index.html": "<!doctype html>\n<title>x</title>\n", "web/app.js": "(() => {\n  run();\n})();\n",
                 "web/style.css": "body {\n  margin: 0;\n}\n", "web/assets/gpfs-logo.svg": "<svg>\n</svg>\n"}
        for name, content in files.items():
            path = Path(root) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content.replace("\n", ending).encode("utf-8"))
        return Path(root)

    def test_same_source_has_one_identity_whatever_its_line_endings(self):
        with tempfile.TemporaryDirectory() as unix, tempfile.TemporaryDirectory() as windows:
            archived, checked_out = self.tree(unix, "\n"), self.tree(windows, "\r\n")
            self.assertNotEqual((archived / "web" / "app.js").read_bytes(), (checked_out / "web" / "app.js").read_bytes())
            identity = runtime_build.build_id(archived)
            self.assertRegex(identity, r"^[0-9a-f]{64}$")
            self.assertEqual(runtime_build.build_id(checked_out), identity,
                             "a CRLF working tree and an LF release of the same source were named differently")
            # A mixed tree (some files converted, some not) is still the same source.
            (checked_out / "server.py").write_bytes((archived / "server.py").read_bytes())
            self.assertEqual(runtime_build.build_id(checked_out), identity)

    def test_any_other_difference_still_changes_the_identity(self):
        with tempfile.TemporaryDirectory() as root:
            tree = self.tree(root, "\n")
            identity = runtime_build.build_id(tree)
            changes = {"web/app.js": b"(() => {\n  run2();\n})();\n",            # different text
                       "web/style.css": b"body {\n\n  margin: 0;\n}\n",           # an added empty line
                       "web/index.html": b"<!doctype html>\n<title>x</title>",    # the final line end removed
                       "server.py": b"import os\rprint('x')\n"}                   # a lone CR: Git converts only CRLF
            for name, content in changes.items():
                with self.subTest(file=name):
                    original = (tree / name).read_bytes()
                    (tree / name).write_bytes(content)
                    self.assertNotEqual(runtime_build.build_id(tree), identity)
                    (tree / name).write_bytes(original)
                    self.assertEqual(runtime_build.build_id(tree), identity)
            # A served file going missing is a different source.
            original = (tree / "web" / "app.js").read_bytes()
            (tree / "web" / "app.js").unlink()
            self.assertNotEqual(runtime_build.build_id(tree), identity)
            (tree / "web" / "app.js").write_bytes(original)
            self.assertEqual(runtime_build.build_id(tree), identity)

    def test_files_the_server_does_not_serve_leave_the_identity_alone(self):
        # iCloud drops conflict copies ("app 2.js") into a synced folder, macOS leaves "._" files on some
        # drives, and drafts lie around. None is ever served, so none may change the build or make a
        # running server report that its files have changed.
        with tempfile.TemporaryDirectory() as root:
            tree = self.tree(root, "\n")
            identity = runtime_build.build_id(tree)
            for name in ("web/app 2.js", "web/assets/gpfs-logo 2.svg", "web/._app.js", "web/app copy.js", "web/new.js"):
                with self.subTest(file=name):
                    (tree / name).parent.mkdir(parents=True, exist_ok=True)
                    (tree / name).write_bytes(b"stray\n")
                    self.assertEqual(runtime_build.build_id(tree), identity)
                    (tree / name).unlink()

    def test_the_hashed_page_files_are_exactly_the_files_the_server_serves(self):
        self.assertEqual(set(runtime_build.WEB_FILES), {name for name, _ in server.STATIC_FILES.values()})


class ReleaseIdentity(unittest.TestCase):
    """server.release_identity: the commit of a packaged release, else the working tree's hash."""

    def folder(self, root, name=COMMIT, content=None):
        release = Path(root) / name
        release.mkdir()
        if content is not None:
            (release / "release.json").write_bytes(content if isinstance(content, bytes) else json.dumps(content).encode())
        return release

    def test_release_folder_is_named_by_its_commit(self):
        with tempfile.TemporaryDirectory() as root:
            release = self.folder(root, content={"commit": COMMIT, "staged_at": "2026-11-13T09:30:00Z"})
            self.assertEqual(server.release_identity(release, "f" * 64),
                             {"build": COMMIT[:12], "release_commit": COMMIT, "release_staged_at": "2026-11-13T09:30:00Z"})

    def test_anything_else_is_a_working_tree_named_by_its_source_hash(self):
        dev = {"build": "dev+" + "f" * 12, "release_commit": "", "release_staged_at": ""}
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(server.release_identity(self.folder(root, "plain"), "f" * 64), dev)
            cases = {"empty": b"", "not JSON": b"{", "a list": b"[]", "not UTF-8": b"\xff\xfe", "no commit": b"{}",
                     "short commit": json.dumps({"commit": COMMIT[:12]}).encode(),
                     "upper case": json.dumps({"commit": COMMIT.upper()}).encode(),
                     "a branch name": json.dumps({"commit": "main"}).encode(),
                     "not text": json.dumps({"commit": 7}).encode()}
            for number, (label, content) in enumerate(cases.items()):
                with self.subTest(content=label):
                    self.assertEqual(server.release_identity(self.folder(root, "case%d" % number, content), "f" * 64), dev)
            # A release.json that was copied into another folder does not rename that folder's code.
            copied = self.folder(root, "edited-copy", {"commit": COMMIT, "staged_at": "2026-11-13T09:30:00Z"})
            self.assertEqual(server.release_identity(copied, "f" * 64), dev)
            # An unusable date is left out; the commit still names the build.
            odd = self.folder(root, content={"commit": COMMIT, "staged_at": "yesterday <b>"})
            self.assertEqual(server.release_identity(odd, "f" * 64),
                             {"build": COMMIT[:12], "release_commit": COMMIT, "release_staged_at": ""})


class ReportedIdentity(unittest.TestCase):
    """The running server says which build it is: in /api/config and in its start row."""

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        client = server.OpenAIClient({"OPENAI_API_KEY": "sk-test-sentinel-not-a-real-credential"})
        self.httpd = server.InterviewServer(("127.0.0.1", 0), server.Handler, client=client,
                                            documents_root=self.root / "documents", knowledge_settings={})
        self.addCleanup(self.httpd.server_close)

    def config(self):
        import threading
        worker = threading.Thread(target=self.httpd.handle_request, daemon=True)
        worker.start()
        with urllib.request.urlopen("http://127.0.0.1:%d/api/config" % self.httpd.server_port, timeout=10) as reply:
            answer = json.load(reply)
        worker.join(10)
        return answer

    def start_row(self):
        self.httpd.record_event("start", parent_pid=1, build_id=self.httpd.build_id)
        return json.loads((self.root / "server-lifecycle.jsonl").read_text(encoding="utf-8").splitlines()[-1])

    def test_working_tree_reports_its_source_hash(self):
        answer = self.config()
        self.assertEqual(answer["build"], "dev+" + self.httpd.build_id[:12])
        self.assertEqual((answer["release_commit"], answer["release_staged_at"]), ("", ""))
        self.assertEqual(answer["version"], server.VERSION)
        row = self.start_row()
        self.assertEqual(row["build_id"], self.httpd.build_id)
        self.assertNotIn("commit", row)

    def test_packaged_release_reports_its_commit(self):
        release = self.root / COMMIT
        release.mkdir()
        (release / "release.json").write_text(json.dumps({"commit": COMMIT, "staged_at": "2026-11-13T09:30:00Z"}))
        self.httpd.release = server.release_identity(release, self.httpd.build_id)
        answer = self.config()
        self.assertEqual((answer["build"], answer["release_commit"], answer["release_staged_at"]),
                         (COMMIT[:12], COMMIT, "2026-11-13T09:30:00Z"))
        row = self.start_row()
        self.assertEqual(row["commit"], COMMIT)
        # Only the start row carries it; the fields of other events are unchanged.
        self.httpd.record_event("exit", reason="serve_forever_returned")
        last = json.loads((self.root / "server-lifecycle.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertNotIn("commit", last)


if __name__ == "__main__":
    unittest.main()
