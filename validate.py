"""Validate regenerated artifacts independently of the pipeline runner."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

ANSWER_LABELS = {"grounded_answer", "insufficient_context", "conflicting_context"}
RETRIEVAL_STATUSES = {"hit", "partial_hit", "miss"}
REQUIRED = ("chunks.json", "retrieval.json", "answers.json", "eval.json")


def validate_artifacts(root: Path) -> dict:
    root = root.resolve()
    artifacts = root / "artifacts"
    errors: list[str] = []
    data = {}
    for name in REQUIRED + ("grounding_check.json", "chunking_comparison.json"):
        path = artifacts / name
        if not path.is_file():
            errors.append(f"Missing artifact: {path}")
            continue
        try:
            data[name] = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"Invalid JSON in {path}: {exc}")
    if errors:
        raise ValueError("\n".join(errors))
    queries = json.loads((root / "queries.json").read_text(encoding="utf-8-sig"))
    query_ids = {query["query_id"] for query in queries}
    chunks = data["chunks.json"]
    retrieval = data["retrieval.json"]
    answers = data["answers.json"]
    evaluation = data["eval.json"]
    chunk_ids = []
    if not isinstance(chunks, list) or not chunks:
        errors.append("chunks.json must contain chunks")
    else:
        chunk_ids = [chunk.get("chunk_id") for chunk in chunks]
        if len(set(chunk_ids)) != len(chunk_ids):
            errors.append("Chunk IDs are not unique")
        for chunk in chunks:
            if not all(key in chunk for key in ("chunk_id", "doc_title", "section", "text", "start_char", "end_char")):
                errors.append("Chunk is missing a required field")
            elif not isinstance(chunk["text"], str) or not chunk["text"].strip():
                errors.append(f"Empty chunk: {chunk['chunk_id']}")
    def ids(rows):
        return [row.get("query_id") for row in rows] if isinstance(rows, list) else []
    for name, rows in (("retrieval", retrieval), ("answers", answers), ("evaluation", evaluation.get("records", []))):
        if set(ids(rows)) != query_ids or len(ids(rows)) != len(queries):
            errors.append(f"{name} does not process every query exactly once")
    retrieval_by_id = {row["query_id"]: row for row in retrieval}
    for row in retrieval:
        top_k = row.get("top_k")
        if not isinstance(top_k, list) or len(top_k) < 3:
            errors.append(f"{row['query_id']}: fewer than three retrieved chunks")
            continue
        for expected_rank, hit in enumerate(top_k, 1):
            if hit.get("rank") != expected_rank:
                errors.append(f"{row['query_id']}: invalid rank sequence")
            score = hit.get("score")
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
                errors.append(f"{row['query_id']}: retrieval score is not finite numeric")
            if hit.get("chunk_id") not in chunk_ids:
                errors.append(f"{row['query_id']}: unknown retrieved chunk")
    for answer in answers:
        query_id = answer["query_id"]
        label = answer.get("answer_label")
        if label not in ANSWER_LABELS:
            errors.append(f"{query_id}: invalid answer label")
        cited = answer.get("citations")
        used = answer.get("used_chunk_ids")
        if not isinstance(cited, list) or not isinstance(used, list):
            errors.append(f"{query_id}: citations and used_chunk_ids must be arrays")
            continue
        retrieved = retrieval_by_id.get(query_id, {}).get("top_k", [])
        available = {f"[{hit['doc_title']} §{hit['chunk_id']}]": hit for hit in retrieved}
        if label == "grounded_answer" and not cited:
            errors.append(f"{query_id}: grounded answer has no citation")
        for citation in cited:
            if citation not in available:
                errors.append(f"{query_id}: citation is not from retrieval: {citation}")
            elif citation not in answer.get("answer", ""):
                errors.append(f"{query_id}: citation missing from answer text")
        if label == "grounded_answer" and cited and all(c in available for c in cited):
            wording = answer.get("answer", "")
            for citation in cited:
                wording = wording.replace(citation, "")
            wording = wording.strip()
            if not wording or not any(wording in available[c]["chunk_text"] for c in cited):
                errors.append(f"{query_id}: answer wording is absent from cited evidence")
        if set(used) != {available[c]["chunk_id"] for c in cited if c in available}:
            errors.append(f"{query_id}: used_chunk_ids do not match citations")
    for row in evaluation.get("records", []):
        if row.get("retrieval_status") not in RETRIEVAL_STATUSES:
            errors.append(f"{row.get('query_id')}: invalid retrieval status")
    summary = evaluation.get("summary")
    if not isinstance(summary, dict) or not all(key in summary for key in ("top3_hit_rate", "total_queries", "hits", "partial_hits", "misses")):
        errors.append("Aggregate evaluation summary is missing")
    elif summary["total_queries"] != len(queries) or summary["hits"] + summary["partial_hits"] + summary["misses"] != len(queries):
        errors.append("Aggregate evaluation counts are inconsistent")
    checks = data.get("grounding_check.json", [])
    if not isinstance(checks, list) or len(checks) != len(queries) or not all(row.get("passed") for row in checks):
        errors.append("Grounding checks failed")
    if errors:
        raise ValueError("Validation failed:\n- " + "\n- ".join(errors))
    return {"passed": True, "checked_queries": len(queries), "checked_chunks": len(chunks)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).parent)
    args = parser.parse_args()
    print(json.dumps(validate_artifacts(args.root), indent=2))
