"""Isolated browser test server. Every provider response is synthetic; data is disposable."""
from pathlib import Path
import sys
import tempfile

app_dir = Path(__file__).resolve().parents[2]
tests = app_dir / "tests"
sys.path.insert(0, str(tests))
from test_interview_orchestrator import SyntheticTeamProvider
from test_server import server


class OfflineProvider(SyntheticTeamProvider):
    def public_config(self):
        return {**super().public_config(), "synthetic_test": True}

    def transcribe(self, audio, media_type):
        return {"text": "A fictional coordinator registers the request."}


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        client = OfflineProvider()
        client.incomplete()
        with server.InterviewServer(("127.0.0.1", 0), server.Handler, client=client,
                                    documents_root=path / "documents", knowledge_root=path / "knowledge",
                                    knowledge_settings={}) as httpd:
            print(f"http://127.0.0.1:{httpd.server_port}/", flush=True)
            httpd.serve_forever()
