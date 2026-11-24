"""Resolve the local server's allowlisted configuration once at startup."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType


logger = logging.getLogger(__name__)


class SettingsError(ValueError):
    """A startup refusal with a safe message and a machine-readable cause."""

    def __init__(self, message: str, *, reason: str = "invalid_value", key: str | None = None):
        super().__init__(message)
        self.reason = reason
        self.key = key


def read_settings_text(path: Path) -> str:
    """The text of a settings file, whichever way a Windows tool saved it.

    Windows PowerShell 5.1 writes UTF-16 for `"KEY=value" > .env.local` and Out-File,
    with a byte-order mark; some editors write UTF-16 without one, which shows as NUL
    bytes (read as UTF-8, every line would then be skipped and the key silently
    ignored). Everything else must be UTF-8. The message never quotes the file.
    """
    try:
        raw = path.read_bytes()
    except OSError:
        raise SettingsError(f"{path.name} could not be opened. Check that the file is readable, "
                            "then start the app again.", reason="unreadable_file") from None
    try:
        if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            return raw.decode("utf-16")
        if b"\x00" in raw:
            # ASCII text in UTF-16 has its zero bytes second (little endian) or first.
            return raw.decode("utf-16-le" if raw[1::2].count(0) >= raw[0::2].count(0) else "utf-16-be")
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise SettingsError(f"{path.name} must be saved as UTF-8. It contains text in another encoding "
                            "(for example an accented letter saved as ANSI). Save the file again as UTF-8, "
                            "then start the app again.", reason="invalid_encoding") from None


# Settings whose empty value is a choice, not a missing one: an empty TRANSCRIPTION_KEYWORDS lists no
# names of your own, where leaving it out uses the built-in ones.
EMPTY_MEANS_NONE = {"TRANSCRIPTION_KEYWORDS"}


def load_settings(root: Path, environ: Mapping[str, str]) -> Mapping[str, str]:
    # Only explicit task-local settings are read; no credential store scanning.
    settings = {}
    allowed = {"OPENAI_API_KEY", "INTERVIEW_MODEL", "DRAFT_MODEL", "DRAFT_AUDIT_MODEL", "DRAFT_COVERAGE_MODEL", "WORKFLOW_AUDIT_MODEL", "TRANSCRIPTION_MODEL", "TRANSCRIPTION_KEYWORDS",
               "COLLECTOR_DEPLOYMENT_MODE", "KNOWLEDGE_LOCAL_OWNER", "AGENT_INTERVIEW_MODEL", "COLLECTOR_MODEL_REASONING", "TRANSCRIPTION_LANGUAGE", 
               "AGENT_COVERAGE_MODEL", "AGENT_PROCESS_MODEL", "AGENT_DOCUMENT_MODEL", "VOICE_MODE", "RAW_TRACE_MODE",
               "COLLECTOR_PROVIDER_SLOTS", "COLLECTOR_MAP_WORKERS", "COLLECTOR_NOTES_WORKERS", "DRAFT_PREPARE", "COLLECTOR_FAST_TIER", "INTERVIEW_MEMORY_ENABLED",
               "LIVE_CAPTION_CHECK", "COLLECTOR_HTTP_CONNECTIONS", "COLLECTOR_BUSY_REPLIES", "COLLECTOR_API_SLOTS",
               "COLLECTOR_UPLOAD_SLOTS", "COLLECTOR_STATUS_WAIT_SLOTS", "COLLECTOR_DOCUMENT_WORKERS"}
    path = root / ".env.local"
    if path.is_file() and not path.is_symlink():
        for number, line in enumerate(read_settings_text(path).splitlines(), 1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if "=" not in line:
                logger.warning("Ignored .env.local line %d: expected NAME=value.", number)
                continue
            key, value = line.split("=", 1)
            key = key.strip().removeprefix("export ").strip()
            if key in allowed:
                value = value.strip()
                if value.startswith(('"', "'", "“", "‘")):
                    end = {'"': '"', "'": "'", "“": "”", "‘": "’"}[value[0]]
                    close = value.rfind(end)
                    if close < 1 or (value[close+1:].strip() and not value[close+1:].lstrip().startswith("#")):
                        raise SettingsError(f"Check the closing quote on .env.local line {number}.", reason="invalid_syntax", key=key)
                    value = value[1:close]
                else:
                    value = re.split(r"\s+#", value, 1)[0].strip()
                if value or key in EMPTY_MEANS_NONE:
                    settings[key] = value
            else:
                logger.warning("Ignored unsupported setting on .env.local line %d.", number)
    for key in allowed:
        raw = environ.get(key)
        value = (raw or "").strip().strip("\"'“”‘’").strip()
        if value or (raw is not None and key in EMPTY_MEANS_NONE):
            settings[key] = value
    return MappingProxyType(settings)


def whole_setting(settings: Mapping[str, str], name: str, default: int, lowest: int, highest: int) -> int:
    """A whole-number setting inside its range, or the default when it is not set."""
    value = settings.get(name)
    if value is None or str(value).strip() == "":
        return default
    if not re.fullmatch(r"[0-9]{1,4}", str(value).strip()) or not lowest <= int(str(value).strip()) <= highest:
        raise SettingsError(f"{name} must be a whole number from {lowest} to {highest}.", key=name)
    return int(str(value).strip())


@dataclass(frozen=True)
class ServerLimits:
    """Validated admission and worker capacities for one server instance."""

    connections: int
    busy_replies: int
    api_slots: int
    uploads: int
    status_waiters: int
    document_workers: int

    @classmethod
    def from_settings(cls, settings: Mapping[str, str], *, connections: int, busy_replies: int,
                      document_workers: int) -> ServerLimits:
        return cls(
            connections=whole_setting(settings, "COLLECTOR_HTTP_CONNECTIONS", connections, 1, 128),
            busy_replies=whole_setting(settings, "COLLECTOR_BUSY_REPLIES", busy_replies, 1, 32),
            api_slots=whole_setting(settings, "COLLECTOR_API_SLOTS", 4, 1, 32),
            uploads=whole_setting(settings, "COLLECTOR_UPLOAD_SLOTS", 2, 1, 8),
            status_waiters=whole_setting(settings, "COLLECTOR_STATUS_WAIT_SLOTS", 6, 1, 32),
            document_workers=whole_setting(settings, "COLLECTOR_DOCUMENT_WORKERS", document_workers, 1, 8),
        )
