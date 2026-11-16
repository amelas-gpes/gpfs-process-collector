"""Public source identity for detecting a running instance from an older build."""
import hashlib
import os
from pathlib import Path


def instance_id(root):
    """Distinguish identical builds launched from different workspaces."""
    return hashlib.sha256(os.fsencode(os.path.normcase(str(Path(root).resolve())))).hexdigest()


def build_id(root):
    root = Path(root)
    files = [root / name for name in (
        'server.py', 'draft_audit.py', 'provider_schema.py', 'provider_usage.py', 'raw_trace.py', 'launcher.py', 'runtime_build.py', 'documents.py',
        'document_service.py', 'knowledge_graph.py', 'knowledge_ai.py',
        'gpfs_interview.py', 'interview_coverage.py', 'agent_team.py', 'interview_orchestrator.py', 'capture_facts.py', 'concurrent_interview.py', 'prompt_catalog.py', 'FOUNDATION.md')]
    web = root / 'web'
    # Never include settings, saved interviews, private stores, logs, or Git data.
    files.extend(path for path in web.rglob('*')
                 if path.is_file() and path.suffix in ('.html', '.js', '.css', '.svg'))
    digest = hashlib.sha256()
    for path in sorted(files):
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
