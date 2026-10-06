"""Capture a versioned, source-grounded answer-quality workload from Qdrant.

Planner source selection is pinned from the existing golden labels so repeated
serving runs see identical sources. Query embeddings, Qdrant retrieval, reranking,
context formatting, citations, and the synthesis system prompt use DocChat code.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchAny

from app.agent.nodes.retriever import _rerank
from app.agent.nodes.synthesizer import _SYSTEM, _format_chunks
from app.core.config import settings
from app.core.sources import citation_label, source_collection
from app.services.embedder import get_embedder
from eval.workloads import Message, WorkloadCase, Workloads

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GOLDEN = ROOT / "eval" / "retrieval_golden.json"


def _context_chunks(chunks: list[dict]) -> list[dict]:
    """Mirror the synthesizer's 12,000-character context budget."""
    used = []
    remaining = settings.context_max_chars
    for chunk in chunks:
        label = citation_label(chunk.get("source_type", "unknown"), chunk.get("metadata", {}))
        text = chunk["text"].strip()
        entry = f"Source marker: {label}\n{text}"
        if len(entry) > remaining:
            if remaining > 500:
                used.append(chunk)
            break
        used.append(chunk)
        remaining -= len(entry)
    return used


def _extra_cases(source_by_type: dict[str, str], source_ids: list[str], chunks: list[dict]) -> list[dict]:
    by_source: dict[str, list[str]] = defaultdict(list)
    for point in chunks:
        by_source[str(point["payload"]["source_id"])].append(str(point["id"]))
    pdf = source_by_type.get("pdf")
    web = source_by_type.get("web")
    if not pdf or not web:
        raise ValueError("The workload requires at least one PDF and one web source")

    cases = [
        {"id": "heldout-rag-vector-types", "split": "held_out", "category": "document_qa",
         "query": "How does the article distinguish sparse vector encoding from dense vector encoding?",
         "source_ids": [web], "expected_evidence": ["b52ac8c7-c659-5819-81b8-1d0c14896510"],
         "expected_facts": ["Sparse vectors encode word identity; dense vectors encode meaning."],
         "max_tokens": 300},
        {"id": "heldout-rag-hybrid-search", "split": "held_out", "category": "document_qa",
         "query": "What search technique does the article suggest when semantic vector search misses important facts?",
         "source_ids": [web], "expected_evidence": ["73bfa23a-88ad-592b-801a-f9c3021ee3d6"],
         "expected_facts": ["Use traditional text search and combine its results with chunks linked to vector results."],
         "max_tokens": 300},
        {"id": "heldout-rag-source-checking", "split": "held_out", "category": "document_qa",
         "query": "According to the article, how can readers verify a RAG answer's cited sources?",
         "source_ids": [web], "expected_evidence": ["ada32a72-a8de-59bd-895b-aa186cc9fa45"],
         "expected_facts": ["Readers can cross-check retrieved content to check accuracy and relevance."],
         "max_tokens": 300},
        {"id": "heldout-rag-source-misreading", "split": "held_out", "category": "document_qa",
         "query": "Can a model still answer incorrectly when RAG retrieves factually correct material, and why?",
         "source_ids": [web], "expected_evidence": ["b44c566c-0452-5bb9-b275-304f36fea17b"],
         "expected_facts": ["Yes. The model can misinterpret the context even when retrieved sources are factually correct."],
         "max_tokens": 300},
        {"id": "heldout-pdf-false-record-penalty", "split": "held_out", "category": "document_qa",
         "query": "What maximum fine does the declaration associate with a knowingly false working-time record?",
         "source_ids": [pdf], "expected_evidence": ["7f02e868-34df-5c65-9015-c64be231fda4"],
         "expected_facts": ["A worker may face a fine of up to £5,000 on conviction."],
         "max_tokens": 300},
        {"id": "heldout-pdf-other-work-scope", "split": "held_out", "category": "document_qa",
         "query": "Which kinds of work for other employers must be included when calculating the working-time limit?",
         "source_ids": [pdf], "expected_evidence": ["7f02e868-34df-5c65-9015-c64be231fda4"],
         "expected_facts": ["All work for other employers is included, including transport and non-transport work."],
         "max_tokens": 300},
        {"id": "summary-worktime", "category": "summarisation", "query":
         "Summarise the declaration's working-time limits, breaks, reference periods, and worker responsibilities.",
         "source_ids": [pdf], "expected_evidence": by_source[pdf], "max_tokens": 550},
        {"id": "summary-rag", "category": "summarisation", "query":
         "Summarise how retrieval-augmented generation works, its benefits, and its limitations.",
         "source_ids": [web], "expected_evidence": by_source[web], "max_tokens": 650},
        {"id": "long-rag-lifecycle", "category": "long_context", "query":
         "Using the full article context, explain RAG's origin, retrieval and augmentation process, data sources, and limitations.",
         "source_ids": [web], "expected_evidence": by_source[web], "max_tokens": 850},
        {"id": "long-worktime-rules", "category": "long_context", "query":
         "Across the declaration, explain the limits for weekly work, night work, breaks, reference periods, and other employment.",
         "source_ids": [pdf], "expected_evidence": by_source[pdf], "max_tokens": 800},
        {"id": "long-rag-grounding", "category": "long_context", "query":
         "Explain what RAG can and cannot do to improve answer grounding, and how retrieved sources support verification.",
         "source_ids": [web], "expected_evidence": by_source[web], "max_tokens": 700},
        {"id": "multi-document-overview", "category": "multi_document", "query":
         "Compare the purpose and key information in the working-time declaration and the RAG article.",
         "source_ids": source_ids, "expected_evidence": by_source[pdf] + by_source[web], "max_tokens": 800},
        {"id": "multi-document-evidence", "category": "multi_document", "query":
         "Which source describes employment rules and which explains a way to ground language-model answers? Summarise the evidence from each.",
         "source_ids": source_ids, "expected_evidence": by_source[pdf] + by_source[web], "max_tokens": 650},
        {"id": "negative-slack-incident", "category": "negative_control", "query":
         "What was the Slack incident ID for DocChat's most recent production database outage?",
         "source_ids": source_ids, "expected_evidence": [], "max_tokens": 250},
        {"id": "negative-model-owner", "category": "negative_control", "query":
         "Which engineer owns DocChat's production embedding service, and what is their on-call phone number?",
         "source_ids": source_ids, "expected_evidence": [], "max_tokens": 250},
        {"id": "negative-threshold", "category": "negative_control", "query":
         "What exact confidence threshold does DocChat use to automatically approve generated answers?",
         "source_ids": source_ids, "expected_evidence": [], "max_tokens": 250},
    ]
    for case in cases:
        case.setdefault("split", "held_out")
    return cases


def capture(golden_path: Path, qdrant_url: str) -> Workloads:
    golden = json.loads(golden_path.read_text())["cases"]
    client = QdrantClient(url=qdrant_url, timeout=20)
    corpus = []
    offset = None
    try:
        while True:
            points, offset = client.scroll(source_collection(), limit=100, offset=offset,
                                           with_payload=True, with_vectors=False)
            corpus.extend(point.model_dump() for point in points)
            if offset is None:
                break

        by_id = {str(point["id"]): point for point in corpus}
        if not corpus:
            raise ValueError("Qdrant collection is empty")
        source_by_type: dict[str, str] = {}
        for point in corpus:
            payload = point["payload"]
            source_by_type.setdefault(str(payload.get("source_type", "unknown")),
                                      str(payload["source_id"]))
        sources = sorted({str(point["payload"]["source_id"]) for point in corpus})

        rows: list[dict] = []
        for case in golden:
            source_ids = sorted({str(row["source_id"]) for row in case["expected_sources"]})
            if any(point_id not in by_id for point_id in case["relevant_ids"]):
                raise ValueError(f"{case['id']}: relevance labels do not match the live corpus")
            rows.append({"id": case["id"], "category": "document_qa", "query": case["query"],
                         "source_ids": source_ids, "expected_evidence": case["relevant_ids"],
                         "expected_facts": [evidence["quote"] for evidence in case["evidence"]],
                         "max_tokens": 350})
        for case in _extra_cases(source_by_type, sources, corpus):
            case.setdefault("split", "held_out")
            rows.append(case)

        embedder = get_embedder()
        if embedder is None:
            raise RuntimeError("DocChat query embedder could not be initialized")
        captured = []
        for row in rows:
            vector = embedder.embed_query(row["query"]).tolist()
            query_filter = Filter(must=[FieldCondition(key="source_id", match=MatchAny(any=row["source_ids"]))])
            result = client.query_points(collection_name=source_collection(), query=vector,
                                         query_filter=query_filter,
                                         limit=max(12, 8 * len(row["source_ids"])), with_payload=True)
            candidates = []
            for point in result.points:
                payload = dict(point.payload or {})
                candidates.append({"id": str(point.id), "text": payload.pop("text", ""),
                                   "metadata": payload, "source_type": payload.get("source_type", "unknown"),
                                   "score": float(point.score)})
            ranked = _rerank(row["query"], candidates)
            context_chunks = _context_chunks(ranked)
            messages = [
                {"role": "system", "content": _SYSTEM.format(
                    context=_format_chunks(ranked), conversation_history="none")},
                {"role": "user", "content": row["query"]},
            ]
            returned = {candidate["id"] for candidate in context_chunks}
            # For summarisation/long-context/multi-document cases, all context
            # actually supplied is the evidence pool reviewers assess. Gold QA
            # labels remain fixed so retrieval misses stay measurable.
            expected_evidence = (row["expected_evidence"] if row["category"] == "document_qa"
                                 else sorted(returned) if row["expected_evidence"] else [])
            context_source_ids = {str(chunk["metadata"].get("source_id")) for chunk in context_chunks}
            if row["category"] == "multi_document" and len(context_source_ids) < 2:
                raise ValueError(f"{row['id']}: retrieval context did not include both requested sources")
            captured.append(WorkloadCase(
                id=row["id"], split=row.get("split", "development"),
                category=row["category"], query=row["query"],
                source_ids=row["source_ids"], messages=[Message(**message) for message in messages],
                max_tokens=row["max_tokens"], expected_evidence=expected_evidence,
                expected_facts=row.get("expected_facts", []),
                evidence_retrieved=sorted(set(row["expected_evidence"]) & returned),
            ))
    finally:
        client.close()

    rows_digest = sorted((str(point["id"]), point["payload"].get("text", "")) for point in corpus)
    digest = hashlib.sha256(json.dumps(rows_digest, ensure_ascii=False).encode()).hexdigest()
    return Workloads(schema_version=1, corpus_sha256=digest, cases=captured)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument("--qdrant-url", default=f"http://{settings.qdrant_host}:{settings.qdrant_port}")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite {args.output}")
    workloads = capture(args.golden, args.qdrant_url)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output:
        output.write(workloads.model_dump_json(indent=2) + "\n")
    counts: dict[str, int] = defaultdict(int)
    misses = []
    for case in workloads.cases:
        counts[case.category] += 1
        missing = sorted(set(case.expected_evidence) - set(case.evidence_retrieved))
        if missing:
            misses.append({"case_id": case.id, "missing_evidence": missing})
    print(json.dumps({"cases": len(workloads.cases), "categories": counts,
                      "corpus_sha256": workloads.corpus_sha256,
                      "expected_evidence_misses": misses}, indent=2))


if __name__ == "__main__":
    main()
