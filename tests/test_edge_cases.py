import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import server as app_server
from rag_pipeline import answer_question, input_fingerprint, load_documents, load_queries, run_pipeline
from validate import validate_artifacts


def write_queries(root, titles):
    (root / "queries.json").write_text(json.dumps([
        {"query_id": "one", "question": "How many days does delivery take?", "expected_doc_titles": [titles[0]]}
    ]), encoding="utf-8")


class FileEdgeCases(unittest.TestCase):
    def test_large_unbroken_file_chunks_and_replays_deterministically(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "kb").mkdir()
            (root / "kb" / "large.txt").write_text(
                "Section: Notes\nTitle: Long text\n\n" + "x" * (256 * 1024), encoding="utf-8")
            write_queries(root, ["Long text"])
            first = run_pipeline(root)
            first_chunks = (root / "artifacts/chunks.json").read_bytes()
            second = run_pipeline(root)
            self.assertEqual(first_chunks, (root / "artifacts/chunks.json").read_bytes())
            self.assertEqual(first["manifest"]["chunks_created"], second["manifest"]["chunks_created"])
            self.assertGreater(first["manifest"]["chunks_created"], 500)

    def test_bom_crlf_unicode_long_line_and_ignored_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "kb" / "nested").mkdir(parents=True)
            (root / "kb" / "nested" / "guide.txt").write_bytes(
                b"\xef\xbb\xbfTitle: Caf\xc3\xa9 delivery\r\nSection: Shipping\r\n\r\nDelivery takes 4 days.\r\n")
            (root / "kb" / "long.md").write_text(
                "Title: Long text\nSection: Notes\n\n" + "x" * 1300, encoding="utf-8")
            (root / "kb" / "fallback.markdown").write_text("Ask for help if needed.\n", encoding="utf-8")
            (root / "kb" / "empty.txt").write_bytes(b"")
            (root / "kb" / "bad.txt").write_bytes(b"\xff\xfe\xfa")
            (root / "kb" / "binary.txt").write_bytes(b"Title: Binary\nSection: Test\n\nabc\x00def")
            (root / "kb" / "image.png").write_bytes(b"not a document")
            (root / "outside.txt").write_text("Title: Private\nSection: Hidden\n\nDo not index me.\n", encoding="utf-8")
            (root / "kb" / "linked.txt").symlink_to(root / "outside.txt")
            write_queries(root, ["Café delivery"])
            before = input_fingerprint(root)
            result = run_pipeline(root)
            self.assertEqual(before, result["manifest"]["input_fingerprint"])
            self.assertEqual(result["manifest"]["documents_loaded"], 3)
            self.assertGreaterEqual(result["manifest"]["chunks_created"], 5)
            self.assertTrue(any("invalid UTF-8" in note for note in result["manifest"]["warnings"]))
            self.assertTrue(any("contains NUL bytes" in note for note in result["manifest"]["warnings"]))
            self.assertTrue(any("empty file" in note for note in result["manifest"]["warnings"]))
            self.assertTrue(any("missing Title" in note for note in result["manifest"]["warnings"]))
            self.assertEqual(answer_question(root, "How many days does delivery take?")["answer_label"], "grounded_answer")
            self.assertEqual(answer_question(root, "What is the lunar dress code?")["answer_label"], "insufficient_context")
            docs, _ = load_documents(root)
            sources = {doc.path: doc.source for doc in docs}
            chunks = json.loads((root / "artifacts/chunks.json").read_text())
            for chunk in chunks:
                self.assertEqual(chunk["text"], sources[chunk["source_path"]][chunk["start_char"]:chunk["end_char"]])
            self.assertEqual(validate_artifacts(root)["checked_queries"], 1)

    def test_too_small_corpus_and_bad_queries_fail_clearly(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "kb").mkdir()
            (root / "kb" / "only.txt").write_text("Title: Tiny\nSection: General\n\nOne fact.\n", encoding="utf-8")
            write_queries(root, ["Tiny"])
            with self.assertRaisesRegex(ValueError, "At least three"):
                run_pipeline(root)
            (root / "queries.json").write_text(json.dumps([
                {"query_id": "dup", "question": "One?", "expected_doc_titles": ["Tiny"]},
                {"query_id": "dup", "question": "Two?", "expected_doc_titles": ["Tiny"]},
            ]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Duplicate query_id"):
                load_queries(root)

    def test_validation_rejects_answer_that_is_not_in_cited_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "kb").mkdir()
            for number, text in enumerate(("Delivery takes 4 days.", "Returns take 7 days.", "Support replies by email."), 1):
                (root / "kb" / f"{number}.txt").write_text(f"Title: Guide {number}\nSection: Help\n\n{text}\n", encoding="utf-8")
            write_queries(root, ["Guide 1"])
            run_pipeline(root)
            path = root / "artifacts/answers.json"
            answers = json.loads(path.read_text())
            answers[0]["answer"] = "Delivery takes 999 days. " + answers[0]["citations"][0]
            path.write_text(json.dumps(answers), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "absent from cited evidence"):
                validate_artifacts(root)


class UploadEdgeCases(unittest.TestCase):
    def test_rejected_uploads_preserve_kb_and_valid_replacement_marks_stale(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "kb").mkdir()
            original = root / "kb" / "original.txt"
            original.write_text("Title: Original\nSection: Help\n\nDelivery takes 4 days.\n", encoding="utf-8")
            write_queries(root, ["Original"])
            app_server.ROOT = root
            server = ThreadingHTTPServer(("127.0.0.1", 0), app_server.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            unset = object()
            def request(path, payload=unset):
                data = None if payload is unset else json.dumps(payload).encode()
                req = urllib.request.Request(base + path, data=data,
                    headers={"Content-Type": "application/json"}, method="POST" if data else "GET")
                try:
                    with urllib.request.urlopen(req) as response:
                        return response.status, json.load(response)
                except urllib.error.HTTPError as error:
                    return error.code, json.load(error)
            try:
                for route in ("/api/ask", "/api/documents", "/api/queries"):
                    for invalid_body in ([], None, "text", 42):
                        status, _ = request(route, invalid_body)
                        self.assertEqual(status, 400)
                for bad in (
                    [{"name": "../escape.txt", "content": "bad"}],
                    [{"name": "escape\\path.txt", "content": "bad"}],
                    [{"name": "bad.pdf", "content": "bad"}],
                    [{"name": "empty.txt", "content": "Title: No body\nSection: Empty\n"}],
                    [{"name": "same.txt", "content": "fact"}, {"name": "same.txt", "content": "fact"}],
                ):
                    status, _ = request("/api/documents", {"files": bad, "replace": True})
                    self.assertEqual(status, 400)
                    self.assertTrue(original.exists())
                status, _ = request("/api/documents", {"files": [
                    {"name": "too-short.txt", "content": "Title: Small\nSection: Test\n\nOne sentence.\n"}
                ], "replace": True})
                self.assertEqual(status, 400)
                self.assertTrue(original.exists())
                files = [
                    {"name": "shipping.txt", "content": "Title: Shipping\r\nSection: Orders\r\n\r\nDelivery takes 2 days.\r\n"},
                    {"name": "returns.md", "content": "Title: Returns\nSection: Orders\n\nReturns take 30 days.\n"},
                    {"name": "café notes.markdown", "content": "Contact support for help.\n"},
                ]
                status, _ = request("/api/documents", {"files": files, "replace": True})
                self.assertEqual(status, 200)
                self.assertFalse(original.exists())
                self.assertTrue((root / "kb" / "café notes.markdown").exists())
                self.assertEqual(request("/api/state")[1]["stale"], True)
                original_queries = (root / "queries.json").read_bytes()
                status, _ = request("/api/queries", {"queries": [{"query_id": "bad", "question": "Missing expected titles"}]})
                self.assertEqual(status, 400)
                self.assertEqual((root / "queries.json").read_bytes(), original_queries)
                status, _ = request("/api/run", {})
                self.assertEqual(status, 200)
                self.assertEqual(request("/api/state")[1]["stale"], False)
            finally:
                server.shutdown()
                server.server_close()
                app_server.ROOT = Path(app_server.__file__).resolve().parent
