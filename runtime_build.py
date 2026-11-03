"""Public source identity for detecting a running instance from an older build."""
import hashlib
from pathlib import Path


def build_id(root):
    root = Path(root)
    files = [root / name for name in (
        'server.py', 'launcher.py', 'runtime_build.py', 'documents.py',
        'document_service.py', 'knowledge_graph.py', 'knowledge_ai.py')]
    web = root / 'web'
    # Never include settings, saved interviews, private stores, logs, or Git data.
    files.extend(path for path in web.rglob('*')
                 if path.is_file() and path.suffix in ('.html', '.js', '.css', '.svg'))
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(path.relative_to(root).as_posix().encode('utf-8') + b'\0')
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b'<unavailable>')
        digest.update(b'\0')
    return digest.hexdigest()
