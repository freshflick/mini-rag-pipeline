"""Seeded stress harness. Run: python3 tests/fuzz_pipeline.py --seed 20261011."""

from __future__ import annotations

import argparse
import http.client
import json
import random
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server as app_server
from rag_pipeline import (BM25Index, Document, answer_question, chunk_documents,
                          generate_answer, grounding_check, run_pipeline)
from validate import validate_artifacts

FRAGMENTS = (
    "account ", "verification ", "document ", "password ", "withdrawal ",
    "proof of address.\n", "valid for 7 days. ", "café ", "東京 ", "🔒 ",
    "\r\n", "\n\n", "\t", "   ", ". ", "! ", "x" * 820,
)
QUESTIONS = (
    "account", "document verification", "proof of address", "???",
    "How long does verification take?", "Can I withdraw funds?",
    "unknownplanet", "café 東京", "password reset", "Is this valid?",
)


def fuzz_chunks(rng: random.Random, cases: int) -> None:
    for number in range(cases):
        body = "fact " + "".join(rng.choice(FRAGMENTS) for _ in range(rng.randrange(1, 45)))
        header = f"Title: Product topic {number}\nSection: Help\n\n"
        doc = Document(f"kb/random_{number}.txt", f"Product topic {number}", "Help", header + body, len(header))
        docs = [doc, doc, doc]
        for strategy in ("paragraph", "fixed"):
            chunks = chunk_documents(docs, strategy)
            assert chunks == chunk_documents(docs, strategy)
            assert all(chunk["text"] == doc.source[chunk["start_char"]:chunk["end_char"]] for chunk in chunks)
            assert all(chunk["text"].strip() for chunk in chunks)
            assert all(0 <= chunk["start_char"] < chunk["end_char"] <= len(doc.source) for chunk in chunks)
            question = rng.choice(QUESTIONS)
            hits = BM25Index(chunks).search(question)
            assert len(hits) >= 3
            answer = generate_answer("fuzz", question, hits)
            assert grounding_check([answer], [{"query_id": "fuzz", "top_k": hits}])[0]["passed"]


def fuzz_full_replays(rng: random.Random, cases: int) -> None:
    for number in range(cases):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "kb").mkdir()
            titles = []
            for index in range(rng.randrange(3, 7)):
                title = f"{rng.choice(('Account', 'Payment', 'Document', 'Demo'))} topic {number}-{index}"
                titles.append(title)
                separator = "\r\n" if rng.choice((True, False)) else "\n"
                body = (f"The {title.lower()} rule lasts {index + 2} days.{separator}"
                        + "".join(rng.choice(FRAGMENTS) for _ in range(rng.randrange(1, 12))))
                (root / "kb" / f"renamed_{index}.txt").write_text(
                    f"Title: {title}{separator}Section: Help{separator}{separator}{body}",
                    encoding="utf-8", newline="")
            queries = [{"query_id": f"Q{index}", "question": rng.choice(QUESTIONS),
                        "expected_doc_titles": [rng.choice(titles)]}
                       for index in range(rng.randrange(1, 5))]
            (root / "queries.json").write_text(json.dumps(queries), encoding="utf-8")
            run_pipeline(root)
            validate_artifacts(root)
            before = {path.name: path.read_bytes() for path in (root / "artifacts").glob("*.json")}
            run_pipeline(root)
            after = {path.name: path.read_bytes() for path in (root / "artifacts").glob("*.json")}
            assert before == after, f"Non-deterministic replay in case {number}"
            answer_question(root, rng.choice(QUESTIONS))


class QuietHandler(app_server.Handler):
    def log_message(self, *_args):
        pass


def fuzz_api(rng: random.Random, cases: int) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "kb").mkdir()
        for index in range(3):
            (root / "kb" / f"{index}.txt").write_text(
                f"Title: Topic {index}\nSection: Help\n\nTopic {index} lasts {index + 2} days.\n", encoding="utf-8")
        (root / "queries.json").write_text(json.dumps([
            {"query_id": "Q1", "question": "How long does Topic 0 last?", "expected_doc_titles": ["Topic 0"]}
        ]), encoding="utf-8")
        original_root = app_server.ROOT
        app_server.ROOT = root
        server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_port}"

        def request(route: str, payload: object) -> int:
            data = json.dumps(payload).encode("utf-8")
            action = urllib.request.Request(base + route, data=data,
                headers={"Content-Type": "application/json"}, method="POST")
            try:
                with urllib.request.urlopen(action, timeout=10) as response:
                    response.read()
                    return response.status
            except urllib.error.HTTPError as error:
                error.read()
                return error.code

        try:
            for raw in (b"{", b"\xff", b""):
                action = urllib.request.Request(base + "/api/ask", data=raw,
                    headers={"Content-Type": "application/json"}, method="POST")
                try:
                    urllib.request.urlopen(action, timeout=10)
                    raise AssertionError("Malformed JSON unexpectedly succeeded")
                except urllib.error.HTTPError as error:
                    assert error.code == 400
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
            connection.putrequest("POST", "/api/documents")
            connection.putheader("Content-Type", "application/json")
            connection.putheader("Content-Length", str(app_server.MAX_REQUEST + 1))
            connection.endheaders()
            response = connection.getresponse()
            assert response.status == 400
            response.read()
            connection.close()
            invalid = (
                [], None, 42, "text", {},
                {"question": []}, {"question": ""}, {"question": None},
                {"files": []}, {"files": "x"}, {"files": [{"name": "../escape.txt", "content": "x"}]},
                {"files": [{"name": "bad.pdf", "content": "x"}]},
                {"files": [{"name": "empty.txt", "content": " \n"}]},
                {"files": [{"name": "binary.txt", "content": "abc\u0000def"}]},
                {"queries": "wrong"}, {"queries": []},
            )
            routes = ("/api/ask", "/api/documents", "/api/queries")
            for _ in range(cases):
                status = request(rng.choice(routes), rng.choice(invalid))
                assert status != 500, f"Unexpected server error: {status}"
            tasks = [("/api/ask", {"question": "How long does Topic 0 last?"}),
                     ("/api/run", {})] + [
                     ("/api/documents", {"files": [{"name": f"extra_{index}.txt",
                         "content": f"Title: Extra {index}\nSection: Help\n\nExtra {index} lasts 3 days.\n"}]})
                     for index in range(10)]
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(lambda task: request(*task), tasks))
            assert all(status == 200 for status in results), results
            assert request("/api/run", {}) == 200
            validate_artifacts(root)
        finally:
            server.shutdown()
            server.server_close()
            app_server.ROOT = original_root


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20261011)
    parser.add_argument("--chunk-cases", type=int, default=1000)
    parser.add_argument("--replay-cases", type=int, default=100)
    parser.add_argument("--api-cases", type=int, default=200)
    args = parser.parse_args()
    rng = random.Random(args.seed)
    fuzz_chunks(rng, args.chunk_cases)
    fuzz_full_replays(rng, args.replay_cases)
    fuzz_api(rng, args.api_cases)
    print(f"PASS seed={args.seed}: {args.chunk_cases} chunk cases, "
          f"{args.replay_cases} full replays, {args.api_cases} API payloads + concurrent requests")
