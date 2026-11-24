"""What one provider call belongs to: its interview, its cancellation check and the stages that made an artifact."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache, wraps
import hashlib
import re
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


def track_generation(function=None, *, artifact=None):
    """Collect successful model stages for one returned artifact, including concurrent reviews.

    The artifact is the returned dict, or its entry named by artifact when the call
    returns the artifact together with something else.
    """
    def decorate(function):
        @wraps(function)
        def tracked(owner, *args, **kwargs):
            token = _generation.set((threading.Lock(), []))
            try:
                result = function(owner, *args, **kwargs)
                stages = generated_by()
                if stages:
                    stamp_generation(result[artifact] if artifact else result,
                                     getattr(getattr(owner, "api", owner), "VERSION", ""))
            finally:
                _generation.reset(token)
            remember_stages(stages)
            return result
        return tracked
    return decorate(function) if function else decorate


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
