#!/usr/bin/env python3
"""
DocChat Benchmarking Suite
===========================
Measures five dimensions of system performance by calling services directly
(no HTTP server required — just the venv and a valid .env).

  1. Ingestion speed      — time & throughput for PDFs of increasing size
  2. Retrieval latency    — cold cache vs warm cache, p50/p95/p99
  3. Reranking precision  — MRR, Hit@k, cross-encoder score vs RRF-only
  4. Semantic cache       — hit rate & latency saving (requires REDIS_URL)
  5. Document scale       — largest document ingested without error

Usage (from project root, venv active):
    python scripts/benchmark.py                    # all benchmarks
    python scripts/benchmark.py --skip-scale       # skip the slow scale test
    python scripts/benchmark.py --pdf my.pdf       # also test a real PDF
    python scripts/benchmark.py --queries 50       # more retrieval samples

Results are printed to stdout AND saved to benchmark_results_<date>.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import tempfile
import time
import tracemalloc
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap: set env vars BEFORE any app import so Settings picks them up
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_BENCH_DB = f"sqlite+aiosqlite:///{ROOT}/benchmark_test.db"
os.environ.setdefault("DATABASE_URL", _BENCH_DB)
os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("RERANK_ENABLED", "true")
os.environ.setdefault("RETRIEVAL_TOP_K", "15")
os.environ.setdefault("RERANK_TOP_K", "5")
# GROQ_API_KEY is read from .env automatically; semantic cache needs REDIS_URL

# ---------------------------------------------------------------------------
# App imports (after env is set)
# ---------------------------------------------------------------------------
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal, Base, engine
from app.models.chunk import Chunk
from app.models.conversation import Conversation
from app.models.document import Document, DocumentStatus
from app.models.message import Message
from app.services import retrieval
from app.services.embedder import get_embedder
from app.services.ingestion import ingest_document
from app.services.reranker import _get_ranker

# ---------------------------------------------------------------------------
# Synthetic document content — known facts with labelled ground-truth queries
# ---------------------------------------------------------------------------

# Each entry: (fact_label, fact_sentence, query_text)
GROUND_TRUTH = [
    (
        "q3_revenue",
        "The Q3 2024 quarterly revenue was exactly 4.231 billion dollars.",
        "What was the Q3 2024 revenue?",
    ),
    (
        "yoy_growth",
        "Year-over-year revenue growth reached precisely 15.7 percent in Q3.",
        "How much did the company grow year over year?",
    ),
    (
        "cac",
        "Customer acquisition cost decreased to 127 dollars per new user this quarter.",
        "What is the customer acquisition cost?",
    ),
    (
        "ebitda",
        "EBITDA margins expanded to 28.5 percent from 24.1 percent in the prior year.",
        "What are the EBITDA margins?",
    ),
    (
        "headcount",
        "Total employee headcount grew to 8432 full-time employees by end of quarter.",
        "How many employees does the company have?",
    ),
]

_LOREM = (
    "The company continues to invest in its core product lines while expanding "
    "into adjacent markets. Strategic partnerships have been established with "
    "several industry leaders to accelerate distribution. Operating leverage "
    "remains a key focus as the team scales efficiently. Research and development "
    "spending increased by twelve percent to support next-generation capabilities. "
    "International markets contributed twenty-two percent of total revenue this period. "
    "The balance sheet remains strong with over two billion in cash and equivalents. "
    "Supply chain improvements reduced cost of goods sold by three percentage points. "
    "Customer satisfaction scores reached an all-time high of 94 out of 100. "
    "The leadership team was strengthened with three executive hires in key functions. "
    "Regulatory approvals were obtained in four new markets during the quarter. "
)


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class IngestionResult:
    label: str
    size_bytes: int
    chunks: int
    elapsed_s: float
    peak_mem_mb: float
    status: str  # "ok" | "error"

    @property
    def chunks_per_sec(self) -> float:
        return self.chunks / self.elapsed_s if self.elapsed_s > 0 else 0.0


@dataclass
class RetrievalResult:
    n_queries: int
    cold_ms: float          # first query (LRU build)
    latencies_ms: list[float] = field(default_factory=list)

    @property
    def p50(self) -> float: return statistics.median(self.latencies_ms) if self.latencies_ms else 0.0
    @property
    def p95(self) -> float: return _percentile(self.latencies_ms, 95)
    @property
    def p99(self) -> float: return _percentile(self.latencies_ms, 99)
    @property
    def mean(self) -> float: return statistics.mean(self.latencies_ms) if self.latencies_ms else 0.0


@dataclass
class RerankerResult:
    n_queries: int
    rrf_mrr: float
    rerank_mrr: float
    rrf_hit1: float
    rerank_hit1: float
    rrf_hit3: float
    rerank_hit3: float
    rrf_avg_score: float
    rerank_avg_score: float
    reorder_rate: float     # fraction of queries where reranker changed top-1


@dataclass
class CacheResult:
    available: bool
    n_unique_queries: int
    n_paraphrase_queries: int
    hits: int
    hit_rate: float
    uncached_ms: float
    cached_ms: float
    speedup: float


@dataclass
class ScaleResult:
    label: str
    size_bytes: int
    pages: int
    chunks: int
    ingest_s: float
    warm_retrieval_ms: float
    status: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _percentile(data: list[float], pct: int) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    k = (len(s) - 1) * pct / 100
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _json_default(obj):
    """Serialize numpy scalars that stdlib json can't handle."""
    try:
        import numpy as np
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
    except ImportError:
        pass
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _fmt_ms(ms: float) -> str:
    if ms >= 1000:
        return f"{ms/1000:.2f}s"
    return f"{ms:.0f}ms"


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def _hr(width: int = 56) -> str:
    return "─" * width


# ---------------------------------------------------------------------------
# PDF / document generation (uses pymupdf — already a dependency)
# ---------------------------------------------------------------------------

def _generate_pdf(target_bytes: int, include_facts: bool = False) -> Path:
    """
    Create a synthetic PDF whose raw size is approximately target_bytes.
    If include_facts=True, embeds GROUND_TRUTH sentences at known positions.
    Returns the path to the temp file.
    """
    import fitz

    tmp = Path(tempfile.mktemp(suffix=".pdf"))
    doc = fitz.open()

    # Estimate chars needed (PDF overhead is ~60 bytes per char of text on average)
    chars_needed = max(target_bytes // 4, 500)
    base_text = _LOREM * (chars_needed // len(_LOREM) + 1)

    # Insert facts at ~1/3 and ~2/3 of the way through (if requested)
    facts_text = ""
    if include_facts:
        for _, sentence, _ in GROUND_TRUTH:
            facts_text += f"\n\n{sentence}\n\n"

    full_text = base_text[: chars_needed // 3] + facts_text + base_text[chars_needed // 3 :]

    # Chunk into pages (~3000 chars per page)
    chars_per_page = 3000
    for i in range(0, len(full_text), chars_per_page):
        page = doc.new_page(width=595, height=842)  # A4
        page.insert_text(
            (50, 50),
            full_text[i : i + chars_per_page],
            fontsize=11,
            fontname="helv",
        )

    doc.save(str(tmp), garbage=4, deflate=True)
    doc.close()
    return tmp


def _create_doc_record(file_path: Path) -> Document:
    """Create an in-memory Document ORM object pointing to the given file."""
    return Document(
        id=str(uuid.uuid4()),
        filename=file_path.name,
        file_path=str(file_path),
        content_type="application/pdf",
        status=DocumentStatus.pending,
    )


# ---------------------------------------------------------------------------
# DB setup / teardown
# ---------------------------------------------------------------------------

async def setup_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def teardown_db() -> None:
    await engine.dispose()
    db_path = ROOT / "benchmark_test.db"
    if db_path.exists():
        db_path.unlink()
    # Remove WAL artefacts
    for ext in ("-wal", "-shm"):
        p = db_path.with_suffix(db_path.suffix + ext)
        if p.exists():
            p.unlink()


# ---------------------------------------------------------------------------
# 1. Ingestion speed benchmark
# ---------------------------------------------------------------------------

async def run_ingestion_benchmark(sizes_kb: list[int]) -> list[IngestionResult]:
    print("\n▸  INGESTION SPEED")
    results: list[IngestionResult] = []

    for kb in sizes_kb:
        label = f"{kb} KB" if kb < 1024 else f"{kb // 1024} MB"
        print(f"   generating {label} PDF…", end=" ", flush=True)
        pdf = _generate_pdf(kb * 1024)
        actual_bytes = pdf.stat().st_size
        doc = _create_doc_record(pdf)

        async with AsyncSessionLocal() as db:
            db.add(doc)
            await db.commit()

            tracemalloc.start()
            t0 = time.perf_counter()
            try:
                await ingest_document(doc, db)
                elapsed = time.perf_counter() - t0
                _, peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()

                r = IngestionResult(
                    label=label,
                    size_bytes=actual_bytes,
                    chunks=doc.chunk_count,
                    elapsed_s=elapsed,
                    peak_mem_mb=peak / 1024**2,
                    status="ok",
                )
                print(f"{r.chunks} chunks in {r.elapsed_s:.1f}s ({r.chunks_per_sec:.1f} ch/s)")
            except Exception as exc:
                tracemalloc.stop()
                elapsed = time.perf_counter() - t0
                r = IngestionResult(
                    label=label,
                    size_bytes=actual_bytes,
                    chunks=0,
                    elapsed_s=elapsed,
                    peak_mem_mb=0.0,
                    status=f"error: {exc}",
                )
                print(f"FAILED — {exc}")
            finally:
                pdf.unlink(missing_ok=True)

        results.append(r)

    return results


# ---------------------------------------------------------------------------
# 2. Retrieval latency benchmark
# ---------------------------------------------------------------------------

async def run_retrieval_benchmark(n_queries: int) -> RetrievalResult:
    print(f"\n▸  RETRIEVAL LATENCY  ({n_queries} queries)")

    # Ingest the known-facts document
    print("   ingesting benchmark document…", end=" ", flush=True)
    pdf = _generate_pdf(200 * 1024, include_facts=True)
    doc = _create_doc_record(pdf)

    async with AsyncSessionLocal() as db:
        db.add(doc)
        await db.commit()
        await ingest_document(doc, db)
    pdf.unlink(missing_ok=True)
    print(f"{doc.chunk_count} chunks ready")

    # Evict from LRU so first query is a cold-cache hit
    retrieval.invalidate_bm25(doc.id)

    queries = [q for _, _, q in GROUND_TRUTH] * (n_queries // len(GROUND_TRUTH) + 1)
    queries = queries[:n_queries]

    cold_ms = 0.0
    warm_latencies: list[float] = []

    async with AsyncSessionLocal() as db:
        for i, q in enumerate(queries):
            t0 = time.perf_counter()
            chunks = await retrieval.retrieve_chunks(
                query=q,
                document_id=doc.id,
                db=db,
                top_k=settings.retrieval_top_k,
            )
            ms = (time.perf_counter() - t0) * 1000

            if i == 0:
                cold_ms = ms
                print(f"   cold-cache first query: {_fmt_ms(ms)}")
            else:
                warm_latencies.append(ms)

    result = RetrievalResult(
        n_queries=n_queries,
        cold_ms=cold_ms,
        latencies_ms=warm_latencies,
    )
    print(
        f"   warm-cache  p50={_fmt_ms(result.p50)}  "
        f"p95={_fmt_ms(result.p95)}  p99={_fmt_ms(result.p99)}  "
        f"mean={_fmt_ms(result.mean)}"
    )
    return result


# ---------------------------------------------------------------------------
# 3. Reranking precision benchmark
# ---------------------------------------------------------------------------

async def run_rerank_benchmark() -> RerankerResult:
    print("\n▸  RERANKING PRECISION  (ground-truth MRR)")

    # Ingest the facts document (reuse if already in DB)
    print("   ingesting facts document…", end=" ", flush=True)
    pdf = _generate_pdf(200 * 1024, include_facts=True)
    doc = _create_doc_record(pdf)
    async with AsyncSessionLocal() as db:
        db.add(doc)
        await db.commit()
        await ingest_document(doc, db)
    pdf.unlink(missing_ok=True)
    print(f"{doc.chunk_count} chunks")

    # Find which chunk_index holds each fact (ground truth)
    from sqlalchemy import select as sa_select
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            sa_select(Chunk.chunk_index, Chunk.text)
            .where(Chunk.document_id == doc.id)
            .order_by(Chunk.chunk_index)
        )).all()

    chunks_by_idx = {row.chunk_index: row.text for row in rows}

    ground_truth_idx: dict[str, int | None] = {}
    for label, sentence, _ in GROUND_TRUTH:
        # Find the chunk that contains the key phrase
        keyword = sentence.split()[4]  # distinctive word in the middle
        gt_idx = None
        for idx, text in chunks_by_idx.items():
            if keyword.lower() in text.lower():
                gt_idx = idx
                break
        ground_truth_idx[label] = gt_idx

    # Ranker instance for direct scoring
    ranker = _get_ranker()

    rrf_reciprocal_ranks: list[float] = []
    rerank_reciprocal_ranks: list[float] = []
    rrf_top1s: list[bool] = []
    rerank_top1s: list[bool] = []
    rrf_top3s: list[bool] = []
    rerank_top3s: list[bool] = []
    rrf_scores: list[float] = []
    rerank_scores: list[float] = []
    reorders: list[bool] = []

    retrieval.invalidate_bm25(doc.id)

    async with AsyncSessionLocal() as db:
        for label, _, query in GROUND_TRUTH:
            gt_idx = ground_truth_idx.get(label)

            # Get top-15 from RRF (no reranking)
            top15 = await retrieval.retrieve_chunks(
                query=query,
                document_id=doc.id,
                db=db,
                top_k=15,
            )

            # RRF-only top-5 (naive truncation)
            rrf_top5 = top15[:5]

            # Score all 15 with cross-encoder to get oracle ranking
            if ranker and top15:
                from flashrank import RerankRequest
                passages = [{"id": i, "text": c} for i, c in enumerate(top15)]
                reranked = ranker.rerank(RerankRequest(query=query, passages=passages))
                reranked_top5 = [r["text"] for r in reranked[:5]]
                reranked_scores_all = {r["id"]: r["score"] for r in reranked}

                # Average cross-encoder score of each set
                rrf_avg = statistics.mean(
                    reranked_scores_all.get(i, 0.0) for i in range(min(5, len(top15)))
                )
                rerank_avg = statistics.mean(r["score"] for r in reranked[:5])
                rrf_scores.append(rrf_avg)
                rerank_scores.append(rerank_avg)

                reorders.append(rrf_top5 != reranked_top5)
            else:
                reranked_top5 = rrf_top5
                reorders.append(False)

            # MRR / Hit@k — match by chunk content containing the fact keyword
            if gt_idx is not None:
                gt_text_snippet = chunks_by_idx.get(gt_idx, "")

                def rank_in(result_list: list[str], snippet: str) -> int | None:
                    for i, text in enumerate(result_list):
                        # Strip the "[Page N, Section ...]" prefix before matching
                        bare = text.split("] ", 1)[-1] if "] " in text else text
                        if any(w in bare.lower() for w in snippet.lower().split()[:6] if len(w) > 4):
                            return i + 1
                    return None

                rrf_rank = rank_in(rrf_top5, gt_text_snippet)
                rerank_rank = rank_in(reranked_top5, gt_text_snippet)

                rrf_reciprocal_ranks.append(1 / rrf_rank if rrf_rank else 0.0)
                rerank_reciprocal_ranks.append(1 / rerank_rank if rerank_rank else 0.0)
                rrf_top1s.append(rrf_rank == 1)
                rerank_top1s.append(rerank_rank == 1)
                rrf_top3s.append(rrf_rank is not None and rrf_rank <= 3)
                rerank_top3s.append(rerank_rank is not None and rerank_rank <= 3)

    def _avg(lst: list) -> float:
        return statistics.mean(lst) if lst else 0.0

    result = RerankerResult(
        n_queries=len(GROUND_TRUTH),
        rrf_mrr=_avg(rrf_reciprocal_ranks),
        rerank_mrr=_avg(rerank_reciprocal_ranks),
        rrf_hit1=_avg(rrf_top1s),
        rerank_hit1=_avg(rerank_top1s),
        rrf_hit3=_avg(rrf_top3s),
        rerank_hit3=_avg(rerank_top3s),
        rrf_avg_score=_avg(rrf_scores),
        rerank_avg_score=_avg(rerank_scores),
        reorder_rate=_avg(reorders),
    )
    print(
        f"   MRR  RRF={result.rrf_mrr:.2f}  Reranked={result.rerank_mrr:.2f}  "
        f"(reorder rate {result.reorder_rate:.0%})"
    )
    return result


# ---------------------------------------------------------------------------
# 4. Semantic cache benchmark
# ---------------------------------------------------------------------------

_PARAPHRASES = [
    ("What was the Q3 2024 revenue?",         "How much revenue did the company earn in Q3 2024?"),
    ("How much did the company grow YoY?",     "What was the year-over-year growth rate?"),
    ("What is the customer acquisition cost?", "How much does it cost to acquire a customer?"),
    ("What are the EBITDA margins?",           "Tell me the EBITDA margin percentage."),
    ("How many employees does the company have?", "What is the total employee headcount?"),
]


async def run_cache_benchmark() -> CacheResult:
    print("\n▸  SEMANTIC CACHE")

    from app.services.semantic_cache import get_semantic_cache
    sc = get_semantic_cache()

    if sc is None:
        print("   SKIPPED — REDIS_URL not set (set REDIS_URL in .env to enable)")
        return CacheResult(
            available=False,
            n_unique_queries=0,
            n_paraphrase_queries=0,
            hits=0,
            hit_rate=0.0,
            uncached_ms=0.0,
            cached_ms=0.0,
            speedup=0.0,
        )

    # Ingest a small document for a doc_id to key cache entries on
    pdf = _generate_pdf(50 * 1024, include_facts=True)
    doc = _create_doc_record(pdf)
    async with AsyncSessionLocal() as db:
        db.add(doc)
        await db.commit()
        await ingest_document(doc, db)
    pdf.unlink(missing_ok=True)

    embedder = get_embedder()
    uncached_times: list[float] = []
    cached_times: list[float] = []
    hits = 0

    for original, paraphrase in _PARAPHRASES:
        # 1. Populate cache with original query
        if embedder:
            import numpy as np
            from concurrent.futures import ThreadPoolExecutor
            loop = asyncio.get_running_loop()
            emb = await loop.run_in_executor(None, embedder.embed_query, original)
        else:
            emb = None

        t0 = time.perf_counter()
        if emb is not None:
            result = await sc.get(emb, doc.id)
            uncached_ms = (time.perf_counter() - t0) * 1000
            uncached_times.append(uncached_ms)

            if result is None:
                # Store a synthetic answer
                await sc.set(emb, f"Synthetic answer for: {original}", doc.id)

        # 2. Query with paraphrase and measure hit/miss
        if embedder:
            para_emb = await loop.run_in_executor(None, embedder.embed_query, paraphrase)
        else:
            para_emb = None

        if para_emb is not None:
            t0 = time.perf_counter()
            cached = await sc.get(para_emb, doc.id)
            cached_ms = (time.perf_counter() - t0) * 1000
            cached_times.append(cached_ms)
            if cached is not None:
                hits += 1
                print(f"   HIT  '{paraphrase[:50]}…'  {_fmt_ms(cached_ms)}")
            else:
                print(f"   MISS '{paraphrase[:50]}…'  {_fmt_ms(cached_ms)}")

    n = len(_PARAPHRASES)
    avg_uncached = statistics.mean(uncached_times) if uncached_times else 0.0
    avg_cached = statistics.mean(cached_times) if cached_times else 0.0
    speedup = avg_uncached / avg_cached if avg_cached > 0 else 0.0

    result = CacheResult(
        available=True,
        n_unique_queries=n,
        n_paraphrase_queries=n,
        hits=hits,
        hit_rate=hits / n,
        uncached_ms=avg_uncached,
        cached_ms=avg_cached,
        speedup=speedup,
    )
    return result


# ---------------------------------------------------------------------------
# 5. Document scale benchmark
# ---------------------------------------------------------------------------

async def run_scale_benchmark(sizes_kb: list[int]) -> list[ScaleResult]:
    print("\n▸  DOCUMENT SCALE")
    results: list[ScaleResult] = []

    for kb in sizes_kb:
        label = f"{kb} KB" if kb < 1024 else f"{kb // 1024} MB"
        print(f"   {label}…", end=" ", flush=True)

        pdf = _generate_pdf(kb * 1024)
        actual_bytes = pdf.stat().st_size
        doc = _create_doc_record(pdf)

        try:
            async with AsyncSessionLocal() as db:
                db.add(doc)
                await db.commit()
                t0 = time.perf_counter()
                await ingest_document(doc, db)
                ingest_s = time.perf_counter() - t0

            # Count pages via pymupdf
            import fitz
            fitz_doc = fitz.open(str(pdf))
            pages = len(fitz_doc)
            fitz_doc.close()

            # Warm retrieval latency
            retrieval.invalidate_bm25(doc.id)
            query = "What is the main topic of this document?"
            async with AsyncSessionLocal() as db:
                # cold hit first
                await retrieval.retrieve_chunks(query=query, document_id=doc.id, db=db, top_k=5)
                # measure warm
                t0 = time.perf_counter()
                await retrieval.retrieve_chunks(query=query, document_id=doc.id, db=db, top_k=5)
                warm_ms = (time.perf_counter() - t0) * 1000

            r = ScaleResult(
                label=label,
                size_bytes=actual_bytes,
                pages=pages,
                chunks=doc.chunk_count,
                ingest_s=ingest_s,
                warm_retrieval_ms=warm_ms,
                status="ok",
            )
            print(
                f"{pages}p  {doc.chunk_count} chunks  "
                f"ingest={_fmt_ms(ingest_s*1000)}  "
                f"retrieval={_fmt_ms(warm_ms)}"
            )

        except Exception as exc:
            r = ScaleResult(
                label=label, size_bytes=actual_bytes, pages=0,
                chunks=0, ingest_s=0.0, warm_retrieval_ms=0.0,
                status=f"error: {exc}",
            )
            print(f"FAILED — {exc}")
        finally:
            pdf.unlink(missing_ok=True)

        results.append(r)

    return results


# ---------------------------------------------------------------------------
# Report printer
# ---------------------------------------------------------------------------

def print_report(
    ingest: list[IngestionResult],
    retrieval_res: RetrievalResult,
    rerank: RerankerResult,
    cache: CacheResult,
    scale: list[ScaleResult],
) -> None:
    W = 62
    print("\n" + "━" * W)
    print(f"  DocChat Benchmark  —  {date.today()}")
    print("━" * W)

    # --- Ingestion ---
    print("\n  INGESTION SPEED")
    print(f"  {'Size':<10} {'Chunks':>8} {'Time':>10} {'Ch/s':>8} {'Peak Mem':>10}  Status")
    print(f"  {_hr(58)}")
    for r in ingest:
        status = "✓" if r.status == "ok" else "✗"
        print(
            f"  {r.label:<10} {r.chunks:>8} {r.elapsed_s:>9.1f}s "
            f"{r.chunks_per_sec:>8.1f} {r.peak_mem_mb:>8.1f} MB  {status} {r.status if r.status != 'ok' else ''}"
        )

    # --- Retrieval ---
    print(f"\n  RETRIEVAL LATENCY  (n={retrieval_res.n_queries}, warm cache)")
    print(f"  Cold cache (LRU build):  {_fmt_ms(retrieval_res.cold_ms)}")
    print(f"  Warm cache  p50={_fmt_ms(retrieval_res.p50)}  "
          f"p95={_fmt_ms(retrieval_res.p95)}  "
          f"p99={_fmt_ms(retrieval_res.p99)}  "
          f"mean={_fmt_ms(retrieval_res.mean)}")

    # --- Reranking ---
    print(f"\n  RERANKING PRECISION  (n={rerank.n_queries} ground-truth queries)")
    print(f"  {'Metric':<28} {'RRF-only':>10} {'+ FlashRank':>12}  {'Δ':>6}")
    print(f"  {_hr(58)}")

    rows = [
        ("MRR",                 rerank.rrf_mrr,         rerank.rerank_mrr,         ".2f"),
        ("Hit@1",               rerank.rrf_hit1,        rerank.rerank_hit1,        ".0%"),
        ("Hit@3",               rerank.rrf_hit3,        rerank.rerank_hit3,        ".0%"),
        ("Avg cross-enc score", rerank.rrf_avg_score,   rerank.rerank_avg_score,   ".3f"),
    ]
    for label, rrf_v, rr_v, fmt in rows:
        delta = rr_v - rrf_v
        sign = "+" if delta >= 0 else ""
        rrf_s = format(rrf_v, fmt)
        rr_s  = format(rr_v,  fmt)
        d_s   = f"{sign}{format(delta, fmt)}"
        print(f"  {label:<28} {rrf_s:>10} {rr_s:>12}  {d_s:>6}")
    print(f"  {'Reorder rate (top-1 changed)':<28} {'—':>10} {rerank.reorder_rate:>11.0%}  {'':>6}")

    # --- Cache ---
    print(f"\n  SEMANTIC CACHE")
    if not cache.available:
        print("  Not available — set REDIS_URL in .env")
    else:
        print(f"  Paraphrase queries:  {cache.n_paraphrase_queries}")
        print(f"  Cache hits:          {cache.hits} / {cache.n_paraphrase_queries}  ({cache.hit_rate:.0%})")
        print(f"  Avg latency uncached: {_fmt_ms(cache.uncached_ms)}")
        print(f"  Avg latency cached:   {_fmt_ms(cache.cached_ms)}")
        print(f"  Speedup:              {cache.speedup:.0f}×")

    # --- Scale ---
    if scale:
        print(f"\n  DOCUMENT SCALE")
        print(f"  {'Size':<10} {'Pages':>6} {'Chunks':>8} {'Ingest':>10} {'Retrieval':>11}  Status")
        print(f"  {_hr(58)}")
        for r in scale:
            status = "✓" if r.status == "ok" else "✗"
            print(
                f"  {r.label:<10} {r.pages:>6} {r.chunks:>8} "
                f"{_fmt_ms(r.ingest_s*1000):>10} "
                f"{_fmt_ms(r.warm_retrieval_ms):>11}  "
                f"{status} {r.status if r.status != 'ok' else ''}"
            )

    print("\n" + "━" * W)


# ---------------------------------------------------------------------------
# Serialisation (for JSON output)
# ---------------------------------------------------------------------------

def _to_json(ingest, retrieval_res, rerank, cache, scale) -> dict:
    return {
        "date": str(date.today()),
        "ingestion": [asdict(r) for r in ingest],
        "retrieval": {
            "n_queries": retrieval_res.n_queries,
            "cold_ms": retrieval_res.cold_ms,
            "p50_ms": retrieval_res.p50,
            "p95_ms": retrieval_res.p95,
            "p99_ms": retrieval_res.p99,
            "mean_ms": retrieval_res.mean,
        },
        "reranking": asdict(rerank),
        "semantic_cache": asdict(cache),
        "scale": [asdict(r) for r in scale],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main(args: argparse.Namespace) -> None:
    print("DocChat Benchmark Suite")
    print(f"DB: {settings.database_url}")
    print(f"Embedding model: {settings.embedding_model}")

    print("\nSetting up benchmark database…")
    await setup_db()

    # Warm up embedder (model download + ONNX load — not counted in measurements)
    print("Warming up embedder (may download model on first run)…")
    emb = get_embedder()
    if emb is None:
        print("  WARNING: embedder unavailable — semantic benchmarks will be skipped")

    ingest_sizes_kb = [10, 100, 500, 1024]          # quick sizes for ingestion bench
    scale_sizes_kb  = [100, 500, 1024, 5 * 1024]    # scale bench (up to 5 MB by default)

    if args.skip_scale:
        scale_sizes_kb = []

    # Run benchmarks
    ingest_results  = await run_ingestion_benchmark(ingest_sizes_kb)
    retrieval_result = await run_retrieval_benchmark(args.queries)
    rerank_result   = await run_rerank_benchmark()
    cache_result    = await run_cache_benchmark()
    scale_results   = await run_scale_benchmark(scale_sizes_kb) if scale_sizes_kb else []

    # If user provided a real PDF, run it through ingestion too
    if args.pdf:
        pdf_path = Path(args.pdf)
        if pdf_path.exists():
            print(f"\n▸  USER PDF  ({pdf_path.name})")
            actual = pdf_path.stat().st_size
            doc = Document(
                id=str(uuid.uuid4()),
                filename=pdf_path.name,
                file_path=str(pdf_path),
                content_type="application/pdf",
                status=DocumentStatus.pending,
            )
            async with AsyncSessionLocal() as db:
                db.add(doc)
                await db.commit()
                tracemalloc.start()
                t0 = time.perf_counter()
                try:
                    await ingest_document(doc, db)
                    elapsed = time.perf_counter() - t0
                    _, peak = tracemalloc.get_traced_memory()
                    tracemalloc.stop()
                    print(
                        f"   {_fmt_bytes(actual)} → {doc.chunk_count} chunks "
                        f"in {elapsed:.1f}s  ({doc.chunk_count/elapsed:.1f} ch/s)  "
                        f"peak {peak/1024**2:.0f} MB"
                    )
                except Exception as exc:
                    tracemalloc.stop()
                    print(f"   FAILED — {exc}")

    print_report(ingest_results, retrieval_result, rerank_result, cache_result, scale_results)

    # Save JSON
    out_path = ROOT / f"benchmark_results_{date.today()}.json"
    payload = _to_json(ingest_results, retrieval_result, rerank_result, cache_result, scale_results)
    out_path.write_text(json.dumps(payload, indent=2, default=_json_default))
    print(f"  Results saved to: {out_path.name}")

    print("\nCleaning up benchmark database…")
    await teardown_db()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DocChat benchmark suite")
    parser.add_argument("--skip-scale", action="store_true",
                        help="Skip the slow document scale benchmark")
    parser.add_argument("--pdf", metavar="PATH",
                        help="Also ingest a real PDF and report timing")
    parser.add_argument("--queries", type=int, default=30,
                        help="Number of retrieval queries to sample (default: 30)")
    args = parser.parse_args()

    asyncio.run(main(args))
