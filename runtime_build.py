"""Public source identity for detecting a running instance from an older build."""
import hashlib
import os
from pathlib import Path


def instance_id(root):
    """Distinguish identical builds launched from different workspaces."""
    return hashlib.sha256(os.fsencode(os.path.normcase(str(Path(root).resolve())))).hexdigest()


# The page files the server serves (server.py STATIC_FILES), relative to web/.
WEB_FILES = (
    'agent-flow.css', 'agent-flow.js', 'agent-settings.js', 'agent-team.css', 'agent-team.js', 'app.js',
    'assets/gpfs-logo.svg', 'assets/gpfs-symbol.svg', 'component-library.css', 'component-library.js',
    'concurrent-interview.js', 'context-help.js', 'controlled-voice.js', 'document-intake.js', 'documents.css',
    'documents.js', 'gpfs-presence.css', 'gpfs-presence.js', 'index.html', 'knowledge-ui.css', 'knowledge-ui.js',
    'live-voice-tap.js', 'live-voice.js', 'log-viewer.js', 'raw-trace.js', 'settings-ui.js', 'settings.css', 'style.css',
    'theme.js', 'vendor/elk.bundled.js', 'workflow-component-art.js', 'workflow-components.js', 'workflow-exports.js',
    'workflow-graph.js', 'workflow-layout-worker.js', 'workflow-stage.css', 'workflow-stage.js',
    'workflow-walkthrough.css', 'workflow-walkthrough.js',
)


def source_files(root):
    """The files that name a build: the server's modules and rules, and the page files it serves."""
    root = Path(root)
    files = [root / name for name in (
        'server.py', 'draft_audit.py', 'provider_schema.py', 'provider_usage.py', 'raw_trace.py', 'launcher.py', 'runtime_build.py', 'documents.py',
        'document_service.py', 'knowledge_graph.py', 'knowledge_ai.py',
        'gpfs_interview.py', 'interview_coverage.py', 'agent_team.py', 'interview_orchestrator.py', 'capture_facts.py', 'file_parts.py', 'concurrent_interview.py', 'prompt_catalog.py', 'FOUNDATION.md')]
    # Never include settings, saved interviews, private stores, logs, or Git data. The page files are
    # exactly the ones the server serves (its STATIC_FILES; a test keeps the two equal), not whatever
    # lies in web/: a stray copy such as an iCloud "app 2.js" is never served, so it must neither change
    # the build nor make a running server report that its files have changed.
    files.extend(root / 'web' / name for name in WEB_FILES)
    return sorted(files)


def source_stamp(root):
    """A cheap stand-in for build_id between checks: size, times and inode of each source file. When it
    is unchanged the files are too, and a running server need not read them all again."""
    stamp = []
    for path in source_files(root):
        try:
            info = path.stat()
            stamp.append((str(path), info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino))
        except OSError:
            stamp.append((str(path), None))
    return tuple(stamp)


def build_id(root):
    root = Path(root)
    digest = hashlib.sha256()
    for path in source_files(root):
        digest.update(path.relative_to(root).as_posix().encode('utf-8') + b'\0')
        try:
            # Every hashed file is text. Git checks one commit out with CRLF or LF line
            # ends depending on the computer and always archives it with LF, so a working
            # tree and a desktop release of the same commit must hash alike.
            digest.update(path.read_bytes().replace(b'\r\n', b'\n'))
        except OSError:
            digest.update(b'<unavailable>')
        digest.update(b'\0')
    return digest.hexdigest()
