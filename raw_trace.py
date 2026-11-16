"""Local, append-only observations. A bound store belongs to one app instance."""
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
import heapq
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import threading
from time import monotonic
import uuid


SCHEMA_VERSION = 1
MAX_EVENT_BYTES = 8 * 1024 * 1024
MAX_PENDING_BYTES = 24 * 1024 * 1024
MAX_PENDING_EVENTS = 1024
MAX_SEGMENT_BYTES = 512 * 1024 * 1024
DISK_RESERVE_BYTES = 64 * 1024 * 1024
SPACE_CHECK_BYTES = 8 * 1024 * 1024
SPACE_CHECK_SECONDS = 5
MAX_NODES = 120_000
MAX_DEPTH = 64
_binding = ContextVar("raw_trace_binding", default=(None, {}))
_event_name = re.compile(r"[a-z][a-z0-9_.-]{0,95}\Z")
_identifier = re.compile(r"[a-zA-Z0-9_.:+/-]{1,160}\Z")
_credential_text = re.compile(
    r"(?:\b(?:sk|ek)[_-][A-Za-z0-9_-]{8,}|\b(?:bearer|basic)\s+[A-Za-z0-9+/_.=-]{8,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----|\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)", re.I
)
_inline_secret = re.compile(
    r"""(?i)["']?(?:api[_-]?key|authorization|password|client[_-]?secret|(?:access|capture|csrf|status|conversation)[_-]?token|document[_-]?scope|agent[_-]?run[_-]?id|review[_-]?ticket|submission[_-]?key)["']?\s*[:=]\s*["']?[^\s"'{}\[\],]{5,}"""
)
_inline_private_field = re.compile(
    r'''(?i)["'](?:scope|_scope|run_id|active_run_id|review_ticket|status_token|document_scope|unsent_answer|sdp|file_data|extracted_text|header_sample)["']\s*:\s*["'][^"']+'''
)
_secret_names = set(
    """authorization proxyauthorization cookie setcookie scope scopeid scopehash
    runtokens runid activerunid agentrunid reviewticket ticket secret secretkey
    sessionkey submissionkey idempotencykey headers environment env credential
    credentials password apikey privatekey sdp icepwd iceufrag connectionstring
    recoveryid""".split()
)
_transient_names = set(
    """unsentanswer unsentinput composervalue composertext inputvalue unsenttext
    rawaudio audiofile recordingbytes filedata filebytes filebase64 base64 dataurl
    sourcebytes originalbytes originalpath absolutepath filepath""".split()
)
_document_groups = set(
    """chunks excerpts excerpt passages retainedevidence documentevidence extractedevidence
    documenttext extractedtext documentcontent originaltext documentexcerpts headersample sample""".split()
)
_safe_doc_metadata = set(
    "id sourceid documentid revision origin kind type status disposition sha256".split()
)
_technical = set(
    """action role channel model stage reasoncode code status state branch outcome method
    kind type producer build buildid appversion version resulttype route path component
    handler errortype errorcategory promptid reasoningeffort mimetype contenttype format
    disposition mode phase operation operationid parentoperationid requestid parentid
    upstreamrequestid revision reason gate guard worker event sourceevent origin field
    control tabid producerid interviewid turnid eventid sourceid documentid sessionid
    schemaid clock observedat recordedat updatedat createdat generatedat implementation
    originaltype omission tracestate hash sha256 trace parenteventid parentoperationid
    teamid throughturnid sourcerevision jobid submissionid category mediatype
    roles tag fieldname contentomitted valueomitted encoding""".split()
)
# Object keys can also be data (e.g. a user-named workflow step or a document
# table heading). Preserve only known structural names in the metadata profile.
_metadata_keys = _technical | set(
    """id seq sequence sourcesequence durationms elapsedms latencyms pid port size bytes
    count length pending queued failed dropped attempts attempt retry enabled available
    active previous next before after changes values value payload data request response
    result text content output input messages instructions context turns question answer
    settings headers transport schema properties required format usage inputtokens
    outputtokens cachedtokens reasoningtokens tokenstotal maxtokens maxoutputtokens
    modelsettings statuscode error errorclass exception scope audio file document
    documents files name summary version generation actors agents role decision allowed
    reason flags at timeutc observedtime receipt caption final delta eventtype parent
    checkpoint throughturnid unreviewedturnids notes workflow capture facts coverage
    source sources eventidsource buildversion schema_version fieldcount itemcount
    redacted truncated total sizebytes characters units totalbytes originalsize
    body fields httpstatus diagnosticstatus httpmethod target checked selected visible available droppedcount
    cancelled accepted approved guardreason published countbytes attemptnumber
    previousrevision currentrevision source_revision jobid fileid connectionid
    speech_authorization diagnostics properties enabled checked resumable interrupted
    written byrevision force kept guard evaluated guardevaluated requestreview syncrequired
    captured published stale hasworkflow calls maxcalls configured contentenabled dropped
    open tag line column persisted aborted originaleventbytes bytecount outputindex
    contentindex audioindex bufferindex startoffset lengthcharacters eventcount inputcount
    endpoint selectedsourceids requestedsourceids questionlength timeoutseconds received
    teamid rolecount hasdocuments hasturns query sourceids scopeomitted
    endms startms acknowledgedchunks totalchunks callback callbackname fragmentcount
    chars captionid clienteventid itemid audioomitted busy lasting exceptiontype
    stepcount turncount map view uploading mutating discarded persisted recovered synthetic
    count omittedfields startoffset endoffset offset matched exitcode timeoutms bytecount
    sourcemode lastsequence depth resource limit mode""".split()
)
_context_keys = {
    "producer", "producer_id", "tab_id", "source_sequence", "observed_at", "interview_id",
    "turn_id", "operation_id", "parent_operation_id", "parent_event_id", "revision",
    "build", "attempt", "request_id",
}


def _utc():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _key(name):
    return re.sub("[^a-z0-9]", "", name.lower())


def _secret_field(key, value):
    # Record measured token counts; an arbitrary string under a token-like
    # field never becomes an exempt value just because its name describes usage.
    if "token" in key:
        return type(value) not in (int, float) or not any(
            part in key for part in ("tokens", "tokencount", "tokencap", "tokenlimit"))
    return (key in _secret_names or any(part in key for part in (
        "password", "secret", "capability", "csrf", "apikey", "privatekey", "documentscope"))
        or key.endswith(("ticket", "credential", "credentials", "runid", "submissionkey")))


def _marker(reason, **fields):
    return {"_trace": reason, **fields}


def _displayable_string(key, value):
    if key == "path":
        return value in {"responses", "live/sessions", "realtime/client_secrets", "audio/transcriptions"} or bool(
            re.fullmatch(r"/(?:api/)?[a-zA-Z0-9_./-]{0,130}", value))
    return key in _technical and bool(_identifier.fullmatch(value))


def _sensitive_text(value, secrets):
    return any(s in value for s in secrets) or bool(_credential_text.search(value))


def _document_reference(ref):
    source_id = ref.get("source_id") if isinstance(ref, dict) else ref
    return isinstance(source_id, str) and source_id.startswith("doc_")


def _distinct_fields(pairs):
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise _DuplicateField()
    return fields


class _DuplicateField(ValueError):
    pass


def _has_link(path):
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            return True
    return False


def _mode(work_dir, settings):
    mode = settings.get("RAW_TRACE_MODE") or os.environ.get("RAW_TRACE_MODE")
    if not mode:
        config = work_dir / "raw-trace-mode.txt"
        try:
            if not _has_link(config) and config.is_file():
                with config.open("rb") as mode_file:
                    raw = mode_file.read(33)
                if len(raw) <= 32:
                    mode = raw.decode("ascii").strip()
        except (OSError, ValueError):
            pass
    normalized = str(mode or "metadata").strip().lower()
    return normalized if normalized in {"off", "metadata", "content"} else "metadata"


class _Snapshot:
    """Construct fresh JSON values at observation time, before callers mutate them."""

    def __init__(self, content, secrets):
        self.content = content
        self.secrets = secrets
        self.nodes = 0
        self.chars = 0

    def copy(self, value, key="", depth=0, document=False):
        self.nodes += 1
        if self.nodes > MAX_NODES or self.chars > MAX_EVENT_BYTES or depth > MAX_DEPTH:
            return _marker("snapshot_limit")
        if _secret_field(key, value):
            return _marker("credential_excluded")
        if key in _transient_names:
            return _marker("transient_excluded")
        if not self.content and key in ("content", "fields") and isinstance(value, (dict, list)):
            # A submitted model/body payload can use any field name for client
            # text, including words like "status" that describe safe metadata
            # when they come from our own instrumentation.
            return _marker("metadata_only", items=len(value))
        document = document or key in _document_groups
        if isinstance(value, dict):
            if value.get("type") in ("reasoning", "reasoning_text", "reasoning_summary", "summary_text", "encrypted_content"):
                return {"type": value["type"], "_trace": "provider_private_reasoning_excluded"}
            if isinstance(value.get("source_id"), str) and (
                value["source_id"].startswith("doc_") or value.get("document_id") and value["source_id"]
            ):
                document = True
            # Document review returns verbatim passages next to a sources
            # array; older outputs carry only IDs, newer outputs keep objects.
            document_observation = ("quote" in value and isinstance(value.get("sources"), list)
                                    and ("basis" in value or any(_document_reference(ref) for ref in value["sources"])))
            result = {}
            for index, (name, item) in enumerate(value.items()):
                if self.nodes >= MAX_NODES or self.chars > MAX_EVENT_BYTES:
                    result["_trace_remaining_fields"] = _marker("snapshot_limit", count=len(value)-index)
                    break
                if not isinstance(name, str) or len(name) > 512 or _sensitive_text(name, self.secrets):
                    result[f"_trace_field:{index}"] = _marker("field_name_excluded")
                    continue
                normalized = _key(name)
                if self.content or (re.fullmatch("[A-Za-z_][A-Za-z0-9_-]{0,95}", name)
                                    and (normalized in _metadata_keys or normalized in _secret_names)):
                    output_name = name
                else:
                    output_name = f"_trace_field:{index}"
                result[output_name] = self.copy(item, normalized, depth+1,
                                                document or (document_observation and normalized == "quote"))
            return result
        if isinstance(value, (list, tuple)):
            result = []
            for index, item in enumerate(value):
                if self.nodes >= MAX_NODES or self.chars > MAX_EVENT_BYTES:
                    result.append(_marker("snapshot_limit", count=len(value)-index))
                    break
                result.append(self.copy(item, key, depth+1, document))
            return result
        if value is None or type(value) in (int, bool):
            return value
        if type(value) is float:
            return value if math.isfinite(value) else _marker("nonfinite_number")
        if isinstance(value, (bytes, bytearray, memoryview)):
            return _marker("binary_excluded", bytes=value.nbytes if isinstance(value, memoryview) else len(value))
        if not isinstance(value, str):
            return _marker("unsupported_value")
        if value == "":
            return ""
        if document and key not in _safe_doc_metadata:
            return _marker("document_content_excluded", characters=len(value))
        if key in {"audio", "imageurl", "imagedata", "audiobytes", "recording", "encryptedcontent"} or value.startswith("data:") and ";base64," in value[:128]:
            return _marker("media_excluded", characters=len(value))
        if not self.content and not _displayable_string(key, value):
            return _marker("metadata_only", characters=len(value))
        if len(value) > MAX_EVENT_BYTES:
            return _marker("snapshot_limit", characters=len(value))
        # Responses input and output_text often wrap structured data in a JSON
        # string. Keep the original bytes/spacing unless a nested exclusion
        # actually applies. When changed, explicitly identify the safe projection.
        if value.lstrip()[:1] in ("[", "{"):
            try:
                inner = json.loads(value, object_pairs_hook=_distinct_fields)
                safe = self.copy(inner, depth=depth+1)
                if safe != inner:
                    return _marker("filtered_json_string", value=safe)
            except _DuplicateField:
                # Parsing last-key-wins then keeping the original string can
                # expose excluded material in an overwritten object member.
                return _marker("ambiguous_json_fields", characters=len(value))
            except (ValueError, RecursionError):
                pass
        if _sensitive_text(value, self.secrets) or _inline_secret.search(value) or _inline_private_field.search(value):
            return _marker("credential_excluded")
        self.chars += len(value)
        return value


class TraceStore:
    """One writer per server run; concurrent processes always own separate segments."""

    def __init__(self, work_dir, settings=None):
        settings = settings or {}
        work_dir = Path(work_dir).absolute()
        self.directory = work_dir / "raw-trace"
        self.mode = _mode(work_dir, settings)
        self.enabled = self.mode != "off"
        self.content = self.mode == "content"
        self.run_id = str(uuid.uuid4())
        self._stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        self._secrets = tuple(s.strip() for s in (settings.get("OPENAI_API_KEY"),)
                              if isinstance(s, str) and len(s.strip()) >= 8)
        self._sequence = 0
        self._written = self._dropped = self._failed = self._pending_bytes = 0
        self._last_error = None
        self._closed = False
        self._cv = threading.Condition()
        self._queue = deque()
        self._thread = None
        self._stream = None
        self._part = 0
        self._segment_bytes = 0
        self._space_budget = 0
        self._next_space_check = 0
        self._space_pause = None
        self._space_omitted = 0
        self._space_gap = None

    def status(self):
        with self._cv:
            return {"enabled": self.enabled, "content": self.content, "mode": self.mode,
                    "written": self._written, "dropped": self._dropped, "failed": self._failed,
                    "pending": len(self._queue), "last_error": self._last_error,
                    "space_pause": self._space_pause, "space_omitted": self._space_omitted}

    def register_secret(self, value):
        """Also suppress this server-owned credential if echoed in a free-text field."""
        if isinstance(value, str) and len(value.strip()) >= 8:
            with self._cv:
                self._secrets = (*self._secrets, value.strip())

    def recent_events(self, *, current_run=False, limit=100):
        """Bounded, read-only tail of saved observations, including earlier runs.

        Never follow links, load arbitrary paths, wait for the writer or alter the
        stored records. An active writer's incomplete final line is ignored.
        """
        if _has_link(self.directory):
            raise OSError("unsafe trace directory")
        result = {"events": [], "status": self.status(), "limited": False, "clipped": 0}
        if not self.directory.exists():
            return result
        pattern = re.compile(r"\d{8}T\d{12}Z-([0-9a-f-]{36})(?:\.part\d{8})?\.jsonl\Z")
        def candidates():
            with os.scandir(self.directory) as entries:
                for entry in entries:
                    match = pattern.fullmatch(entry.name)
                    if match and (not current_run or match[1] == self.run_id):
                        yield entry.name
        # A bounded recent window avoids reading an entire growing archive.
        names = heapq.nlargest(9, candidates())
        result["limited"] = len(names) > 8
        budget, collected = 8 * 1024 * 1024, []
        for name in names[:8]:
            path = self.directory / name
            try:
                if _has_link(path) or not path.is_file():
                    continue
                with path.open("rb") as source:
                    size = source.seek(0, os.SEEK_END)
                    allowance = min(budget, 1024 * 1024)
                    start = max(0, size - allowance)
                    source.seek(start)
                    raw = source.read(min(size, allowance))
                budget -= len(raw)
                if start:
                    raw = raw.partition(b"\n")[2]
                    result["limited"] = True
                lines = raw.split(b"\n")[:-1]
                found = 0
                for line in reversed(lines):
                    try:
                        row = json.loads(line)
                    except (ValueError, UnicodeError, RecursionError):
                        continue
                    if not isinstance(row, dict) or not isinstance(row.get("type"), str):
                        continue
                    if current_run and row.get("app_run_id") != self.run_id:
                        continue
                    encoded = json.dumps(row, ensure_ascii=True)
                    if len(encoded) > 32768:
                        row = {key: row[key] for key in ("sequence", "type", "app_run_id", "producer", "recorded_at", "observed_at") if key in row}
                        row["viewer_excerpt"] = encoded[:32768]
                        row["viewer_truncated"] = True
                        result["clipped"] += 1
                        encoded = json.dumps(row, ensure_ascii=True)
                    if found >= limit:
                        result["limited"] = True
                        break
                    collected.append((row, len(encoded)))
                    found += 1
            except FileNotFoundError:
                continue  # Another local process may remove an old, finished run.
            if budget <= 0:
                result["limited"] = True
                break
        # Runs may overlap. Merge their tails by receipt time, rather than the
        # start timestamp in each filename, retaining duplicates as observations.
        collected.sort(key=lambda item: (str(item[0].get("recorded_at", "")), item[0].get("sequence", 0)), reverse=True)
        response_bytes = 0
        for row, size in collected:
            if len(result["events"]) >= limit or response_bytes + size > 1024 * 1024:
                result["limited"] = True
                break
            result["events"].append(row)
            response_bytes += size
        return result

    def emit(self, event_type, payload=None, **context):
        if not self.enabled or self._closed:
            return None
        try:
            if not isinstance(event_type, str) or not _event_name.fullmatch(event_type):
                raise ValueError("event_type")
            if _sensitive_text(event_type, self._secrets):
                raise ValueError("sensitive_event_type")
            bound_store, bound = _binding.get()
            if bound_store is self:
                context = {**bound, **context}
            now = _utc()
            event_id = str(uuid.uuid4())
            snapshot = _Snapshot(self.content, self._secrets)
            row = {"schema_version": SCHEMA_VERSION, "type": event_type, "event_id": event_id,
                   "app_run_id": self.run_id, "producer": "server", "observed_at": now,
                   "recorded_at": now, "mode": self.mode}
            for key in _context_keys & context.keys():
                item = context[key]
                if item is None:
                    continue
                if type(item) is int or isinstance(item, str) and _identifier.fullmatch(item):
                    row[key] = snapshot.copy(item, _key(key))
            row["payload"] = snapshot.copy(payload)
            encoded = json.dumps(row, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode("ascii")
            if len(encoded) > MAX_EVENT_BYTES:
                row["payload"] = _marker("event_size_limit", serialized_bytes=len(encoded))
                encoded = json.dumps(row, ensure_ascii=True, separators=(",", ":")).encode("ascii")
            with self._cv:
                if self._closed:
                    return None
                self._sequence += 1
                if len(self._queue) >= MAX_PENDING_EVENTS or self._pending_bytes+len(encoded) > MAX_PENDING_BYTES:
                    self._dropped += 1
                    self._last_error = "queue_full"
                    return None
                if self._thread is None:
                    writer = threading.Thread(target=self._write_loop, name="raw-trace-writer", daemon=True)
                    writer.start()
                    self._thread = writer
                self._queue.append((self._sequence, encoded))
                self._pending_bytes += len(encoded)
                self._cv.notify()
            return event_id
        except Exception as exc:
            with self._cv:
                self._failed += 1
                self._last_error = type(exc).__name__
            return None

    def _open_stream(self):
        if _has_link(self.directory):
            raise OSError("unsafe trace directory")
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        # The initial .jsonl sorts before its .part segments in directory listings.
        extra = f".part{self._part:08d}" if self._part else ""
        path = self.directory / f"{self._stamp}-{self.run_id}{extra}.jsonl"
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        fd = os.open(path, flags, 0o600)
        self._part += 1
        try:
            if _has_link(self.directory):
                raise OSError("unsafe trace directory")
            self._stream = os.fdopen(fd, "wb", buffering=0)
            self._segment_bytes = 0
        except BaseException:
            os.close(fd)
            raise

    def _space_for(self, size):
        """Sample the destination volume on the writer thread, outside the producer lock."""
        now = monotonic()
        if self._space_pause and now < self._next_space_check:
            return False
        if size > self._space_budget or now >= self._next_space_check:
            self._next_space_check = now + SPACE_CHECK_SECONDS
            try:
                # A fresh workspace may not have a trace directory yet.
                target = self.directory
                while not target.is_dir() and target != target.parent:
                    target = target.parent
                free = shutil.disk_usage(target).free
                usable = free - DISK_RESERVE_BYTES
                pause = "low_disk_space" if usable < size else None
                self._space_budget = min(usable, max(SPACE_CHECK_BYTES, size))
            except (OSError, ValueError):
                pause = "space_check_failed"
                self._space_budget = 0
            with self._cv:
                self._space_pause = pause
        if self._space_pause:
            return False
        self._space_budget -= size
        return True

    def _write(self, sequence, encoded, *, loss_summary=False):
        prefix = b'{"sequence":' + str(sequence).encode("ascii") + b','
        if self._space_gap:
            prefix += b'"storage_gap_before":' + json.dumps(self._space_gap).encode("ascii") + b','
        raw = prefix + encoded[1:] + b"\n"
        if not self._space_for(len(raw)):
            if not loss_summary:
                with self._cv:
                    self._space_omitted += 1
                    self._dropped += 1
                    self._last_error = self._space_pause
                if self._space_gap is None:
                    self._space_gap = {"first_sequence": sequence, "last_sequence": sequence, "omitted": 0}
                self._space_gap["last_sequence"] = sequence
                self._space_gap["omitted"] += 1
            return
        try:
            # Rotate at a record boundary. Even a record larger than a test
            # segment target stays intact in a file of its own.
            if self._stream is not None and self._segment_bytes+len(raw) > MAX_SEGMENT_BYTES:
                self._close_stream()
            if self._stream is None:
                self._open_stream()
            if self._stream.write(raw) != len(raw):
                raise OSError("short trace write")
            self._space_gap = None
            self._segment_bytes += len(raw)
            with self._cv:
                self._written += 1
        except (OSError, ValueError) as exc:
            with self._cv:
                self._failed += 1
                self._last_error = type(exc).__name__
            self._close_stream()

    def _close_stream(self):
        if self._stream is not None:
            try:
                self._stream.close()
            except OSError:
                pass
            self._stream = None

    def _write_loop(self):
        try:
            while True:
                with self._cv:
                    self._cv.wait_for(lambda: self._queue or self._closed)
                    if not self._queue:
                        break
                    sequence, encoded = self._queue.popleft()
                    self._pending_bytes -= len(encoded)
                self._write(sequence, encoded)
            if self._dropped or self._failed:
                now = _utc()
                loss = {"schema_version": SCHEMA_VERSION, "type": "trace.loss", "event_id": str(uuid.uuid4()),
                        "producer": "trace_writer", "app_run_id": self.run_id, "observed_at": now,
                        "recorded_at": now, "mode": self.mode, "payload": self.status()}
                self._write(self._sequence+1, json.dumps(loss).encode("ascii"), loss_summary=True)
        finally:
            self._close_stream()

    def close(self):
        with self._cv:
            self._closed = True
            self._cv.notify_all()
            thread = self._thread
        if thread and thread is not threading.current_thread():
            # A stalled device must not prevent the interview server from
            # stopping. The daemon still drains the queue if the host recovers.
            thread.join(timeout=5)
            if thread.is_alive():
                with self._cv:
                    self._last_error = "close_timeout"


@contextmanager
def bind(store=None, **context):
    previous_store, previous = _binding.get()
    selected = previous_store if store is None else store
    fields = {**previous, **context} if selected is previous_store else dict(context)
    token = _binding.set((selected, fields))
    try:
        yield
    finally:
        _binding.reset(token)


def emit(event_type, payload=None, **context):
    store, _ = _binding.get()
    if store is not None:
        return store.emit(event_type, payload, **context)
    return None


def active():
    store, _ = _binding.get()
    return store is not None and store.enabled


def content_enabled():
    store, _ = _binding.get()
    return store is not None and store.content


def wrap(function):
    """Capture only tracing context; callers retain their own context propagation policy."""
    binding = _binding.get()

    @wraps(function)
    def traced(*args, **kwargs):
        token = _binding.set(binding)
        try:
            return function(*args, **kwargs)
        finally:
            _binding.reset(token)
    return traced
