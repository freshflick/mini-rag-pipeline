"""Deterministic, dependency-free ingestion, retrieval, answering and evaluation."""

from __future__ import annotations

import json
import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


ALLOWED_EXTENSIONS = {".txt", ".md", ".markdown"}
ANSWER_LABELS = {"grounded_answer", "insufficient_context", "conflicting_context"}
RETRIEVAL_STATUSES = {"hit", "partial_hit", "miss"}
STOPWORDS = set("a an and are as at be been by can could did do does for from had has have how i in is it its me my of on or our should that the their them there these this to us was were what when where which who why will with would you your after before about long old currently yesterday".split())
STAGES = (
    "INIT", "DOCUMENTS_LOADED", "DOCUMENTS_CHUNKED", "INDEX_BUILT",
    "RETRIEVAL_COMPLETE", "ANSWERS_GENERATED", "EVALUATION_COMPLETE",
    "VALIDATION_COMPLETE", "RESULTS_FINALISED",
)


class Stage(str, Enum):
    INIT = "INIT"
    DOCUMENTS_LOADED = "DOCUMENTS_LOADED"
    DOCUMENTS_CHUNKED = "DOCUMENTS_CHUNKED"
    INDEX_BUILT = "INDEX_BUILT"
    RETRIEVAL_COMPLETE = "RETRIEVAL_COMPLETE"
    ANSWERS_GENERATED = "ANSWERS_GENERATED"
    EVALUATION_COMPLETE = "EVALUATION_COMPLETE"
    VALIDATION_COMPLETE = "VALIDATION_COMPLETE"
    RESULTS_FINALISED = "RESULTS_FINALISED"


class PipelineState:
    def __init__(self) -> None:
        self.stage = Stage.INIT
        self.history = [self.stage.value]

    def advance(self, next_stage: Stage) -> None:
        current = STAGES.index(self.stage.value)
        if STAGES[current + 1] != next_stage.value:
            raise RuntimeError(f"Invalid pipeline transition: {self.stage.value} -> {next_stage.value}")
        self.stage = next_stage
        self.history.append(next_stage.value)


@dataclass(frozen=True)
class Document:
    path: str
    title: str
    section: str
    source: str
    body_start: int


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def input_fingerprint(root: Path) -> str:
    """Hash the supported input files so stale UI results can be identified."""
    digest = hashlib.sha256()
    kb = root / "kb"
    if kb.is_dir():
        for path in sorted(p for p in kb.rglob("*") if p.is_file() and not p.is_symlink() and p.suffix.lower() in ALLOWED_EXTENSIONS):
            digest.update(str(path.relative_to(root)).encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    query_path = root / "queries.json"
    if query_path.is_file():
        digest.update(b"queries.json\0")
        digest.update(query_path.read_bytes())
    return digest.hexdigest()


def parse_document(path: Path, root: Path) -> tuple[Document | None, list[str]]:
    warnings: list[str] = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            source = handle.read()
    except UnicodeError as exc:
        return None, [f"Skipped {path.relative_to(root)}: invalid UTF-8 ({exc})"]
    if "\x00" in source:
        return None, [f"Skipped {path.relative_to(root)}: contains NUL bytes"]
    if not source.strip():
        return None, [f"Skipped {path.relative_to(root)}: empty file"]

    title = None
    section = None
    offset = 0
    body_start = 0
    in_header = True
    for line in source.splitlines(keepends=True):
        match = re.match(r"^[ \t]*(Title|Section)[ \t]*:[ \t]*(.*?)[ \t]*(?:\r?\n)?$", line, re.I)
        if in_header and match:
            key, value = match.group(1).lower(), match.group(2).strip()
            if key == "title":
                title = value or None
            else:
                section = value or None
            body_start = offset + len(line)
        elif in_header and not line.strip():
            body_start = offset + len(line)
        else:
            in_header = False
        offset += len(line)
    if title is None:
        title = path.stem.replace("_", " ").replace("-", " ").strip() or path.name
        warnings.append(f"{path.relative_to(root)}: missing Title header; used filename")
    if section is None:
        section = "General"
        warnings.append(f"{path.relative_to(root)}: missing Section header; used General")
    if not source[body_start:].strip():
        return None, [f"Skipped {path.relative_to(root)}: no document body"]
    return Document(str(path.relative_to(root)), title, section, source, body_start), warnings


def load_documents(root: Path) -> tuple[list[Document], list[str]]:
    kb = root / "kb"
    if not kb.is_dir():
        raise FileNotFoundError(f"Knowledge base directory does not exist: {kb}")
    paths = sorted(p for p in kb.rglob("*") if p.is_file() and not p.is_symlink() and p.suffix.lower() in ALLOWED_EXTENSIONS)
    if not paths:
        raise ValueError("kb/ contains no supported .txt, .md or .markdown documents")
    docs: list[Document] = []
    warnings: list[str] = []
    for path in paths:
        doc, notes = parse_document(path, root)
        warnings.extend(notes)
        if doc:
            docs.append(doc)
    if not docs:
        raise ValueError("All knowledge base documents were empty or unreadable")
    return docs, warnings


def load_queries(root: Path) -> list[dict[str, Any]]:
    path = root / "queries.json"
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list) or not data:
        raise ValueError("queries.json must be a nonempty array")
    seen = set()
    for number, row in enumerate(data, 1):
        if not isinstance(row, dict):
            raise ValueError(f"Query {number} must be an object")
        if not isinstance(row.get("query_id"), str) or not row["query_id"].strip():
            raise ValueError(f"Query {number} needs a nonempty query_id")
        if row["query_id"] in seen:
            raise ValueError(f"Duplicate query_id: {row['query_id']}")
        seen.add(row["query_id"])
        if not isinstance(row.get("question"), str) or not row["question"].strip():
            raise ValueError(f"Query {row['query_id']} needs a nonempty question")
        titles = row.get("expected_doc_titles")
        if not isinstance(titles, list) or not titles or not all(isinstance(x, str) and x.strip() for x in titles):
            raise ValueError(f"Query {row['query_id']} needs expected_doc_titles")
        points = row.get("ground_truth_answer_points", [])
        if not isinstance(points, list) or not all(isinstance(x, str) for x in points):
            raise ValueError(f"Query {row['query_id']} has invalid ground_truth_answer_points")
    return data


def _break_at(text: str, start: int, limit: int, strategy: str) -> int:
    end = min(len(text), start + limit)
    if end == len(text):
        return end
    window = text[start:end]
    minimum = max(1, int(limit * 0.45))
    patterns = ([r"\r?\n[ \t]*\r?\n", r"\r?\n", r"[.!?][ \t]+", r"\s+"]
                if strategy == "paragraph" else [r"\s+"])
    for pattern in patterns:
        choices = [match.end() for match in re.finditer(pattern, window) if match.end() >= minimum]
        if choices:
            return start + choices[-1]
    return end


def chunk_documents(docs: list[Document], strategy: str = "paragraph") -> list[dict[str, Any]]:
    if strategy not in {"paragraph", "fixed"}:
        raise ValueError(f"Unknown chunking strategy: {strategy}")
    size = 480 if strategy == "paragraph" else 220
    chunks: list[dict[str, Any]] = []
    for doc in docs:
        position = doc.body_start
        while position < len(doc.source):
            end = _break_at(doc.source, position, size, strategy)
            if end <= position:
                raise RuntimeError("Chunker failed to advance")
            text = doc.source[position:end]
            if text.strip():
                chunks.append({
                    "chunk_id": f"chunk_{len(chunks) + 1:04d}",
                    "doc_title": doc.title,
                    "section": doc.section,
                    "text": text,
                    "start_char": position,
                    "end_char": end,
                    "source_path": doc.path,
                })
            position = end
    if len(chunks) < 3:
        raise ValueError("At least three nonempty chunks are needed for top-3 retrieval; add more KB content")
    return chunks


def normalize(token: str) -> str:
    token = token.casefold()
    if token.startswith("withdraw"):
        return "withdraw"
    if token.startswith("expir"):
        return "expir"
    if token.endswith("ies") and len(token) > 5:
        token = token[:-3] + "y"
    elif token.endswith("ing") and len(token) > 6:
        token = token[:-3]
    elif token.endswith("ed") and len(token) > 5:
        token = token[:-2]
    elif token.endswith("s") and not token.endswith("ss") and len(token) > 4:
        token = token[:-1]
    return token


def terms(text: str) -> list[str]:
    return [word for raw in re.findall(r"[\w]+", text, flags=re.UNICODE)
            if (word := normalize(raw)) not in STOPWORDS and len(word) > 1]


class BM25Index:
    def __init__(self, chunks: list[dict[str, Any]]) -> None:
        self.chunks = chunks
        self.vectors: list[Counter[str]] = []
        self.lengths: list[int] = []
        document_frequency: Counter[str] = Counter()
        for chunk in chunks:
            body = terms(chunk["text"])
            title = terms(chunk["doc_title"]) * 2
            section = terms(chunk["section"])
            vector = Counter(body + title + section)
            self.vectors.append(vector)
            self.lengths.append(sum(vector.values()))
            document_frequency.update(vector.keys())
        self.avg_length = sum(self.lengths) / len(self.lengths)
        count = len(chunks)
        self.idf = {term: math.log(1 + (count - frequency + 0.5) / (frequency + 0.5))
                    for term, frequency in document_frequency.items()}

    def search(self, question: str, top_n: int = 3) -> list[dict[str, Any]]:
        query = set(terms(question))
        scored = []
        for index, (chunk, vector, length) in enumerate(zip(self.chunks, self.vectors, self.lengths)):
            score = 0.0
            for term in query:
                count = vector.get(term, 0)
                if count:
                    score += self.idf[term] * (count * 2.2) / (count + 1.2 * (0.25 + 0.75 * length / self.avg_length))
            scored.append((score, index, chunk))
        scored.sort(key=lambda row: (-row[0], row[2]["chunk_id"]))
        return [{"rank": rank, "chunk_id": chunk["chunk_id"], "doc_title": chunk["doc_title"],
                 "section": chunk["section"], "score": round(score, 6), "chunk_text": chunk["text"]}
                for rank, (score, _, chunk) in enumerate(scored[:max(3, top_n)], 1)]


def retrieve(queries: list[dict[str, Any]], index: BM25Index) -> list[dict[str, Any]]:
    return [{"query_id": query["query_id"], "question": query["question"],
             "top_k": index.search(query["question"])} for query in queries]


def citation_for(chunk: dict[str, Any]) -> str:
    return f"[{chunk['doc_title']} §{chunk['chunk_id']}]"


def topic_excerpt(text: str, max_chars: int = 380) -> str:
    """Return a short, literal source slice ending at a line or sentence boundary."""
    source = text.strip()
    if len(source) <= max_chars:
        return source
    prefix = source[:max_chars]
    boundaries = [match.end() for match in re.finditer(r"[.!?](?=\s|$)|\r?\n", prefix)]
    usable = [position for position in boundaries if position >= max_chars // 2]
    return source[:usable[-1]].strip() if usable else prefix.strip()


def generate_answer(query_id: str, question: str, top_k: list[dict[str, Any]]) -> dict[str, Any]:
    query_terms = set(terms(question))
    if len(query_terms) < 2:
        has_related_result = bool(top_k and top_k[0]["score"] > 0)
        message = ("Please ask a more specific question so I can select the right evidence from the documents."
                   if has_related_result else
                   "I couldn't find relevant information for that keyword. Please try a more specific question.")
        return {"query_id": query_id, "answer_label": "insufficient_context",
                "answer_reason": "underspecified_question" if has_related_result else "no_matching_evidence",
                "answer": message, "citations": [], "used_chunk_ids": []}
    first_word = re.search(r"\w+", question.casefold())
    question_openers = {"what", "when", "where", "why", "who", "how", "can", "could", "should", "would", "will", "is", "are", "do", "does", "did", "may", "might"}
    is_topic_phrase = len(query_terms) <= 5 and (not first_word or first_word.group() not in question_openers)
    if is_topic_phrase and top_k and top_k[0]["score"] > 0:
        top = top_k[0]
        heading_terms = set(terms(top["doc_title"] + " " + top.get("section", "")))
        if query_terms <= heading_terms:
            excerpt = topic_excerpt(top["chunk_text"])
            citation = citation_for(top)
            return {"query_id": query_id, "answer_label": "grounded_answer",
                    "answer_reason": "topic_overview", "answer": f"{excerpt} {citation}",
                    "citations": [citation], "used_chunk_ids": [top["chunk_id"]]}
    candidates = []
    for chunk in top_k:
        if chunk["score"] <= 0:
            continue
        for sentence in re.split(r"(?<=[.!?])\s+|\r?\n+", chunk["chunk_text"]):
            sentence = sentence.strip()
            if len(sentence) < 12:
                continue
            overlap = query_terms & set(terms(sentence))
            if not overlap:
                continue
            coverage = len(overlap) / max(1, len(query_terms))
            score = coverage + 0.06 / chunk["rank"]
            candidates.append((score, coverage, len(overlap), chunk["rank"], sentence, chunk))
    candidates.sort(key=lambda row: (-row[0], -row[2], row[3], row[4]))
    # A single shared word (often a generic noun such as "account") is not evidence.
    # Requiring two distinct content terms trades some recall for safer abstention.
    if not candidates or candidates[0][1] < 0.30 or candidates[0][2] < 2:
        return {"query_id": query_id, "answer_label": "insufficient_context",
                "answer_reason": "weak_evidence",
                "answer": "The retrieved documents do not contain enough evidence to answer this question.",
                "citations": [], "used_chunk_ids": []}
    _, _, _, _, sentence, chunk = candidates[0]
    citation = citation_for(chunk)
    return {"query_id": query_id, "answer_label": "grounded_answer",
            "answer_reason": "source_sentence",
            "answer": f"{sentence} {citation}", "citations": [citation],
            "used_chunk_ids": [chunk["chunk_id"]]}


def evaluate(queries: list[dict[str, Any]], retrieval: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {row["query_id"]: row for row in retrieval}
    records = []
    counts = Counter()
    for query in queries:
        top3 = by_id[query["query_id"]]["top_k"][:3]
        titles = list(dict.fromkeys(chunk["doc_title"] for chunk in top3))
        expected = query["expected_doc_titles"]
        found = [title for title in expected if title in titles]
        status = "hit" if len(found) == len(expected) else "partial_hit" if found else "miss"
        counts[status] += 1
        if status == "hit" and len(expected) == 1:
            rank = next(chunk["rank"] for chunk in top3 if chunk["doc_title"] == expected[0])
            explanation = f"Expected title found at rank {rank}"
        elif status == "hit":
            explanation = f"All {len(expected)} expected titles found in top 3"
        elif status == "partial_hit":
            explanation = f"Found {len(found)} of {len(expected)} expected titles in top 3"
        else:
            explanation = "No expected title found in top 3"
        records.append({"query_id": query["query_id"], "expected_doc_titles": expected,
                        "retrieved_doc_titles_top3": titles, "retrieval_status": status,
                        "matched_expected_title": bool(found), "explanation": explanation})
    total = len(queries)
    return {"records": records, "summary": {"top3_hit_rate": round(counts["hit"] / total, 4),
            "total_queries": total, "hits": counts["hit"], "partial_hits": counts["partial_hit"],
            "misses": counts["miss"]}}


def grounding_check(answers: list[dict[str, Any]], retrieval: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {row["query_id"]: row for row in retrieval}
    result = []
    for answer in answers:
        chunks = {citation_for(chunk): chunk for chunk in by_id[answer["query_id"]]["top_k"]}
        cited = answer["citations"]
        citation_valid = all(citation in chunks for citation in cited)
        evidence = answer["answer"]
        for citation in cited:
            evidence = evidence.replace(citation, "")
        evidence = evidence.strip()
        wording_supported = (answer["answer_label"] != "grounded_answer" or
                             (citation_valid and bool(cited) and any(evidence in chunks[c]["chunk_text"] for c in cited)))
        result.append({"query_id": answer["query_id"], "citation_valid": citation_valid,
                       "wording_supported": wording_supported,
                       "passed": citation_valid and wording_supported})
    return result


def compare_chunking(docs: list[Document], queries: list[dict[str, Any]]) -> dict[str, Any]:
    strategies = {}
    for strategy in ("paragraph", "fixed"):
        chunks = chunk_documents(docs, strategy)
        score = evaluate(queries, retrieve(queries, BM25Index(chunks)))["summary"]
        strategies[strategy] = {"chunk_count": len(chunks), "top3_hit_rate": score["top3_hit_rate"]}
    p, f = strategies["paragraph"], strategies["fixed"]
    if p["top3_hit_rate"] > f["top3_hit_rate"]:
        explanation = "Paragraph chunks retained more context and achieved a higher top-3 hit rate on these queries."
    elif f["top3_hit_rate"] > p["top3_hit_rate"]:
        explanation = "Fixed-size chunks isolated relevant wording and achieved a higher top-3 hit rate on these queries."
    else:
        explanation = "Both strategies had the same top-3 hit rate; paragraph chunks retain more context, while fixed-size chunks provide narrower evidence."
    return {"strategies": strategies, "explanation": explanation}


def run_pipeline(root: Path) -> dict[str, Any]:
    root = root.resolve()
    state = PipelineState()
    docs, warnings = load_documents(root)
    queries = load_queries(root)
    state.advance(Stage.DOCUMENTS_LOADED)
    chunks = chunk_documents(docs)
    save_json(root / "artifacts/chunks.json", chunks)
    state.advance(Stage.DOCUMENTS_CHUNKED)
    index = BM25Index(chunks)
    state.advance(Stage.INDEX_BUILT)
    retrieval = retrieve(queries, index)
    save_json(root / "artifacts/retrieval.json", retrieval)
    state.advance(Stage.RETRIEVAL_COMPLETE)
    answers = [generate_answer(row["query_id"], row["question"], row["top_k"]) for row in retrieval]
    save_json(root / "artifacts/answers.json", answers)
    state.advance(Stage.ANSWERS_GENERATED)
    evaluation = evaluate(queries, retrieval)
    save_json(root / "artifacts/eval.json", evaluation)
    state.advance(Stage.EVALUATION_COMPLETE)
    checks = grounding_check(answers, retrieval)
    save_json(root / "artifacts/grounding_check.json", checks)
    comparison = compare_chunking(docs, queries)
    save_json(root / "artifacts/chunking_comparison.json", comparison)
    from validate import validate_artifacts
    validation = validate_artifacts(root)
    state.advance(Stage.VALIDATION_COMPLETE)
    state.advance(Stage.RESULTS_FINALISED)
    manifest = {"stages": state.history, "input_fingerprint": input_fingerprint(root),
                "documents_loaded": len(docs), "chunks_created": len(chunks),
                "queries_processed": len(queries), "warnings": warnings, "validation": validation}
    save_json(root / "artifacts/run_manifest.json", manifest)
    return {"manifest": manifest, "evaluation": evaluation, "comparison": comparison}


def answer_question(root: Path, question: str) -> dict[str, Any]:
    if not question.strip():
        raise ValueError("Question cannot be empty")
    docs, _ = load_documents(root)
    chunks = chunk_documents(docs)
    top_k = BM25Index(chunks).search(question)
    return {"question": question, "retrieval": top_k,
            **generate_answer("interactive", question, top_k)}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run the replayable mini-RAG pipeline")
    parser.add_argument("--root", type=Path, default=Path(__file__).parent)
    args = parser.parse_args()
    print(json.dumps(run_pipeline(args.root), ensure_ascii=False, indent=2))
