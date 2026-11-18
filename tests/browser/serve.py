"""Isolated browser test server. Every provider response is synthetic; data is disposable."""
from pathlib import Path
import argparse
from contextlib import nullcontext
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace-work", type=Path, help="Empty test directory for a synthetic content trace.")
    args = parser.parse_args()
    if args.trace_work and (not args.trace_work.is_dir() or any(args.trace_work.iterdir())):
        parser.error("--trace-work requires an empty, existing test directory")
    with (nullcontext(args.trace_work) if args.trace_work else tempfile.TemporaryDirectory()) as directory:
        path = Path(directory)
        if args.trace_work:
            client = ConversationProvider()
        else:
            client = OfflineProvider()
        client.incomplete()
        with server.InterviewServer(("127.0.0.1", 0), server.Handler, client=client,
                                    documents_root=path / "documents", knowledge_root=path / "knowledge",
                                    knowledge_settings={"RAW_TRACE_MODE":"content"} if args.trace_work else {}) as httpd:
            print(f"http://127.0.0.1:{httpd.server_port}/", flush=True)
            httpd.serve_forever()
