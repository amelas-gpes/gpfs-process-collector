"""Own the optional local recovery copy and its cross-process check-and-write lock."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
import uuid
from contextlib import closing, contextmanager
from pathlib import Path

from runtime_build import VERSION


RECOVERY_FORMAT = 1
RECOVERY_DAYS = 7
# The largest saved interview the page opens (Open saved interview in web/app.js).
MAX_RECOVERY = 16 * 1024 * 1024
RECOVERY_OFF_MESSAGE = "Recovery copies are turned off in Settings. Nothing was stored."


class RecoveryOff(Exception):
    """The person has not turned the recovery copy on (or has turned it off again)."""


class RecoveryConflict(Exception):
    """The stored copy is not the one the request is about; carries its description."""

    def __init__(self, summary):
        super().__init__("Another recovery copy is stored.")
        self.summary = summary


def recovery_session(value):
    """Refuse what Open saved interview in the page would refuse, before a copy is stored.

    The page validates the whole interview again when a copy is restored; these are its
    size and shape bounds, so the store never holds something the page could not open.
    """
    def length(text):
        # As the page counts it (UTF-16 units), so both sides apply the same bound.
        return len(text.encode("utf-16-le", "surrogatepass")) // 2

    if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise ValueError("A recovery copy must be an interview in this app's saved format.")
    if value.get("synthetic_example") is True:
        raise ValueError("The fictional example is not kept as a recovery copy.")
    context = value.get("context")
    if not isinstance(context, dict):
        raise ValueError("A recovery copy needs the interview context.")
    for key, limit in (("process_name", 500), ("process_owner", 500), ("objective", 500), ("background", 8000)):
        if context.get(key) is not None and (not isinstance(context[key], str) or length(context[key]) > limit):
            raise ValueError("The interview context is too long to keep as a recovery copy.")
    turns = value.get("turns")
    if not isinstance(turns, list) or len(turns) > 400:
        raise ValueError("A recovery copy holds at most 400 turns.")
    seen, total = set(), 0
    for turn in turns:
        if not isinstance(turn, dict) or turn.get("role") not in ("user", "assistant"):
            raise ValueError("Turns must have a user or assistant role.")
        turn_id, text = turn.get("id"), turn.get("text")
        if (not isinstance(turn_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", turn_id)
                or turn_id == "context" or turn_id in seen):
            raise ValueError("Turn IDs must be unique letters, numbers, underscores or hyphens.")
        seen.add(turn_id)
        if not isinstance(text, str) or length(text) > 6000:
            raise ValueError("A turn exceeds the 6,000-character limit.")
        total += length(text)
    if total > 400_000:
        raise ValueError("A recovery copy holds at most 400,000 characters of conversation.")
    if isinstance(value.get("unsent_answer"), str) and length(value["unsent_answer"]) > 18000:
        raise ValueError("The unsent answer is too long to keep.")
    return value


class RecoveryStore:
    """One optional local copy of an unsaved interview, kept with the app's private data.

    Nothing is kept unless the person turns the setting on in the page; while it is off
    the folder does not exist. The copy is what Save copy would write. It is read only
    by the recovery routes below: no provider request, log or other store sees it. It
    is deleted when the page reports a confirmed save, a replaced interview or Discard,
    when the setting is turned off, and when it is RECOVERY_DAYS old.

    The folder sits beside the document and knowledge stores, so the browser launcher
    and the desktop window (two servers on one work folder) share the setting and the
    copy. A copy belongs to the interview that wrote it (its id): another interview
    never replaces it, and a copy this version cannot read is reported, not overwritten.
    """

    def __init__(self, root, clock=time.time):
        self.root = Path(root)
        self.clock = clock
        self._seen = None

    @contextmanager
    def _exclusive(self):
        # Every server serving these data must perform check-and-replace as one operation.
        # Keep this content-free lock outside the folder removed when recovery is disabled.
        with closing(sqlite3.connect(self.root.with_suffix(".lock.sqlite3"))) as db:
            db.execute("BEGIN IMMEDIATE")
            yield

    @property
    def _draft(self):
        return self.root / "draft.json"

    def enabled(self):
        try:
            data = json.loads((self.root / "setting.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return (isinstance(data, dict) and type(data.get("format")) is int
                and data["format"] == RECOVERY_FORMAT and data.get("enabled") is True)

    def public_state(self):
        """For /api/config: whether to ask at all. Never any part of a copy."""
        state = self.status()
        return {"enabled": state["enabled"], "stored": state["draft"] is not None}

    def status(self):
        if not self.root.is_dir():
            return {"enabled": False, "draft": None}
        with self._exclusive():
            enabled = self.enabled()
            return {"enabled": enabled, "draft": self._summary() if enabled else None}

    def set_enabled(self, value):
        if type(value) is not bool:
            raise ValueError("Choose whether a recovery copy is kept.")
        if value:
            self.root.parent.mkdir(parents=True, exist_ok=True)
        elif not self.root.is_dir():
            return {"enabled": False, "draft": None}
        with self._exclusive():
            if value:
                self.root.mkdir(parents=True, exist_ok=True)
                self._write(self.root / "setting.json", json.dumps(
                    {"format": RECOVERY_FORMAT, "enabled": True, "changed_at": self._stamp(self.clock())}).encode("utf-8"))
            else:
                # Turning the option off removes everything it kept.
                for path in (self._draft, self.root / "setting.json", *self._leftovers()):
                    self._remove(path)
                try:
                    self.root.rmdir()
                except OSError:
                    pass
        return self.status()

    def save(self, draft_id, session):
        if not isinstance(draft_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", draft_id) or draft_id.startswith("unreadable-"):
            raise ValueError("The recovery copy ID is not valid.")
        recovery_session(session)
        # Prepare the whole candidate before claiming the slot. A failed validation or
        # serialization cannot displace the current copy, including for non-HTTP callers.
        raw_session = json.dumps(session, ensure_ascii=False, separators=(",", ":")).encode("utf-8", "surrogatepass")
        if len(raw_session) > MAX_RECOVERY:
            raise ValueError("The recovery copy is larger than the largest interview this app opens.")
        if not self.root.is_dir():
            raise RecoveryOff(RECOVERY_OFF_MESSAGE)
        with self._exclusive():
            if not self.enabled():
                raise RecoveryOff(RECOVERY_OFF_MESSAGE)
            current = self._summary()
            if current and current["id"] != draft_id:
                raise RecoveryConflict(current)
            now = self.clock()
            record = {"format": RECOVERY_FORMAT, "id": draft_id, "saved_at": self._stamp(now), "saved_epoch": int(now),
                      "app_version": VERSION}
            # Keep the original on-disk JSON envelope and the exact session bytes we bounded.
            header = json.dumps(record, separators=(",", ":")).encode("ascii")
            self._write(self._draft, b"".join((header[:-1], b',"session":', raw_session, b"}")))
            self._seen = None
        return {"id": draft_id, "saved_at": record["saved_at"]}

    def load(self, draft_id=None):
        """The stored copy, or None. A copy other than the one asked for is a conflict."""
        if not self.root.is_dir():
            return None
        with self._exclusive():
            if not self.enabled():
                return None
            current = self._summary()
            if not current:
                return None
            if not current["readable"] or (draft_id is not None and current["id"] != draft_id):
                raise RecoveryConflict(current)
            record = self._record()
        if not record:
            return None
        return {"id": record["id"], "saved_at": record["saved_at"], "session": record["session"]}

    def discard(self, draft_id):
        """Delete the stored copy when it is the one named; say what is stored afterwards."""
        if not self.root.is_dir():
            return {"enabled": False, "draft": None}
        with self._exclusive():
            current = self._summary()
            if current and current["id"] == draft_id:
                self._remove(self._draft)
                self._seen = None
        return self.status()

    def purge(self):
        """Server start: drop an expired copy and files an interrupted write left behind."""
        if not self.root.is_dir():
            return
        try:
            with self._exclusive():
                for path in self._leftovers():
                    self._remove(path)
                self._summary()
        except (OSError, sqlite3.Error):
            pass

    def _leftovers(self):
        try:
            return [path for path in self.root.iterdir() if path.suffix == ".tmp"]
        except OSError:
            return []

    @staticmethod
    def _stamp(moment):
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(moment))

    @staticmethod
    def _remove(path):
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def _write(self, path, raw):
        """Whole file or nothing: a crash, a kill or a shutdown never leaves half a copy."""
        pending = path.with_name(f"{path.stem}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        try:
            with pending.open("wb") as output:
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())
            for attempt in range(5):
                try:
                    os.replace(pending, path)
                    return
                except PermissionError:
                    # Windows refuses while the other server on this folder reads the file.
                    if attempt == 4:
                        raise
                    time.sleep(.05)
        finally:
            try:
                pending.unlink()
            except OSError:
                pass  # Already moved into place, or removed at the next start.

    def _record(self):
        """The stored record when this version can read it, else None."""
        try:
            if self._draft.stat().st_size > MAX_RECOVERY + 4096:
                return None
            record = json.loads(self._draft.read_bytes().decode("utf-8", "surrogatepass"))
        except (OSError, ValueError, RecursionError):
            return None
        if (not isinstance(record, dict) or type(record.get("format")) is not int or record["format"] != RECOVERY_FORMAT
                or not isinstance(record.get("id"), str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", record["id"])
                or not isinstance(record.get("saved_at"), str) or len(record["saved_at"]) > 40
                or type(record.get("saved_epoch")) not in (int, float) or not 0 <= record["saved_epoch"] < 253402300800):
            return None
        try:
            recovery_session(record.get("session"))
        except ValueError:
            return None
        return record

    def _summary(self):
        """What may be said about the stored copy without any of its text, or None."""
        try:
            stat = self._draft.stat()
        except OSError:
            return None
        # Read the file again only when it has changed, here or through the other server.
        key = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
        if not self._seen or self._seen[0] != key:
            record = self._record()
            if record:
                session = record["session"]
                context = session.get("context") if isinstance(session.get("context"), dict) else {}
                derived = session.get("derived_process_title") if session.get("process_name_manual") is not True else ""
                name = derived or context.get("process_name") or ""
                turns = session.get("turns") if isinstance(session.get("turns"), list) else []
                summary = {"id": record["id"], "saved_at": record["saved_at"],
                           "process_name": (name[:180].encode("utf-8", "replace").decode("utf-8")
                                            if isinstance(name, str) else ""),
                           "messages": sum(1 for turn in turns if isinstance(turn, dict) and turn.get("document_event") is not True),
                           "readable": True}
                saved = record["saved_epoch"]
            else:
                # Named by the file itself, so Discard removes exactly what was described.
                summary = {"id": "unreadable-" + hashlib.sha256(repr(key).encode("ascii")).hexdigest()[:24],
                           "saved_at": self._stamp(stat.st_mtime), "process_name": "", "messages": 0, "readable": False}
                saved = stat.st_mtime
            self._seen = (key, summary, saved)
        _, summary, saved = self._seen
        if self.clock() - saved > RECOVERY_DAYS * 86400:
            self._seen = None
            try:
                self._remove(self._draft)
            except OSError:
                pass  # In use just now; it is neither offered nor kept past the next look.
            return None
        return dict(summary)
