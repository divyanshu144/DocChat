#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = ROOT / "reports"
sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.services import llm  # noqa: E402


@dataclass(frozen=True)
class EvalChunk:
    source_id: str
    source_type: str
    text: str
    metadata: dict


@dataclass(frozen=True)
class EvalCase:
    label: str
    query: str
    required_terms: list[list[str]]
    expected_source_ids: list[str]
    forbidden_terms: list[str] = field(default_factory=list)


@dataclass
class EvalResult:
    label: str
    provider: str
    embedding_model: str
    retrieval_top_k: int
    prompt_profile: str
    latency_ms: float
    retrieved_source_ids: list[str]
    missing_terms: list[str]
    forbidden_hits: list[str]
    source_recall: float
    passed: bool
    answer: str


CORPUS = [
    EvalChunk(
        source_id="architecture-pdf",
        source_type="pdf",
        text=(
            "DocChat uses BAAI/bge-small-en-v1.5 through fastembed. The embedding vectors "
            "are 384-dimensional float32 arrays stored in Qdrant."
        ),
        metadata={"filename": "architecture.pdf", "page_number": 2},
    ),
    EvalChunk(
        source_id="ingestion-pdf",
        source_type="pdf",
        text=(
            "PDF ingestion extracts text with PyMuPDF. If a scanned page has no text layer, "
            "pytesseract OCR is used as a fallback before chunking."
        ),
        metadata={"filename": "ingestion.pdf", "page_number": 4},
    ),
    EvalChunk(
        source_id="youtube-demo",
        source_type="youtube",
        text=(
            "YouTube ingestion fetches transcripts with youtube-transcript-api. Transcript "
            "segments are grouped into roughly 60 second chunks before embedding."
        ),
        metadata={"title": "DocChat ingestion demo", "timestamp_start": 120},
    ),
    EvalChunk(
        source_id="web-docs",
        source_type="web",
        text=(
            "Web ingestion uses httpx for HTTP requests and trafilatura for readable content "
            "extraction. The extracted article text is chunked and stored with URL metadata."
        ),
        metadata={"url": "https://docs.example.com/web-ingestion"},
    ),
]


CASES = [
    EvalCase(
        label="embedding_model",
        query="What embedding model does DocChat use and what vector dimension does it produce?",
        required_terms=[["bge-small-en-v1.5", "BAAI/bge-small-en-v1.5"], ["384"]],
        expected_source_ids=["architecture-pdf"],
        forbidden_terms=["768", "OpenAI embeddings"],
    ),
    EvalCase(
        label="pdf_ocr",
        query="What fallback handles scanned PDF pages with no embedded text?",
        required_terms=[["pytesseract", "OCR"], ["fallback"], ["scanned"]],
        expected_source_ids=["ingestion-pdf"],
        forbidden_terms=["youtube-transcript-api", "trafilatura"],
    ),
    EvalCase(
        label="multi_source_ingestion",
        query="Compare the libraries used for PDF, YouTube, and web ingestion.",
        required_terms=[["PyMuPDF"], ["pytesseract"], ["youtube-transcript-api"], ["httpx"], ["trafilatura"]],
        expected_source_ids=["ingestion-pdf", "youtube-demo", "web-docs"],
        forbidden_terms=["Selenium"],
    ),
]


PROMPTS = {
    "baseline": (
        "Answer the question using only the context. If the context is insufficient, say so.\n\n"
        "Context:\n{context}\n\nQuestion: {query}"
    ),
    "strict_cited": (
        "You are evaluating a RAG answer. Use only the context below, include the concrete "
        "terms from the context, and do not invent facts. End with a short Sources section "
        "listing source IDs.\n\nContext:\n{context}\n\nQuestion: {query}"
    ),
}


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def _format_context(chunks: Iterable[EvalChunk]) -> str:
    return "\n\n---\n\n".join(
        f"Source ID: {chunk.source_id}\nSource type: {chunk.source_type}\n{chunk.text}"
        for chunk in chunks
    )


def _score(case: EvalCase, answer: str, retrieved: list[EvalChunk]) -> tuple[list[str], list[str], float, bool]:
    answer_l = answer.lower()
    missing = [
        " | ".join(group)
        for group in case.required_terms
        if not any(term.lower() in answer_l for term in group)
    ]
    forbidden = [term for term in case.forbidden_terms if term.lower() in answer_l]
    retrieved_ids = {chunk.source_id for chunk in retrieved}
    expected = set(case.expected_source_ids)
    source_recall = len(expected & retrieved_ids) / len(expected) if expected else 1.0
    passed = not missing and not forbidden and math.isclose(source_recall, 1.0)
    return missing, forbidden, source_recall, passed


def _embed_texts(model_name: str, texts: list[str]) -> list[np.ndarray]:
    from fastembed import TextEmbedding

    embedder = TextEmbedding(model_name=model_name)
    return [vec.astype(np.float32) for vec in embedder.embed(texts)]


async def _run_case(
    case: EvalCase,
    *,
    provider: str,
    embedding_model: str,
    retrieval_top_k: int,
    prompt_profile: str,
    corpus_embeddings: list[np.ndarray],
) -> EvalResult:
    query_vec = _embed_texts(embedding_model, [case.query])[0]
    ranked = sorted(
        zip(CORPUS, corpus_embeddings, strict=True),
        key=lambda item: _cosine(query_vec, item[1]),
        reverse=True,
    )
    retrieved = [chunk for chunk, _ in ranked[:retrieval_top_k]]
    prompt = PROMPTS[prompt_profile].format(context=_format_context(retrieved), query=case.query)

    settings.llm_provider = provider  # type: ignore[assignment]
    llm._client = None
    llm._client_provider = None

    start = time.perf_counter()
    answer = await llm.chat_complete([{"role": "user", "content": prompt}], max_tokens=700)
    latency_ms = round((time.perf_counter() - start) * 1000, 2)

    missing, forbidden, source_recall, passed = _score(case, answer, retrieved)
    return EvalResult(
        label=case.label,
        provider=provider,
        embedding_model=embedding_model,
        retrieval_top_k=retrieval_top_k,
        prompt_profile=prompt_profile,
        latency_ms=latency_ms,
        retrieved_source_ids=[chunk.source_id for chunk in retrieved],
        missing_terms=missing,
        forbidden_hits=forbidden,
        source_recall=source_recall,
        passed=passed,
        answer=answer,
    )


async def run_matrix(args: argparse.Namespace) -> dict:
    results: list[EvalResult] = []
    total = len(args.providers) * len(args.embedding_models) * len(args.retrieval_top_k) * len(args.prompt_profiles) * len(CASES)
    index = 0

    for embedding_model in args.embedding_models:
        corpus_embeddings = _embed_texts(embedding_model, [chunk.text for chunk in CORPUS])
        for provider in args.providers:
            for retrieval_top_k in args.retrieval_top_k:
                for prompt_profile in args.prompt_profiles:
                    for case in CASES:
                        index += 1
                        print(
                            f"[{index}/{total}] provider={provider} embedding={embedding_model} "
                            f"k={retrieval_top_k} prompt={prompt_profile} case={case.label}"
                        )
                        results.append(await _run_case(
                            case,
                            provider=provider,
                            embedding_model=embedding_model,
                            retrieval_top_k=retrieval_top_k,
                            prompt_profile=prompt_profile,
                            corpus_embeddings=corpus_embeddings,
                        ))

    grouped: dict[str, dict] = {}
    for result in results:
        key = "|".join([
            result.provider,
            result.embedding_model,
            str(result.retrieval_top_k),
            result.prompt_profile,
        ])
        bucket = grouped.setdefault(key, {
            "provider": result.provider,
            "embedding_model": result.embedding_model,
            "retrieval_top_k": result.retrieval_top_k,
            "prompt_profile": result.prompt_profile,
            "total": 0,
            "passed": 0,
            "avg_latency_ms": 0.0,
            "avg_source_recall": 0.0,
        })
        bucket["total"] += 1
        bucket["passed"] += int(result.passed)
        bucket["avg_latency_ms"] += result.latency_ms
        bucket["avg_source_recall"] += result.source_recall

    for bucket in grouped.values():
        bucket["pass_rate"] = bucket["passed"] / bucket["total"] if bucket["total"] else 0.0
        bucket["avg_latency_ms"] = round(bucket["avg_latency_ms"] / bucket["total"], 2)
        bucket["avg_source_recall"] = round(bucket["avg_source_recall"] / bucket["total"], 3)

    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "cases": [asdict(case) for case in CASES],
        "summary": list(grouped.values()),
        "results": [asdict(result) for result in results],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare RAG settings on a fixed DocChat eval set.")
    parser.add_argument("--providers", nargs="+", default=[settings.llm_provider], choices=["groq", "mistral", "openai"])
    parser.add_argument("--embedding-models", nargs="+", default=[settings.embedding_model])
    parser.add_argument("--retrieval-top-k", nargs="+", type=int, default=[2, 3])
    parser.add_argument("--prompt-profiles", nargs="+", default=["baseline", "strict_cited"], choices=sorted(PROMPTS))
    parser.add_argument("--out", type=Path, default=None)
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()
    report = await run_matrix(args)
    REPORT_DIR.mkdir(exist_ok=True)
    out = args.out or REPORT_DIR / f"rag_harness_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {out}")
    for row in report["summary"]:
        print(
            f"{row['provider']} {row['embedding_model']} k={row['retrieval_top_k']} "
            f"{row['prompt_profile']}: pass_rate={row['pass_rate']:.2f} "
            f"source_recall={row['avg_source_recall']:.2f} latency={row['avg_latency_ms']}ms"
        )


if __name__ == "__main__":
    asyncio.run(main())
