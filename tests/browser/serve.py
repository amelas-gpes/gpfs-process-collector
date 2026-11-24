"""Isolated browser test server. Every provider response is synthetic; data is disposable."""
from pathlib import Path
import argparse
import sys
import tempfile

app_dir = Path(__file__).resolve().parents[2]
tests = app_dir / "tests"
sys.path.insert(0, str(tests))
from test_concurrent_http import ConversationProvider
from test_document_api import document_result
from test_server import server


class OfflineProvider(ConversationProvider):
    def public_config(self):
        return {**super().public_config(), "synthetic_test": True}

    def transcribe(self, audio, media_type):
        return {"text": "A fictional coordinator registers the request."}

    def analyze_document(self, context, record, chunks, phase, store):
        return document_result(chunks)


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        client = OfflineProvider()
        client.incomplete()
        with server.InterviewServer(("127.0.0.1", 0), server.Handler, client=client,
                                    documents_root=path / "documents", knowledge_root=path / "knowledge",
                                    knowledge_settings={}) as httpd:
            print(f"http://127.0.0.1:{httpd.server_port}/", flush=True)
            httpd.serve_forever()
