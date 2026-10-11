"""Small local API and optional production static server."""

from __future__ import annotations

import json
import re
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from rag_pipeline import ALLOWED_EXTENSIONS, answer_question, chunk_documents, input_fingerprint, load_documents, parse_document, run_pipeline

ROOT = Path(__file__).resolve().parent
MAX_REQUEST = 5 * 1024 * 1024
API_LOCK = threading.RLock()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / "dist"), **kwargs)

    def _json(self, status: int, value) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        size = int(self.headers.get("Content-Length", "0"))
        if size <= 0 or size > MAX_REQUEST:
            raise ValueError("Request must contain JSON smaller than 5 MB")
        return json.loads(self.rfile.read(size).decode("utf-8"))

    def do_GET(self):
        with API_LOCK:
            self._get_locked()

    def _get_locked(self):
        path = urlparse(self.path).path
        if path == "/api/state":
            try:
                docs, warnings = load_documents(ROOT)
                def artifact(name):
                    file = ROOT / "artifacts" / name
                    return json.loads(file.read_text(encoding="utf-8")) if file.is_file() else None
                manifest = artifact("run_manifest.json")
                stale = manifest is None or manifest.get("input_fingerprint") != input_fingerprint(ROOT)
                self._json(200, {"documents": [{"title": d.title, "section": d.section, "path": d.path} for d in docs],
                                 "warnings": warnings, "stale": stale, "manifest": manifest,
                                 "evaluation": artifact("eval.json"), "answers": artifact("answers.json"),
                                 "retrieval": artifact("retrieval.json"),
                                 "comparison": artifact("chunking_comparison.json")})
            except Exception as exc:
                self._json(400, {"error": str(exc)})
            return
        if path.startswith("/api/"):
            self._json(404, {"error": "Unknown API endpoint"})
            return
        if path == "/" and not (ROOT / "dist" / "index.html").is_file():
            self._json(404, {"error": "Frontend not built. Run npm install and npm run build, or use npm run dev."})
            return
        super().do_GET()

    def do_POST(self):
        with API_LOCK:
            self._post_locked()

    def _post_locked(self):
        path = urlparse(self.path).path
        try:
            body = self._body()
            if not isinstance(body, dict):
                raise ValueError("Request body must be a JSON object")
            if path == "/api/run":
                self._json(200, run_pipeline(ROOT))
            elif path in {"/api/ask", "/answer"}:
                question = body.get("question")
                if not isinstance(question, str):
                    raise ValueError("question must be a string")
                self._json(200, answer_question(ROOT, question))
            elif path == "/api/documents":
                files = body.get("files")
                if not isinstance(files, list) or not files:
                    raise ValueError("files must be a nonempty array")
                kb = ROOT / "kb"
                kb.mkdir(exist_ok=True)
                prepared = []
                names = set()
                for item in files:
                    name = item.get("name") if isinstance(item, dict) else None
                    content = item.get("content") if isinstance(item, dict) else None
                    if (not isinstance(name, str) or not name or len(name) > 100 or
                            name != name.strip() or name in {".", ".."} or
                            "/" in name or "\\" in name or re.search(r"[\x00-\x1f\x7f]", name)):
                        raise ValueError(f"Invalid document filename: {name!r}")
                    if Path(name).suffix.lower() not in ALLOWED_EXTENSIONS:
                        raise ValueError(f"Unsupported document type: {name}")
                    if not isinstance(content, str) or not content.strip():
                        raise ValueError(f"Document {name} is empty")
                    if name in names:
                        raise ValueError(f"Duplicate document filename: {name}")
                    names.add(name)
                    prepared.append((name, content))
                with tempfile.TemporaryDirectory(prefix="rag-upload-", dir=ROOT) as temporary:
                    staging_root = Path(temporary)
                    staged_kb = staging_root / "kb"
                    staged_kb.mkdir()
                    for name, content in prepared:
                        target = staged_kb / name
                        target.write_text(content, encoding="utf-8")
                        parsed, _ = parse_document(target, staging_root)
                        if parsed is None:
                            raise ValueError(f"Document {name} has no usable body text")
                    if body.get("replace") is True:
                        staged_docs, _ = load_documents(staging_root)
                        chunk_documents(staged_docs)
                        backup = staging_root / "previous-kb"
                        if kb.exists():
                            kb.replace(backup)
                        try:
                            staged_kb.replace(kb)
                        except Exception:
                            if backup.exists():
                                backup.replace(kb)
                            raise
                    else:
                        for name, _ in prepared:
                            (staged_kb / name).replace(kb / name)
                self._json(200, {"saved": [name for name, _ in prepared]})
            elif path == "/api/queries":
                queries = body.get("queries")
                if not isinstance(queries, list):
                    raise ValueError("queries must be an array")
                candidate = ROOT / "queries.json"
                previous = candidate.read_bytes() if candidate.exists() else None
                candidate.write_text(json.dumps(queries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                try:
                    from rag_pipeline import load_queries
                    load_queries(ROOT)
                except Exception:
                    if previous is None:
                        candidate.unlink(missing_ok=True)
                    else:
                        candidate.write_bytes(previous)
                    raise
                self._json(200, {"saved_queries": len(queries)})
            else:
                self._json(404, {"error": "Unknown API endpoint"})
        except (ValueError, UnicodeError, KeyError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})
        except Exception as exc:
            self._json(500, {"error": str(exc)})


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    print(f"Mini-RAG API on http://localhost:{args.port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
