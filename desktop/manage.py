"""Download GitHub main for review and host the build approved in the Windows desktop window."""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager, redirect_stdout
import hashlib
import importlib.util
import json
import msvcrt
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urljoin
from urllib.request import ProxyHandler, build_opener
import warnings
import zipfile


# Downloading and running are separate. `update` (the scheduled task) and `pending` (the
# window, before it opens) fetch a commit, unpack it and check it statically: nothing they
# fetch is imported or run. `approve` records the user's decision, made in the window, to
# run one downloaded build. `serve` imports approved builds only. One the window has not
# opened before is first started by itself with empty stores (`rehearse`), so a build that
# cannot start here is found before it is given the user's data, and is not tried first
# again (`failed`). `rollback` chooses again among the approved builds, and `hold` stops
# downloads and offers until `resume`.
ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".local" / "desktop"
RELEASES = STATE / "releases"
APPROVED = STATE / "approved.json"
PENDING = STATE / "pending.txt"
LAST_OPENED = STATE / "last-opened.txt"
# Approved builds that could not start on this computer, by commit. `serve` passes over them.
FAILED = STATE / "failed.json"
# The startup check runs an approved build with these variables only: no keys, no tokens.
PLAIN_ENVIRONMENT = {
    "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATH", "PATHEXT", "TEMP", "TMP", "OS",
    "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "USERNAME", "USERDOMAIN", "COMPUTERNAME", "APPDATA",
    "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "COMMONPROGRAMFILES",
    "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE"}
CHECK_SECONDS = 90
# The build last seen working here: its page was requested and its window then stayed open
# for KNOWN_GOOD_AFTER seconds. Opening a build is not enough. This build is never discarded
# by later approvals or downloads, and it is the first fallback and the default `rollback`.
KNOWN_GOOD = STATE / "known-good.txt"
KNOWN_GOOD_AFTER = 300
# While this file exists (`hold`, ended by `resume`) nothing is downloaded, offered or approved.
HOLD = STATE / "hold"
# When the window closes, requests the service has already admitted get this long to finish.
# Then the service ends anyway: nobody is left to receive their answers, and a provider call
# can run for minutes while it holds the window's lock. A new window waits somewhat longer
# than that for the lock before it reports that the previous session is still closing.
DRAIN_SECONDS = 5
WINDOW_PATIENCE = DRAIN_SECONDS + 5
# The hosted application's two SQLite stores, which every build and the checkout's own server
# share, and the module of a build that declares the store formats it opens with the line
# `STORE_FORMATS = (oldest, newest)`. SQLite keeps a store's format in the file.
STORES = (("documents.py", Path("work", "documents", "documents.sqlite3"), "documents saved on this computer were"),
          ("knowledge_graph.py", Path("work", "knowledge", "knowledge.sqlite3"),
           "company knowledge saved on this computer was"))
# A build from before that declaration existed wrote the layout that is now format 1.
UNDECLARED_FORMATS = (0, 1)
REMOTE = "https://github.com/amelas-dev/ai-process-collector.git"
REF = "refs/collector-desktop/main"
# Where a fetch lands. REF, our copy of main, moves to it only when it continues from REF.
INCOMING = "refs/collector-desktop/incoming"
TAGS = "refs/collector-desktop/tags/"
# The owner's optional list of trusted release signers, in OpenSSH allowed-signers format.
# It is kept outside this checkout and outside every release. While it exists, a build is
# accepted only if its commit, or a tag naming that commit, is signed by a listed key.
SIGNERS = Path.home() / ".process-collector" / "allowed_signers"
SHA = re.compile(r"[0-9a-f]{40}")


class DesktopError(Exception):
    pass


class PortUnavailable(DesktopError):
    """The window's port could not be bound. That is this computer's state, not a build's failure."""

    def __init__(self, port):
        super().__init__(f"Port {port} is not available: another program may be using it. Close that program, "
                         "or wait a moment, and reopen Process Collector.")


class GitMissing(DesktopError):
    """git.exe could not be started at all. That is not a failed download."""


def failure(event, message, revision=""):
    """A refusal with its fixed reason code: the code (and the commit it concerns) goes to the
    update log, the sentence to the person. Returns the error for the caller to raise."""
    record(event, revision)
    return DesktopError(message)


class WindowBusy(DesktopError):
    """Another `serve` holds this port's window lock: an open window, or one that is still closing."""

    def __init__(self):
        super().__init__("Process Collector is still closing its previous session, or is already open in another "
                         "window. Wait a few seconds and open it again.")


def record(status, revision=""):
    # Only fixed event names and public Git commit IDs enter this rolling log.
    try:
        with locked(STATE / "log.lock", .5):
            path = STATE / "updates.log"
            if path.is_file() and path.stat().st_size >= 64 * 1024:
                os.replace(path, STATE / "updates.previous.log")
            with path.open("a", encoding="ascii") as log:
                stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                print(stamp, status, revision[:12] if SHA.fullmatch(revision) else "", file=log)
    except (OSError, DesktopError):
        pass


@contextmanager
def locked(path, timeout, busy=(), offset=0, length=1):
    """Windows releases this byte-range lock even when the process is killed.

    `busy` is the reason code (and commit) to log when the lock stays held: see `record`.
    """
    deadline = time.monotonic() + timeout
    with path.open("a+b") as handle:
        handle.seek(offset)
        while True:
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, length)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    if busy:
                        record(*busy)
                    raise DesktopError("Another desktop operation is in progress.")
                time.sleep(.1)
        try:
            yield
        finally:
            handle.seek(offset)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, length)


def stop_tree(process):
    """End a child process and everything it started, without waiting long for any of it."""
    try:
        subprocess.run(
            [os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "taskkill.exe"),
             "/T", "/F", "/PID", str(process.pid)], timeout=10, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        process.kill()  # Covers a taskkill that could not run. Harmless once the child is gone.
        process.wait(2)
    except (OSError, subprocess.TimeoutExpired):
        pass


def run(command, timeout, **options):
    """Run a command to completion, or stop it and all of its children at the timeout.

    git.exe starts helpers (git-remote-https.exe) that inherit its pipes and outlive it when
    only git.exe is killed, so a stalled connection used to hold a caller far beyond its
    timeout. Output therefore goes to files, which no surviving process can keep us waiting
    on, and a timeout stops the whole process tree.
    """
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, stdout=output, stderr=errors,
                                   creationflags=subprocess.CREATE_NO_WINDOW, **options)
        try:
            process.wait(timeout)
        except BaseException:
            stop_tree(process)
            raise
        finally:
            if process.stdin:
                process.stdin.close()
        output.seek(0)
        errors.seek(0)
        return subprocess.CompletedProcess(command, process.returncode, output.read(), errors.read())


def run_git(args, timeout):
    try:
        return run(["git", "-C", str(ROOT), *args], timeout,
                   env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "Never"})
    except FileNotFoundError:
        record("git-missing")
        raise GitMissing("Git was not found on this computer's PATH. The desktop app needs Git to download "
                         "and check builds: install Git for Windows, or add it to PATH, and try again.") from None


def git(args, timeout, event="git-failed"):
    result = run_git(args, timeout)
    if result.returncode:
        if event:
            record(event)
        raise DesktopError("Git could not read the Process Collector main branch.")
    return result.stdout.decode("ascii").strip()


def replace_text(path, text):
    replacement = path.with_suffix(".tmp")
    replacement.write_text(text, encoding="utf-8")
    os.replace(replacement, path)


def approved():
    """Builds the user agreed to run, newest first. Nothing else is ever imported."""
    if APPROVED.is_file():
        try:
            revisions = json.loads(APPROVED.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            revisions = None
        if not isinstance(revisions, list):
            # Never guessed at: an unreadable list approves nothing, and says which file it is.
            raise failure("approved-list-unreadable",
                          "The list of approved builds (.local\\desktop\\approved.json) cannot be read, so no build "
                          "was started or changed. Close Process Collector, delete that file and open it again: the "
                          "build the window last opened stays approved, and anything newer asks for approval again.")
    else:
        # Before approvals were recorded, the window ran whatever had been staged (the
        # head of current.json, which is not a list of approvals). Carry over only the build
        # the window actually opened; anything staged after it waits for a decision.
        revisions = [last_opened()]
    return [sha for sha in revisions if isinstance(sha, str) and SHA.fullmatch(sha)
            and (RELEASES / sha / "server.py").is_file()]


def earlier_scheme():
    """Builds the earlier, self-updating version listed in current.json, until the first approval.

    They are not approved and nothing here runs them. The list only keeps the unattended
    download from deleting, before the owner has decided anything, what that version kept
    as its fallback.
    """
    if APPROVED.is_file():
        return []
    try:
        listed = json.loads((STATE / "current.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return []
    return [sha for sha in listed if isinstance(sha, str) and SHA.fullmatch(sha)] if isinstance(listed, list) else []


def last_opened():
    try:
        sha = LAST_OPENED.read_text(encoding="ascii").strip()
    except (OSError, ValueError):
        return None  # Nothing recorded, or unreadable: the next window that opens records it again.
    return sha if SHA.fullmatch(sha) and (RELEASES / sha / "server.py").is_file() else None


def known_good():
    try:
        sha = KNOWN_GOOD.read_text(encoding="ascii").strip()
    except (OSError, ValueError):
        return None
    return sha if SHA.fullmatch(sha) and (RELEASES / sha / "server.py").is_file() else None


def failed():
    """Approved builds that could not start here: {commit: event}. Unreadable means none."""
    try:
        marks = json.loads(FAILED.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(marks, dict):
        return {}
    return {sha: event for sha, event in marks.items() if SHA.fullmatch(sha) and isinstance(event, str)}


def note_failures(changes):
    """Add ({commit: event}) or clear ({commit: None}) startup failures of builds still on disk."""
    marks = {**failed(), **changes}
    try:
        replace_text(FAILED, json.dumps({sha: event for sha, event in sorted(marks.items())
                                         if event and (RELEASES / sha).is_dir()}) + "\n")
    except OSError:
        pass  # Like the log, this record must never stop a build from being chosen or served.


def pending():
    """The downloaded build that is waiting for the user's decision, if there is one."""
    try:
        sha = PENDING.read_text(encoding="ascii").strip()
    except (OSError, ValueError):
        return None  # Nothing recorded, or unreadable: the next download records it again.
    if SHA.fullmatch(sha) and (RELEASES / sha / "server.py").is_file() and sha not in approved():
        return sha
    return None


def extract_release(archive, destination):
    with zipfile.ZipFile(archive) as source:
        entries = source.infolist()
        if len(entries) > 16000 or sum(item.file_size for item in entries) > 256 * 1024**2:
            raise DesktopError("The release exceeds the desktop archive limits.")
        names = set()
        for item in entries:
            parts = PurePosixPath(item.filename).parts
            name = tuple(part.casefold() for part in parts)
            if (item.filename.startswith("/") or name in names or
                    any(ord(ch) < 32 or ch in '<>"|?*' for ch in item.filename)):
                raise DesktopError("GitHub release contains an unsupported archive path.")
            names.add(name)
            if (not parts or any(x in (".", "..", "/") or "\\" in x or ":" in x
                                 or x.rstrip(" .") != x or Path(x).is_reserved() for x in parts)
                    or parts[0].lower() in {".git", ".local", "work"}
                    or parts[0].lower().startswith(".env") and parts[0] != ".env.example"
                    or stat.S_ISLNK(item.external_attr >> 16)):
                raise DesktopError("GitHub release contains an unsupported archive path.")
            source.extract(item, destination)


def load_server(release):
    spec = importlib.util.spec_from_file_location("collector_desktop_server", release / "server.py")
    app = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = app
    spec.loader.exec_module(app)
    return app


def check_release(release):
    """Static checks only. Nothing in a downloaded release is imported or run here."""
    if not (release / "server.py").is_file() or not (release / "web" / "index.html").is_file():
        raise DesktopError("The GitHub release is missing its desktop entry point.")
    for module in sorted(release.glob("*.py")):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                compile(module.read_bytes(), module.name, "exec", dont_inherit=True)
        except (SyntaxError, ValueError, RecursionError, MemoryError, OverflowError):
            raise DesktopError("The GitHub release contains Python source that does not compile.")


def signed(revision):
    """True only for an SSH signature, on the commit or on a tag naming it, by a listed key."""
    trust = ["-c", "gpg.ssh.allowedSignersFile=" + str(SIGNERS), "-c", "gpg.minTrustLevel=fully"]
    tags = run_git(["for-each-ref", "--points-at", revision, "--format=%(refname)", TAGS], 20)
    names = [] if tags.returncode else tags.stdout.decode("utf-8", "replace").split("\n")
    checks = [["verify-commit", "--raw", revision], *(["verify-tag", "--raw", name] for name in names if name)]
    for check in checks:
        result = run_git([*trust, *check], 20)
        # This is the line OpenSSH prints only when the signing key matches a listed signer.
        if not result.returncode and result.stderr.startswith(b'Good "git" signature for '):
            return True
    return False


def advance(revision):
    """Move our copy of main forward to the commit just fetched, or refuse that commit by name.

    Fetching straight into the copy would make Git refuse rewritten or older history too, but
    then the fetch only fails, as it does offline. Fetched beside the copy and compared here,
    such a main is recorded with its commit ID. Any Git error refuses as well.
    """
    previous = git(["for-each-ref", "--format=%(objectname)", REF], 8)
    if previous == revision:
        return
    # With no copy yet (a first download, or the ref was deleted) the approved build is the
    # anchor. It is tested here, before the copy is created: a copy made on history that
    # `check_provenance` then refuses would refuse the real main from then on.
    anchor = previous or next(iter(approved()), "")
    if anchor and (not SHA.fullmatch(anchor)
                   or run_git(["merge-base", "--is-ancestor", anchor, revision], 20).returncode):
        record("rejected-not-fast-forward", revision)
        raise DesktopError("GitHub main was rewritten or moved backwards, so it was not accepted.")
    git(["update-ref", REF, revision], 8)


def check_provenance(revision, prior):
    """Refuse rewritten or older history and, when the owner lists signers, unsigned builds."""
    if prior and run_git(["merge-base", "--is-ancestor", prior[0], revision], 20).returncode:
        record("rejected-not-fast-forward", revision)
        raise DesktopError("GitHub main does not continue from the approved build, so it was not accepted.")
    if SIGNERS.exists() and not signed(revision):
        record("rejected-untrusted-signature", revision)
        raise DesktopError("GitHub main is not signed by a trusted signer, so it was not accepted.")


def release_manifest(directory):
    files = {}
    for file in directory.rglob("*"):
        relative = file.relative_to(directory).as_posix()
        if file.is_file() and relative != ".desktop-manifest":
            with file.open("rb") as source:
                files[relative] = hashlib.file_digest(source, "sha256").hexdigest()
    return files


def intact(directory):
    path = directory / ".desktop-manifest"
    try:
        return json.loads(path.read_text(encoding="utf-8")) == release_manifest(directory)
    except (ValueError, OSError):
        return False


def stage(revision):
    """Unpack one commit beside the other builds without running any of it."""
    destination = RELEASES / revision
    if destination.is_dir() and intact(destination):
        return
    with tempfile.TemporaryDirectory(dir=STATE, prefix="stage-") as scratch:
        archive = Path(scratch) / "source.zip"
        tree = Path(scratch) / "release"
        git(["archive", "--format=zip", "-o", str(archive), revision], 60)
        extract_release(archive, tree)
        check_release(tree)
        # The build's name, written by the manager and not by the commit, for the application
        # to report: its Settings, saved interviews and exports then say which code made them.
        (tree / "release.json").write_text(json.dumps({
            "commit": revision, "staged_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}) + "\n", encoding="ascii")
        (tree / ".desktop-manifest").write_text(json.dumps(release_manifest(tree)), encoding="utf-8")
        if destination.exists():
            with locked(STATE / (revision + ".lock"), 0, ("build-in-use", revision), length=65536):
                previous = Path(scratch) / "previous"
                destination.rename(previous)
                try:
                    tree.rename(destination)
                except BaseException:
                    previous.rename(destination)
                    raise
            return
        for attempt in range(6):
            try:
                tree.rename(destination)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(.25 * (attempt + 1))


def clean_old_releases(keep):
    for directory in RELEASES.iterdir():
        if not SHA.fullmatch(directory.name) or directory.name in keep:
            continue
        if not directory.is_dir() or directory.is_symlink() or directory.is_junction():
            continue
        try:
            with locked(STATE / (directory.name + ".lock"), 0, length=65536):
                shutil.rmtree(directory)
            (STATE / (directory.name + ".lock")).unlink(missing_ok=True)
        except (DesktopError, OSError):
            pass  # A running window can continue using any older pinned release.


def update(fetch_timeout, lock_timeout):
    """Download GitHub main and unpack it for review. Nothing downloaded is imported or run."""
    with locked(STATE / "update.lock", lock_timeout, ("update-busy",)):
        if HOLD.exists():
            record("on-hold")
            return None
        for orphan in STATE.glob("stage-*"):
            if orphan.is_dir() and not orphan.is_symlink() and not orphan.is_junction():
                shutil.rmtree(orphan, ignore_errors=True)
        # Fetched beside our copy of main, which `advance` then moves forward only.
        refspecs = ["+refs/heads/main:" + INCOMING]
        if SIGNERS.exists():
            # Tags are evidence, never a pointer that is followed: only a tag's signature
            # and the commit it names are used, so a moved tag may simply replace its copy.
            refspecs.append("+refs/tags/*:" + TAGS + "*")
        try:
            # Git has no transfer timeout of its own. Let it give up on a connection that
            # carries almost nothing for most of the time allowed; the timeout stops the rest
            # (a name lookup or a handshake that never completes).
            git(["-c", "http.lowSpeedLimit=1000", "-c", f"http.lowSpeedTime={max(1, int(fetch_timeout * 2 / 3))}",
                 "fetch", "--quiet", "--no-tags", "--no-recurse-submodules", "--no-write-fetch-head",
                 REMOTE, *refspecs], fetch_timeout, event="")
        except GitMissing:
            raise
        except (DesktopError, subprocess.TimeoutExpired):
            record("fetch-failed")
            raise DesktopError("The download from GitHub did not complete: this computer may be offline, or the "
                               "connection stalled. Nothing was changed.") from None
        revision = git(["rev-parse", "--verify", INCOMING + "^{commit}"], 8)
        if not SHA.fullmatch(revision):
            raise failure("git-failed", "Git returned an invalid commit.")
        advance(revision)
        prior = approved()
        if revision in prior[:1]:
            if (RELEASES / revision / ".desktop-manifest").exists() and not intact(RELEASES / revision):
                stage(revision)
            PENDING.unlink(missing_ok=True)
            status = "up-to-date"
        elif revision in prior:
            # After a rollback, main is a build the user approved and then moved away from.
            # It is not offered again; `rollback <commit>` returns to it.
            PENDING.unlink(missing_ok=True)
            status = "not-selected"
        else:
            check_provenance(revision, prior)
            rejected = STATE / "rejected-stage.txt"
            if rejected.is_file() and rejected.read_bytes().strip() == revision.encode("ascii"):
                raise DesktopError("This downloaded build previously failed the static release checks.")
            try:
                stage(revision)
            except (zipfile.BadZipFile, DesktopError) as error:
                if not str(error).startswith(("The GitHub release", "GitHub release", "The release exceeds")) and not isinstance(error, zipfile.BadZipFile):
                    raise
                replace_text(rejected, revision)
                record("staging-failed", revision)
                raise
            except Exception:
                record("staging-failed", revision)
                raise
            status = "awaiting-approval"
            if pending() != revision:
                replace_text(PENDING, revision)
                status = "release-staged"
        clean_old_releases({*prior, *earlier_scheme(), pending(), last_opened(), known_good()})
        record(status, revision)
        return revision


def offer():
    """The question the window asks before a downloaded build is first run, or ''."""
    revision = pending()
    if not revision or HOLD.exists():
        return ""
    prior = approved()
    try:
        check_provenance(revision, prior)
    except DesktopError:
        return ""
    shown = run_git(["log", "-1", "--format=%cs%n%s", revision], 8).stdout.decode("utf-8", "replace")
    date, _, subject = shown.partition("\n")
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", date):
        date = "an unknown date"
    # The subject is whatever the commit's author wrote. Show it as a quotation, in plain
    # printable text of limited length.
    subject = "".join(x if x.isprintable() else " " for x in subject.strip())[:120].strip()
    return "\n".join([
        ("UPDATE " if prior else "FIRST ") + revision,
        "A newer Process Collector build has been downloaded. It has not been run." if prior
        else "Process Collector has downloaded a build from GitHub. It has not been run.",
        "",
        "Build " + revision[:12] + " from " + date,
        'Its author describes it as: "' + (subject or "no description") + '"',
        "Signature: verified against your trusted signers." if SIGNERS.exists()
        else "Signature: not checked (no trusted signers are set up on this computer).",
        "",
        "Switch to this build now? Choose No to keep using the current build." if prior
        else "Run this build now? Choose No to close without running it.",
    ]) + "\n"


def approve(revision):
    """Record the user's decision, made in the window, to run the build it showed them."""
    with locked(STATE / "update.lock", 30, ("update-busy",)):
        if HOLD.exists():
            raise failure("approval-refused", "Updates are on hold. Run `manage.py resume` first.", revision)
        if pending() != revision:
            raise failure("approval-refused", "That build is not waiting for approval. Reopen Process Collector.", revision)
        prior = approved()
        check_provenance(revision, prior)
        try:
            check_release(RELEASES / revision)
        except DesktopError:
            record("staging-failed", revision)  # Damaged since it was downloaded: it is not approved.
            raise
        # Fallbacks: first the build last known to work here, which is always kept, then
        # the build the window last opened and the previous choice.
        anchor = known_good() if known_good() in prior else None
        others = [sha for sha in dict.fromkeys([last_opened(), *prior]) if sha and sha not in (revision, anchor)]
        replace_text(APPROVED, json.dumps([revision, *([anchor] if anchor else []), *others[:2]]) + "\n")
        PENDING.unlink(missing_ok=True)
        note_failures({revision: None})  # Choosing a build again is a request to try it again.
        record("release-approved", revision)


def rollback(revision=""):
    """Choose again among the builds approved earlier and still on this computer: the one
    named (a commit ID or its first 7 or more characters), else the build last known to work
    here, else the previous choice. The window uses it the next time it opens. Nothing is
    downloaded or deleted, and the build left behind stays approved, so naming it returns to it."""
    with locked(STATE / "update.lock", 30, ("update-busy",)):
        choices = approved()
        if revision:
            named = [sha for sha in choices if sha.startswith(revision)] if re.fullmatch(r"[0-9a-f]{7,40}", revision) else []
            if len(named) != 1:
                raise failure("rollback-refused",
                              "That does not name one build you approved that is still on this computer. "
                              "Approved builds: " + (", ".join(sha[:12] for sha in choices) or "none") + ".")
            selected = named[0]
        else:
            anchor = known_good()
            selected = anchor if anchor in choices[1:] else next(iter(choices[1:]), None)
            if not selected:
                raise failure("rollback-refused", "There is no earlier approved build to go back to.")
        try:
            check_stores(RELEASES / selected, ROOT)  # Say so now if that build cannot open the saved data.
        except DesktopError:
            record("older-than-saved-data", selected)
            raise
        replace_text(APPROVED, json.dumps([selected, *(sha for sha in choices if sha != selected)]) + "\n")
        note_failures({selected: None})  # Choosing a build is a request to try it again.
        record("release-selected", selected)
        return selected


def hold(held):
    """Stop, or resume, downloading and offering builds. The approved build keeps running."""
    with locked(STATE / "update.lock", 30, ("update-busy",)):
        if held:
            HOLD.touch()
        else:
            HOLD.unlink(missing_ok=True)
        record("updates-held" if held else "updates-resumed")


def host(release, port, ready, served=None, rehearsal=None):
    """Host one approved build for the window until the window closes.

    With `rehearsal` (an empty folder outside the checkout) the same steps run once as a
    startup check: the build's own settings parser, the server it constructs, its `main()`
    and the /api/config handshake, but on a free port, with a placeholder key and with empty
    stores in that folder. Nothing of the user's is opened, and nothing is announced.
    """
    protocol = sys.stdout
    home = rehearsal or ROOT
    # Use the release's own configuration parser and allowlist once, before
    # starting threads. Private settings stay in this process's memory.
    with (STATE / "server.log").open("a", encoding="utf-8") as startup, redirect_stdout(startup):
        app = load_server(release)
        release_root = app.APP_DIR
        try:
            app.APP_DIR = home
            settings = app.load_settings()
        finally:
            app.APP_DIR = release_root
    app.load_settings = lambda: settings.copy()
    result = []

    visits = []
    refused = []

    class WindowServer(app.InterviewServer):
        # On Windows SO_REUSEADDR permits a second listener on the same address.
        allow_reuse_address = False

        def server_bind(self):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                super().server_bind()
            except OSError:
                refused.append(None)  # Whatever the build makes of this error, it is not the build's failure.
                raise

        def process_request(self, request, client_address):
            visits.append(None)  # Connections: the handshake below is one, the window's page makes more.
            super().process_request(request, client_address)

    def proven():
        # "Opened" only means that the server answered. This is the evidence that the build
        # works here: the window requested its page and then stayed open.
        if len(visits) > 1 and known_good() != release.name:
            try:
                replace_text(KNOWN_GOOD, release.name)
            except OSError:
                return
            record("known-good", release.name)

    def abandon():
        # Still here DRAIN_SECONDS after the window closed: a request is still running, usually
        # a provider call that can take minutes, and the page that asked is gone. End the
        # process. Windows then releases the window's lock and the build's lease; the stores
        # are SQLite files, which discard an unfinished transaction when they are next opened.
        record("closed-while-working", release.name)
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.flush()  # server.log is still this process's stdout here.
            except (AttributeError, OSError, ValueError):
                pass
        os._exit(0)

    def supervise(server):
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}/"
            client = build_opener(ProxyHandler({}))
            with client.open(url + "api/config", timeout=8) as response:
                config = json.load(response)
            if (config.get("app_id") != "voice-interviewer"
                    or config.get("build_id") != server.build_id
                    or config.get("csrf_token") != server.csrf_token):
                raise DesktopError("Could not verify the desktop server.")
            if getattr(server, "trace", None):
                server.trace.emit("desktop.handshake_verified", {"port":server.server_port, "rehearsal":bool(rehearsal)})
            if rehearsal:
                smoke(client, url)
                ready.set()
                return
            pending = LAST_OPENED.with_name(f"opened-{os.getpid()}.tmp")
            pending.write_text(release.name, encoding="ascii")
            os.replace(pending, LAST_OPENED)
            # After READY, one more line may tell the window that an older build is running.
            notice = served() if served else ""
            ready.set()
            record("window-ready", release.name)
            print("READY " + url, file=protocol, flush=True)
            if getattr(server, "trace", None):
                server.trace.emit("desktop.ready_sent", {"port":server.server_port})
            if notice:
                print(notice, file=protocol, flush=True)
            signal = threading.Timer(KNOWN_GOOD_AFTER, proven)
            signal.daemon = True
            signal.start()
            try:
                sys.stdin.buffer.read()
                if getattr(server, "trace", None):
                    server.trace.emit("desktop.host_input_ended", {"port":server.server_port})
            finally:
                signal.cancel()  # Closed before then: opened, but not shown to work.
            # The window has closed. The build now stops accepting requests and waits for those
            # it admitted; that wait is bounded here, because this process holds the window's lock.
            drain = threading.Timer(DRAIN_SECONDS, abandon)
            drain.daemon = True
            drain.start()
        except Exception as error:
            result.append(type(error).__name__)
        finally:
            server.shutdown()

    def desktop_server(address, handler, *args, **kwargs):
        server = WindowServer(address, handler, *args, documents_root=home / "work" / "documents",
                              knowledge_root=home / "work" / "knowledge", **kwargs)
        threading.Thread(target=supervise, args=(server,), daemon=True).start()
        return server

    app.InterviewServer = desktop_server
    sys.argv = [str(release / "server.py"), "--port", str(port)]
    # The window's stdout protocol has one success line. App output stays local.
    with (STATE / "server.log").open("a", encoding="utf-8") as log, redirect_stdout(log):
        try:
            app.main()
        except (Exception, SystemExit):
            if not refused or rehearsal or ready.is_set():
                raise
    if refused and not rehearsal and not ready.is_set():
        raise PortUnavailable(port)
    if result:
        raise DesktopError("The desktop server handshake failed (" + result[0] + ").")


def smoke(client, url):
    """The startup check's fixed requests beyond the handshake, all local and offline.

    The build must serve its page, and every script and stylesheet of its own that the page
    names: a build that starts but would show a page that cannot load fails here, before it
    is given the user's data. Any refusal (an HTTP error is an exception) fails the check.
    """
    with client.open(url, timeout=8) as response:
        page = response.read(4 * 1024 * 1024)
    if not page.strip():
        raise DesktopError("The build served an empty page.")
    named = re.findall(rb"""<(?:script|link)\b[^>]*?\s(?:src|href)\s*=\s*["']([^"'<>\s]+)["']""", page, re.IGNORECASE)
    for reference in list(dict.fromkeys(named))[:80]:
        target = urljoin(url, reference.decode("utf-8", "replace"))
        if target.startswith(url):  # Its own files only: nothing on another origin is requested.
            with client.open(target, timeout=8) as response:
                while response.read(65536):
                    pass  # Taken whole, so the build's handler is not cut off while it writes.


def store_formats(release, module):
    """The store formats a build declares it opens, read from its source without running it."""
    try:
        source = (release / module).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return UNDECLARED_FORMATS
    declared = re.search(r"^STORE_FORMATS = \(([0-9]{1,6}), ([0-9]{1,6})\)", source, re.MULTILINE)
    return (int(declared[1]), int(declared[2])) if declared else UNDECLARED_FORMATS


def check_stores(release, home):
    """Refuse to give the saved data to a build that is older than the data.

    The stores are shared: the build that last opened them, or the checkout's own server on
    port 8774, may have upgraded them. An older build would misread them and write to them.
    """
    for module, location, contents in STORES:
        path = home / location
        if not path.is_file():
            continue
        try:
            database = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=5)
            try:
                stored = database.execute("PRAGMA user_version").fetchone()[0]
            finally:
                database.close()
        except sqlite3.Error:
            continue  # Not readable from here: the build decides when it opens the store itself.
        newest = store_formats(release, module)[1]
        if stored > newest:
            raise DesktopError(
                f"The {contents} written by a newer build of Process Collector "
                f"(store format {stored}). Build {release.name[:12]} opens formats up to {newest}, so it was "
                "not started and nothing was changed. Approve a newer build, choose one with `manage.py "
                "rollback <commit>`, or open the data with the build that wrote it.")


def rehearse(revision):
    """Start an approved build once, away from the user's data. True if it answered.

    The check is a separate process with a plain environment (`check()`), which runs the
    build in a scratch folder outside the checkout: see `host()` for what it does there.
    """
    plain = {name: value for name, value in os.environ.items() if name.upper() in PLAIN_ENVIRONMENT}
    try:
        # Its input is a pipe that only this process holds. The pipe ends when this process
        # does, even if it is killed (the window was closed while it was still opening).
        return not run([sys.executable, "-I", "-B", str(Path(__file__).resolve()), "_check", revision],
                       CHECK_SECONDS + 30, cwd=tempfile.gettempdir(), env=plain, stdin=subprocess.PIPE).returncode
    except (OSError, subprocess.TimeoutExpired):
        return False


def check(revision):
    """The startup check's own process. It runs none of the build itself.

    It owns the scratch folder and the process that runs the build there, so both are gone
    when the build has answered or failed, when its time is up, and when the process that
    asked has gone: a killed `serve` could neither stop the build nor remove the folder.
    """
    with tempfile.TemporaryDirectory(prefix="collector-check-", ignore_cleanup_errors=True) as scratch:
        build = subprocess.Popen(
            [sys.executable, "-I", "-B", str(Path(__file__).resolve()), "_rehearse", revision], cwd=scratch,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW)

        def abandoned():
            try:
                # Read the handle itself: a thread waiting inside sys.stdin's buffer would
                # stop this process from ending normally. Returns b"" when the asker has gone.
                while os.read(sys.stdin.fileno(), 4096):
                    pass
            except (AttributeError, OSError, ValueError):
                return  # No input to watch: the time limit below still applies.
            with stopping:
                stop_tree(build)

        stopping = threading.Lock()
        threading.Thread(target=abandoned, daemon=True).start()
        try:
            answered = not build.wait(CHECK_SECONDS)
        except BaseException:
            answered = False
            stop_tree(build)
        with stopping:
            pass  # Let a stop that is under way finish before the folder is removed.
    if not answered:
        sys.exit(1)  # `serve` records it against the build (startup-check-failed).


def rehearsal(revision):
    """The body of the startup check: runs in the process and folder `check()` made for it."""
    scratch = Path.cwd().resolve()
    if revision not in approved() or scratch.is_relative_to(ROOT) or any(scratch.iterdir()):
        raise DesktopError("The startup check runs only for an approved build, in an empty folder outside the checkout.")
    # If the process that asked is stopped, a build that hangs must not stay behind.
    limit = threading.Timer(CHECK_SECONDS, os._exit, [1])
    limit.daemon = True
    limit.start()
    # A key that is not a key: the build takes the branches it takes with one, and can spend nothing.
    (scratch / ".env.local").write_text("OPENAI_API_KEY=startup-check-placeholder\n", encoding="ascii")
    ready = threading.Event()
    host(RELEASES / revision, 0, ready, rehearsal=scratch)
    if not ready.is_set():
        raise DesktopError("The build ended without answering its startup check.")


def port_available(port):
    """Whether the window's address can be bound now, in the way `host()` binds it."""
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def serve(port):
    with ExitStack() as held:
        try:
            # A window that was closed a moment ago may still be finishing (`host` bounds
            # that at DRAIN_SECONDS). Wait for it instead of failing the new window at once.
            held.enter_context(locked(STATE / f"window-{port}.lock", WINDOW_PATIENCE))
        except DesktopError:
            record("window-busy")
            raise WindowBusy() from None
        # Only builds the user approved are imported, newest first, then the approved
        # fallbacks. Downloading (`update`, `pending`) is separate and never runs what
        # it fetched; a downloaded build is not served until `approve` records it.
        choices = approved()
        if not choices:
            raise failure("nothing-approved", "No Process Collector build has been approved to run yet.")
        if not port_available(port):
            # Every build would fail on this. None is run, and none is marked as failed.
            record("port-unavailable")
            raise PortUnavailable(port)
        marks, fresh, outdated = failed(), {}, {}

        def served(selected):
            # This build answered here, so the failures before it in this launch were those
            # builds' own: the settings and saved data they share did not stop this one, and
            # a port that cannot be bound ends the launch instead of counting against a
            # build. Remember them: a build that failed once is not tried first again.
            note_failures({**fresh, selected: None})
            if selected == choices[0]:
                return ("NOTICE Updates are on hold: nothing new is downloaded or offered until 'manage.py resume'."
                        if HOLD.exists() else "")
            if choices[0] in outdated:
                return (f"NOTICE Running build {selected[:12]}: the chosen build {choices[0][:12]} is older than "
                        "the saved data and was not started.")
            return (("NOTICE-NEW " if fresh else "NOTICE ") + "Running the previous build: the latest update "
                    f"failed to start (using {selected[:12]}, not {choices[0][:12]}).")

        # Approved releases are retained during scheduled updates.
        # Acquire this window's lease before serving from its immutable tree.
        # A build that could not start here is tried again only when nothing else is left.
        for selected in sorted(choices, key=lambda sha: sha in marks):
            with locked(STATE / (selected + ".lock"), 3, ("build-in-use", selected), offset=port):
                release = RELEASES / selected
                ready = threading.Event()
                if not (release / "server.py").is_file():
                    continue
                if (release / ".desktop-manifest").exists() and not intact(release):
                    record("release-damaged", selected)
                    fresh[selected] = "release-damaged"
                    continue
                try:
                    check_stores(release, ROOT)
                except DesktopError as refusal:
                    # Not a failure to start: nothing of this build was run, and it is refused
                    # again for as long as the data is newer than it.
                    record("older-than-saved-data", selected)
                    outdated[selected] = str(refusal)
                    continue
                # A build the window has not opened yet is started once with empty stores
                # before it is given the real ones. That failure is the build's own.
                if selected != last_opened() and not rehearse(selected):
                    record("startup-check-failed", selected)
                    fresh[selected] = "startup-check-failed"
                    # Only this build: the failures before it in this launch are not yet shown
                    # to be those builds' own (see `served`).
                    note_failures({selected: "startup-check-failed"})
                    continue
                try:
                    host(release, port, ready, lambda: served(selected))
                    return
                except PortUnavailable:
                    # Taken since it was tested above. No build is marked for it, and no older
                    # build is opened in place of the chosen one because of it.
                    record("port-unavailable")
                    raise
                except (Exception, SystemExit):
                    if ready.is_set():
                        raise  # Never reopen a window that has already been served.
                    record("startup-failed", selected)
                    fresh[selected] = "startup-failed"
                    # Discard only imports loaded from this failed release.
                    for name, module in list(sys.modules.items()):
                        path = getattr(module, "__file__", None)
                        if isinstance(path, str) and Path(path).is_relative_to(release):
                            sys.modules.pop(name, None)
        raise DesktopError(outdated.get(choices[0]) or next(iter(outdated.values()), None) or
                           "Could not start an approved desktop release. The update log "
                           "(.local\\desktop\\updates.log) names each build that failed.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True,
                                     metavar="{update,pending,approve,rollback,hold,resume,serve}")
    commands.add_parser("update", help="download GitHub main for review; runs nothing")
    commands.add_parser("pending", help="download, then print the build awaiting approval")
    decision = commands.add_parser("approve", help="record the decision to run that build")
    decision.add_argument("revision")
    earlier = commands.add_parser("rollback", help="open an earlier approved build from now on: the one named, "
                                  "else the last one known to work")
    earlier.add_argument("revision", nargs="?", default="")
    commands.add_parser("hold", help="stop downloading and offering builds until `resume`")
    commands.add_parser("resume", help="end a hold")
    window = commands.add_parser("serve", help="host the approved build for the window")
    window.add_argument("--port", type=int, default=8776)
    # Internal: `serve` runs `_check`, which runs `_rehearse` in a scratch folder, before a
    # build first gets the real stores.
    commands.add_parser("_check").add_argument("revision")
    commands.add_parser("_rehearse").add_argument("revision")
    args = parser.parse_args()
    RELEASES.mkdir(parents=True, exist_ok=True)
    if args.command == "update":
        revision = update(90, 90)
        if sys.stdout:
            print("Updates are on hold. Run `manage.py resume` to end the hold." if not revision
                  else "GitHub main " + revision + (" is downloaded and awaits approval in the desktop window"
                                                    if pending() == revision else ""))
    elif args.command == "pending":
        cached = approved()
        problem = ""
        try:
            update(8 if cached else 45, .2 if cached else 65)
        except (OSError, DesktopError, subprocess.TimeoutExpired) as error:
            # Offline, busy or refused: an earlier download may still be waiting.
            problem = explained(error)
        question = offer()
        if not question and not cached and problem:
            # A first run with nothing to open and nothing to offer. Tell the window why, so
            # that it does not go on to report only that no build has been approved.
            question = "PROBLEM " + problem + "\n"
        if sys.stdout:
            sys.stdout.buffer.write(question.encode("utf-8"))
            sys.stdout.flush()
    elif args.command == "approve":
        approve(args.revision)
    elif args.command == "rollback":
        selected = rollback(args.revision)
        if sys.stdout:
            print("Process Collector will open build " + selected[:12] + " the next time its window opens.")
    elif args.command in ("hold", "resume"):
        hold(args.command == "hold")
        if sys.stdout:
            print("Updates are on hold: nothing is downloaded or offered until `manage.py resume`."
                  if args.command == "hold" else "Updates are no longer on hold.")
    elif args.command == "_check":
        check(args.revision)
    elif args.command == "_rehearse":
        rehearsal(args.revision)
    elif 0 < args.port < 65536:
        try:
            serve(args.port)
        except DesktopError as error:
            # In place of READY: the reason, for the window to show instead of a general failure.
            if sys.stdout:
                print("ERROR " + str(error), flush=True)
            raise
    else:
        parser.error("Port must be between 1 and 65535.")


def explained(error):
    """One sentence for a person. Never environment values, HTTP responses or raw Git output."""
    if isinstance(error, DesktopError):
        return str(error)
    return "The desktop command stopped on an unexpected error (" + type(error).__name__ + ")."


def cli():
    try:
        main()
    except (DesktopError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        # The window shows the last line that starts like this one, with the path of the log.
        record("operation-failed")
        if sys.stderr:
            print("Process Collector desktop: " + explained(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    cli()
