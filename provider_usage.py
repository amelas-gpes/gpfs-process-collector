"""Local token accounting. Store UTC day, anonymous interview label and counts only."""
from contextlib import closing, contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import lru_cache, wraps
import hashlib
from pathlib import Path
import re
import sqlite3
import threading


active_interview = ContextVar("active_interview", default="")
active_abort = ContextVar("active_abort", default=None)
# Set in the threads that do work nobody is waiting on (notes, maps and their source checks).
# The provider client keeps part of its request slots free of such work, so that a question,
# a transcription or a voice session never queues behind it.
background_work = ContextVar("background_work", default=False)
_generation = ContextVar("generation_provenance", default=None)


@lru_cache(maxsize=128)
def prompt_id(instructions):
    return hashlib.sha256(instructions.encode("utf8")).hexdigest()[:16]


def validate_generation_records(records):
    keys = {'stage', 'model', 'prompt_id', 'reasoning_effort', 'generated_at', 'build_id'}
    if not isinstance(records, list) or len(records) > 128:
        raise ValueError('Generation history must contain at most 128 records.')
    for row in records:
        if not isinstance(row, dict) or not {'stage','model'} <= row.keys() <= keys:
            raise ValueError('Each generation record must identify the stage and model.')
        if any(not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/+ -]{0,179}', value) for value in row.values()):
            raise ValueError('A generation record contains an invalid identifier.')
    return records


def remember_stages(stages):
    current = _generation.get()
    if current is None:
        return
    lock, rows = current
    with lock:
        for row in stages:
            if len(rows) < 32 and row not in rows:
                rows.append(dict(row))


def generated_by():
    current = _generation.get()
    if current is None:
        return []
    lock, rows = current
    with lock:
        return [dict(row) for row in rows]


def stamp_generation(result, version):
    stages = generated_by()
    if stages:
        previous = result.get("generated_by", [])
        result["generated_by"] = (previous + [row for row in stages if row not in previous])[:32]
        result["app_version"] = version


def track_generation(function):
    """Collect successful model stages for one returned artifact, including concurrent reviews."""
    @wraps(function)
    def tracked(owner, *args, **kwargs):
        token = _generation.set((threading.Lock(), []))
        try:
            result = function(owner, *args, **kwargs)
            stages = generated_by()
            if stages:
                stamp_generation(result, getattr(getattr(owner, "api", owner), "VERSION", ""))
        finally:
            _generation.reset(token)
        remember_stages(stages)
        return result
    return tracked


def interview_id(value):
    return value if isinstance(value, str) and re.fullmatch("[a-f0-9]{32}", value) else ""


@contextmanager
def request_scope(interview_id=None, should_abort=None):
    label = active_interview.set(interview_id if interview_id is not None else active_interview.get())
    previous = active_abort.get()
    if previous and should_abort:
        check = lambda: previous() or should_abort()
    else:
        check = should_abort or previous
    cancel = active_abort.set(check)
    try:
        yield
    finally:
        active_abort.reset(cancel)
        active_interview.reset(label)


class UsageLedger:
    def __init__(self, settings):
        def cap(setting):
            text = str(settings.get(setting) or "0")
            if not re.fullmatch(r"[0-9]{1,14}", text):
                raise ValueError("Token caps must be whole nonnegative numbers, or zero to disable.")
            return int(text)

        self.daily_cap = cap("DAILY_TOKEN_CAP")
        self.interview_cap = cap("INTERVIEW_TOKEN_CAP")
        self.path = None
        self._lock = threading.RLock()
        self._memory = {}
        self._quota_blocked = False
        self._pending = {}

    def attach(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise ValueError("The usage ledger cannot be a symbolic link.")
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS totals (day TEXT, interview TEXT, tokens INTEGER NOT NULL, PRIMARY KEY (day, interview))")
        self.path = path

    @staticmethod
    def day():
        return datetime.now(timezone.utc).date().isoformat()

    def summary(self, label=""):
        day = self.day()
        with self._lock:
            if self.path:
                with closing(sqlite3.connect(self.path)) as db:
                    count_day = db.execute("SELECT COALESCE(SUM(tokens),0) FROM totals WHERE day=?", (day,)).fetchone()[0]
                    personal = db.execute("SELECT COALESCE(SUM(tokens),0) FROM totals WHERE interview=?", (label,)).fetchone()[0] if label else None
            else:
                count_day = sum(v for (d, _), v in self._memory.items() if d == day)
                personal = sum(v for (_, i), v in self._memory.items() if i == label) if label else None
            return {"day_tokens": count_day, "daily_token_cap": self.daily_cap, "interview_tokens": personal,
                    "interview_token_cap": self.interview_cap, "quota_blocked": self._quota_blocked}

    def start(self, request_id, label, budget, background):
        with self._lock:
            if self._quota_blocked:
                return "quota"
            if self.daily_cap or self.interview_cap:
                status = self.summary(label)
                pending = sum(size for _, size in self._pending.values())
                personal = sum(size for owner, size in self._pending.values() if owner == label)
                limits = [(self.daily_cap, status["day_tokens"] + pending)]
                if label:
                    limits.append((self.interview_cap, status["interview_tokens"] + personal))
                if any(limit and (used + budget > limit or (background and used >= limit * .9)) for limit, used in limits):
                    return "budget_reached"
                self._pending[request_id] = (label, budget)
        return ""

    def finish(self, request_id, label, metrics):
        with self._lock:
            self._pending.pop(request_id, None)
            if metrics.get("error_category") == "quota":
                self._quota_blocked = True
            tokens = metrics.get("input_tokens", 0) + metrics.get("output_tokens", 0)
            if not tokens:
                return
            day = self.day()
            if self.path:
                with closing(sqlite3.connect(self.path)) as db, db:
                    db.execute("INSERT INTO totals VALUES (?,?,?) ON CONFLICT(day,interview) DO UPDATE SET tokens=tokens+excluded.tokens",
                               (day, label, tokens))
            else:
                self._memory[day, label] = self._memory.get((day, label), 0) + tokens

    def clear_quota(self):
        with self._lock:
            self._quota_blocked = False
