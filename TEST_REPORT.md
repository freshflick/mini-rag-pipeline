# Test report — 11 October 2026

The local app was served at `http://127.0.0.1:8010/` and checked in the browser. The six automated integration tests passed. A seeded stress harness passed with five seeds (`20261011`, `42`, `314159`, `8675309`, `20261012`): **5,000 randomized chunking cases, 500 complete replays, and 1,000 malformed API payloads**, plus malformed JSON, oversized requests, and concurrent calls for each seed. `python3 validate.py` passed. The production React build succeeded.

| Area | Cases exercised | Result |
| --- | --- | --- |
| File decoding | UTF-8 BOM, CRLF, Unicode text, invalid UTF-8, empty file | Passed; unusable files were skipped or rejected with a clear error |
| File discovery | Renamed files, nested directory, `.txt`, `.md`, `.markdown`, unsupported `.png`, symlink | Passed; supported regular files indexed without filename assumptions |
| Chunking | Exact source slices and offsets, 256 KiB unbroken text, deterministic replay | Passed |
| Metadata | Reversed header order and missing `Title:` / `Section:` | Passed; fallback warnings recorded |
| Input validation | Duplicate query IDs, malformed query schema, duplicate upload names, unsupported `.pdf`, path traversal | Rejected; existing files preserved |
| API body shape and size | JSON arrays, scalars, `null`, malformed bytes, empty body, oversized declared request | Rejected with HTTP 400, without server errors |
| Replacement | Invalid replacement followed by valid replacement | Passed; old KB remained until a valid replacement was ready |
| Corpus viability | Replacement with fewer than three possible chunks | Rejected before changing the old KB |
| Freshness | New document upload, stale results, replay | Passed; evaluation was hidden until regeneration completed |
| Answering | Relevant demo-profit question, unrelated account-security question, single keywords `account` and `quasarxyz`, topic phrase `document verification` | Cited answer for the specific question; abstention for the unsupported one; clarification for a related keyword; no-match message for an unknown keyword; cited source overview for the topic phrase |
| Grounding | Tampered answer wording absent from cited chunk | Validation rejected it |
| Concurrency | Uploads, replays, and questions submitted together | Passed; API operations completed without corruption |

The sample knowledge base was restored after UI upload testing. Its final replay indexed **4 documents and 4 chunks**. All **5 sample queries** retrieved the expected document in the top three, and all 5 answers were grounded. This score describes only the supplied sample; new knowledge bases can have different retrieval quality.

The app uses extractive answers and local lexical retrieval. It can abstain on heavy paraphrases even when a human would know the answer. The corpus must produce at least three nonempty chunks to meet the required top-3 retrieval format.

The stress pass also found and fixed two defects: non-object JSON requests previously returned HTTP 500, and a too-small replacement KB could previously overwrite a usable one. NUL-containing text files are now skipped as binary-like input.
