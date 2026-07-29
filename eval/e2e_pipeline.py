from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
from contextlib import ExitStack
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from unittest.mock import patch

import numpy as np
from langgraph.graph import END, StateGraph


ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = ROOT / "reports"


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct / 100
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


@dataclass(frozen=True)
class PipelineCase:
    label: str
    query: str
    expected_sources: list[Literal["pdf", "youtube", "web"]]
    required_terms: list[list[str]]
    forbidden_terms: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class PipelineCaseResult:
    label: str
    passed: bool
    latency_ms: float
    retrieved_chunks: int
    grounding_passed: bool
    needs_replan: bool
    iteration: int
    missing_terms: list[str]
    forbidden_hits: list[str]
    expected_sources: list[str]
    planned_sources: list[str]
    answer: str


class FakeEmbedder:
    def __init__(self) -> None:
        self.last_query = ""

    def embed_query(self, text: str) -> np.ndarray:
        self.last_query = text
        return np.array([0.1] * 384, dtype="float32")


CHUNKS: dict[str, list[dict]] = {
    "pdf": [
        {
            "score": 0.94,
            "payload": {
                "text": (
                    "DocChat uses the BAAI/bge-small-en-v1.5 embedding model through "
                    "fastembed's ONNX runtime. The embeddings are 384-dimensional "
                    "float32 vectors and run on CPU without a GPU requirement."
                ),
                "filename": "architecture.pdf",
                "page_number": 2,
            },
        },
        {
            "score": 0.91,
            "payload": {
                "text": (
                    "PDF ingestion extracts text with PyMuPDF, also imported as fitz. "
                    "When a scanned page has no embedded text, pytesseract OCR is used "
                    "as a fallback before chunking."
                ),
                "filename": "ingestion.pdf",
                "page_number": 4,
            },
        },
        {
            "score": 0.9,
            "payload": {
                "text": (
                    "DocChat splits PDF text with RecursiveCharacterTextSplitter using "
                    "a chunk size of 1500 characters and an overlap of 200 characters."
                ),
                "filename": "ingestion.pdf",
                "page_number": 5,
            },
        },
        {
            "score": 0.88,
            "payload": {
                "text": (
                    "The LangGraph agent is a five-node pipeline: Planner, Retriever, "
                    "Synthesizer, Grounding, and Critic. The critic can request one "
                    "replan loop when the answer is poor."
                ),
                "filename": "agent.pdf",
                "page_number": 7,
            },
        },
    ],
    "youtube": [
        {
            "score": 0.93,
            "payload": {
                "text": (
                    "YouTube ingestion fetches transcripts with youtube-transcript-api. "
                    "Transcript segments are grouped into chunks of roughly 60 seconds "
                    "before embedding and storage."
                ),
                "title": "DocChat ingestion demo",
                "timestamp_start": 120,
            },
        },
        {
            "score": 0.86,
            "payload": {
                "text": (
                    "In the demo, chat responses are streamed back to the browser using "
                    "Server-Sent Events so users can see words arrive incrementally."
                ),
                "title": "DocChat chat demo",
                "timestamp_start": 240,
            },
        },
    ],
    "web": [
        {
            "score": 0.92,
            "payload": {
                "text": (
                    "Web ingestion sends HTTP requests with httpx and extracts article "
                    "content with trafilatura. The resulting text is chunked, embedded, "
                    "and stored with a URL source marker."
                ),
                "url": "https://docs.example.com/web-ingestion",
            },
        },
        {
            "score": 0.84,
            "payload": {
                "text": (
                    "Conversation folders let users organize chats. A folder can be "
                    "created, renamed, deleted, and used to group existing conversations."
                ),
                "url": "https://docs.example.com/folders",
            },
        },
    ],
}


BASE_CASES: list[PipelineCase] = [
    PipelineCase(
        label="embedding_model_and_dimension",
        query="What embedding model does DocChat use and what is the vector dimension?",
        expected_sources=["pdf"],
        required_terms=[["bge-small-en-v1.5", "baai/bge-small-en-v1.5"], ["384"]],
        forbidden_terms=["768", "openai", "gpu required"],
        reason="Single-source factual lookup from PDF context.",
    ),
    PipelineCase(
        label="pdf_ocr_fallback",
        query="How does DocChat handle scanned PDF pages with no embedded text?",
        expected_sources=["pdf"],
        required_terms=[["pytesseract", "ocr"], ["fallback"], ["scanned"]],
        forbidden_terms=["youtube", "trafilatura"],
        reason="Checks PDF-specific ingestion details.",
    ),
    PipelineCase(
        label="pdf_chunking_parameters",
        query="What chunk size and overlap does PDF ingestion use?",
        expected_sources=["pdf"],
        required_terms=[["1500"], ["200"]],
        forbidden_terms=["60 seconds"],
        reason="Requires numeric PDF chunking details.",
    ),
    PipelineCase(
        label="youtube_transcript_library",
        query="Which library fetches YouTube transcripts and how are transcript chunks grouped?",
        expected_sources=["youtube"],
        required_terms=[["youtube-transcript-api"], ["60 seconds", "60-second", "roughly 60"]],
        forbidden_terms=["pymupdf", "trafilatura"],
        reason="Checks YouTube-specific retrieval and synthesis.",
    ),
    PipelineCase(
        label="web_ingestion_libraries",
        query="Which libraries does web ingestion use for HTTP requests and content extraction?",
        expected_sources=["web"],
        required_terms=[["httpx"], ["trafilatura"]],
        forbidden_terms=["pytesseract", "youtube-transcript-api"],
        reason="Checks web-specific source selection.",
    ),
    PipelineCase(
        label="agent_nodes",
        query="What are the five nodes in the LangGraph agent pipeline?",
        expected_sources=["pdf"],
        required_terms=[["planner"], ["retriever"], ["synthesizer"], ["grounding"], ["critic"]],
        forbidden_terms=["router", "validator", "nine nodes"],
        reason="Checks complete multi-item answer.",
    ),
    PipelineCase(
        label="chat_streaming_transport",
        query="How are chat responses streamed back to the browser?",
        expected_sources=["youtube"],
        required_terms=[["server-sent events", "sse"], ["incrementally", "words arrive", "streamed"]],
        forbidden_terms=["websocket", "complete json only"],
        reason="Checks streaming transport answer.",
    ),
    PipelineCase(
        label="conversation_folders",
        query="What can users do with conversation folders?",
        expected_sources=["web"],
        required_terms=[["create"], ["rename"], ["delete"], ["group", "organize"]],
        forbidden_terms=["pdf", "ocr"],
        reason="Checks product workflow answer from web context.",
    ),
    PipelineCase(
        label="multi_source_ingestion_libraries",
        query="Compare the libraries used for PDF, YouTube, and web ingestion.",
        expected_sources=["pdf", "youtube", "web"],
        required_terms=[["pymupdf", "fitz"], ["pytesseract"], ["youtube-transcript-api"], ["httpx"], ["trafilatura"]],
        forbidden_terms=["selenium", "beautifulsoup"],
        reason="Requires combining all three source types.",
    ),
    PipelineCase(
        label="unknown_information",
        query="What database migration tool does DocChat use?",
        expected_sources=[],
        required_terms=[["does not contain", "not provided", "not enough information", "cannot determine"]],
        forbidden_terms=["alembic", "flyway", "liquibase"],
        reason="Checks refusal to fabricate when context lacks the answer.",
    ),
]


QUERY_VARIANTS: dict[str, list[str]] = {
    "embedding_model_and_dimension": [
        "What embedding model does DocChat use and what is the vector dimension?",
        "Name DocChat's embedding model and its vector size.",
        "Which embedding model powers DocChat, and how many dimensions are its vectors?",
        "What model creates embeddings in DocChat, and what dimensionality does it output?",
        "Tell me the embedding model and vector dimension used by DocChat.",
    ],
    "pdf_ocr_fallback": [
        "How does DocChat handle scanned PDF pages with no embedded text?",
        "What fallback does PDF ingestion use for scanned pages?",
        "If a PDF page has no text layer, what does DocChat do?",
        "How are image-only PDF pages processed during ingestion?",
        "What OCR fallback exists for scanned PDFs in DocChat?",
    ],
    "pdf_chunking_parameters": [
        "What chunk size and overlap does PDF ingestion use?",
        "Give the PDF chunking size and overlap settings.",
        "How large are PDF chunks, and how much overlap is used?",
        "What are the numeric PDF chunking parameters?",
        "Which chunk size and overlap are configured for PDF text?",
    ],
    "youtube_transcript_library": [
        "Which library fetches YouTube transcripts and how are transcript chunks grouped?",
        "How does DocChat retrieve and group YouTube transcript text?",
        "What transcript library is used for YouTube ingestion, and how are segments chunked?",
        "Explain the YouTube transcript fetching library and chunk duration.",
        "For YouTube ingestion, what library is used and how long are transcript chunks?",
    ],
    "web_ingestion_libraries": [
        "Which libraries does web ingestion use for HTTP requests and content extraction?",
        "What tools power web page fetching and article extraction?",
        "Name the HTTP client and content extraction library used for web ingestion.",
        "How does DocChat fetch web pages and extract article text?",
        "Which web ingestion libraries handle requests and readable content extraction?",
    ],
    "agent_nodes": [
        "What are the five nodes in the LangGraph agent pipeline?",
        "List the LangGraph pipeline nodes used by DocChat.",
        "Which five stages make up the DocChat agent graph?",
        "Name each node in the DocChat LangGraph workflow.",
        "What is the planner-to-critic node sequence in DocChat?",
    ],
    "chat_streaming_transport": [
        "How are chat responses streamed back to the browser?",
        "What transport streams generated answers to the frontend?",
        "How does DocChat deliver incremental chat output to users?",
        "What browser streaming mechanism does DocChat use for chat responses?",
        "How do generated answer tokens reach the browser incrementally?",
    ],
    "conversation_folders": [
        "What can users do with conversation folders?",
        "Which actions are supported for organizing chats into folders?",
        "How do conversation folders help users manage chats?",
        "What folder operations are available for conversations?",
        "Describe the supported conversation folder workflow.",
    ],
    "multi_source_ingestion_libraries": [
        "Compare the libraries used for PDF, YouTube, and web ingestion.",
        "Which ingestion libraries are used across PDFs, YouTube videos, and web pages?",
        "Summarize DocChat's source-specific ingestion stack.",
        "What libraries handle each of the three ingestion source types?",
        "Map PDF, YouTube, and web ingestion to their implementation libraries.",
    ],
    "unknown_information": [
        "What database migration tool does DocChat use?",
        "Which schema migration framework is used in DocChat?",
        "Does the context say whether DocChat uses Alembic?",
        "What tool manages database migrations for this app?",
        "Identify the migration system used by DocChat.",
    ],
}


def _expanded_cases() -> list[PipelineCase]:
    cases: list[PipelineCase] = []
    by_label = {case.label: case for case in BASE_CASES}
    for label, queries in QUERY_VARIANTS.items():
        base = by_label[label]
        for index, query in enumerate(queries, start=1):
            cases.append(PipelineCase(
                label=f"{label}_{index}",
                query=query,
                expected_sources=base.expected_sources,
                required_terms=base.required_terms,
                forbidden_terms=base.forbidden_terms,
                reason=base.reason,
            ))
    return cases


CASES: list[PipelineCase] = _expanded_cases()


def _collection_to_source(collection_name: str) -> str:
    return collection_name.removesuffix("_chunks")


def _score(case: PipelineCase, state: dict, latency_ms: float) -> PipelineCaseResult:
    answer = state.get("answer", "")
    answer_l = answer.lower()
    missing: list[str] = []
    for group in case.required_terms:
        if not any(term.lower() in answer_l for term in group):
            missing.append(" | ".join(group))

    forbidden_hits = [term for term in case.forbidden_terms if term.lower() in answer_l]
    retrieved = state.get("retrieved_chunks", [])
    planned_sources = state.get("sources_to_use", [])
    source_ok = all(
        any(chunk.get("source_type") == source for chunk in retrieved)
        for source in case.expected_sources
    )
    if not source_ok:
        missing.append(f"retrieved source(s): {', '.join(case.expected_sources)}")

    passed = not missing and not forbidden_hits
    return PipelineCaseResult(
        label=case.label,
        passed=passed,
        latency_ms=round(latency_ms, 2),
        retrieved_chunks=len(retrieved),
        grounding_passed=bool(state.get("grounding_passed")),
        needs_replan=bool(state.get("needs_replan")),
        iteration=int(state.get("iteration", 0)),
        missing_terms=missing,
        forbidden_hits=forbidden_hits,
        expected_sources=case.expected_sources,
        planned_sources=planned_sources,
        answer=answer,
    )


def _build_eval_graph(allow_retry: bool):
    from app.agent.state import AgentState
    from app.agent.nodes.planner import planner_node
    from app.agent.nodes.retriever import retriever_node
    from app.agent.nodes.synthesizer import synthesizer_node
    from app.agent.nodes.grounding import grounding_node
    from app.agent.nodes.critic import critic_node

    graph = StateGraph(AgentState)
    graph.add_node("planner", planner_node)
    graph.add_node("retriever", retriever_node)
    graph.add_node("synthesizer", synthesizer_node)
    graph.add_node("grounding", grounding_node)
    graph.add_node("critic", critic_node)
    graph.set_entry_point("planner")
    graph.add_edge("planner", "retriever")
    graph.add_edge("retriever", "synthesizer")
    graph.add_edge("synthesizer", "grounding")
    graph.add_edge("grounding", "critic")
    if allow_retry:
        def route(state: dict) -> str:
            if state.get("needs_replan") and state.get("iteration", 0) < 2:
                return "planner"
            return END

        graph.add_conditional_edges("critic", route, {"planner": "planner", END: END})
    else:
        graph.add_edge("critic", END)
    return graph.compile()


async def _run_case_manual(case: PipelineCase, *, allow_retry: bool) -> tuple[PipelineCaseResult, PipelineCaseResult]:
    from app.agent.nodes.planner import planner_node
    from app.agent.nodes.retriever import retriever_node
    from app.agent.nodes.synthesizer import synthesizer_node
    from app.agent.nodes.grounding import grounding_node
    from app.agent.nodes.critic import critic_node

    state = {
        "query": case.query,
        "conversation_id": f"eval-{case.label}",
        "sources_to_use": ["pdf", "youtube", "web"],
        "source_ids": [],
        "retrieved_chunks": [],
        "answer": "",
        "critic_feedback": "",
        "needs_replan": False,
        "iteration": 0,
        "grounding_passed": False,
    }

    started = time.perf_counter()
    for node in (planner_node, retriever_node, synthesizer_node, grounding_node, critic_node):
        state.update(await node(state))
    first_latency_ms = (time.perf_counter() - started) * 1000
    baseline = _score(case, state, first_latency_ms)

    if allow_retry and state.get("needs_replan") and state.get("iteration", 0) < 2:
        retry_started = time.perf_counter()
        for node in (planner_node, retriever_node, synthesizer_node, grounding_node, critic_node):
            state.update(await node(state))
        final_latency_ms = first_latency_ms + ((time.perf_counter() - retry_started) * 1000)
    else:
        final_latency_ms = first_latency_ms

    optimized = _score(case, state, final_latency_ms)
    return baseline, optimized


async def run_eval(*, allow_retry: bool = True, limit: int | None = None) -> list[PipelineCaseResult]:
    agent_graph = _build_eval_graph(allow_retry)

    fake_embedder = FakeEmbedder()

    async def fake_search(collection_name: str, query_vector: list, limit: int, qdrant_filter=None) -> list:
        source = _collection_to_source(collection_name)
        query = fake_embedder.last_query.lower()
        rows = CHUNKS.get(source, [])

        if "database migration" in query:
            return []
        if "compare" in query or ("pdf" in query and "youtube" in query and "web" in query):
            return rows[:limit]
        if "youtube" in query or "transcript" in query or "streamed" in query or "browser" in query:
            return rows[:limit] if source == "youtube" else []
        if "web" in query or "http" in query or "content extraction" in query or "folders" in query:
            return rows[:limit] if source == "web" else []
        return rows[:limit] if source == "pdf" else []

    results: list[PipelineCaseResult] = []
    with ExitStack() as stack:
        stack.enter_context(patch("app.agent.nodes.retriever.get_embedder", return_value=fake_embedder))
        stack.enter_context(patch("app.agent.nodes.retriever._search", new=fake_search))
        selected_cases = CASES[:limit] if limit else CASES
        total = len(selected_cases)
        for index, case in enumerate(selected_cases, start=1):
            print(f"[EVAL {'optimized' if allow_retry else 'baseline'}] {index}/{total} {case.label}", flush=True)
            state = {
                "query": case.query,
                "conversation_id": f"eval-{case.label}",
                "sources_to_use": ["pdf", "youtube", "web"],
                "source_ids": [],
                "retrieved_chunks": [],
                "answer": "",
                "critic_feedback": "",
                "needs_replan": False,
                "iteration": 0,
                "grounding_passed": False,
            }
            started = time.perf_counter()
            final_state = await agent_graph.ainvoke(state)
            latency_ms = (time.perf_counter() - started) * 1000
            results.append(_score(case, final_state, latency_ms))
    return results


async def run_compare(limit: int | None = None) -> tuple[list[PipelineCaseResult], list[PipelineCaseResult]]:
    fake_embedder = FakeEmbedder()

    async def fake_search(collection_name: str, query_vector: list, limit: int, qdrant_filter=None) -> list:
        source = _collection_to_source(collection_name)
        query = fake_embedder.last_query.lower()
        rows = CHUNKS.get(source, [])

        if "database migration" in query or "migration framework" in query or "alembic" in query:
            return []
        if "compare" in query or ("pdf" in query and "youtube" in query and "web" in query):
            return rows[:limit]
        if "youtube" in query or "transcript" in query or "streamed" in query or "browser" in query or "frontend" in query or "tokens" in query:
            return rows[:limit] if source == "youtube" else []
        if "web" in query or "http" in query or "content extraction" in query or "article" in query or "folders" in query or "folder" in query or "chats" in query:
            return rows[:limit] if source == "web" else []
        return rows[:limit] if source == "pdf" else []

    import app.services.llm as llm_service

    output_cap = int(os.getenv("E2E_EVAL_MAX_TOKENS", "220"))

    async def capped_chat_complete(messages: list[dict], max_tokens: int = 1024) -> str:
        return await llm_service.chat_complete(messages, max_tokens=min(max_tokens, output_cap))

    baseline: list[PipelineCaseResult] = []
    optimized: list[PipelineCaseResult] = []
    selected_cases = CASES[:limit] if limit else CASES
    total = len(selected_cases)
    with ExitStack() as stack:
        stack.enter_context(patch("app.agent.nodes.retriever.get_embedder", return_value=fake_embedder))
        stack.enter_context(patch("app.agent.nodes.retriever._search", new=fake_search))
        stack.enter_context(patch("app.agent.nodes.planner.chat_complete", new=capped_chat_complete))
        stack.enter_context(patch("app.agent.nodes.synthesizer.chat_complete", new=capped_chat_complete))
        stack.enter_context(patch("app.agent.nodes.grounding.chat_complete", new=capped_chat_complete))
        stack.enter_context(patch("app.agent.nodes.critic.chat_complete", new=capped_chat_complete))
        for index, case in enumerate(selected_cases, start=1):
            print(f"[EVAL compare] {index}/{total} {case.label}", flush=True)
            base_result, opt_result = await _run_case_manual(case, allow_retry=True)
            baseline.append(base_result)
            optimized.append(opt_result)
    return baseline, optimized


def _print_report(results: list[PipelineCaseResult]) -> None:
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    latencies = [r.latency_ms for r in results]
    print("\nFormal E2E Pipeline Eval")
    print(f"Cases: {passed}/{total} passed ({passed / total:.1%})")
    print(f"Latency: mean={statistics.mean(latencies):.0f}ms p50={statistics.median(latencies):.0f}ms p95={_percentile(latencies, 95):.0f}ms")
    print("\ncase                              status  latency  chunks  replans")
    print("-" * 76)
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        print(f"{r.label:<34} {status:<6} {r.latency_ms:>7.0f}ms {r.retrieved_chunks:>6} {r.iteration:>7}")
        if not r.passed:
            if r.missing_terms:
                print(f"  missing: {', '.join(r.missing_terms)}")
            if r.forbidden_hits:
                print(f"  forbidden: {', '.join(r.forbidden_hits)}")


def _summary(results: list[PipelineCaseResult]) -> dict:
    latencies = [r.latency_ms for r in results]
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    return {
        "cases": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": passed / total if total else 0.0,
        "mean_latency_ms": statistics.mean(latencies) if latencies else 0.0,
        "p50_latency_ms": statistics.median(latencies) if latencies else 0.0,
        "p95_latency_ms": _percentile(latencies, 95),
    }


async def async_main() -> int:
    parser = argparse.ArgumentParser(description="Run formal DocChat end-to-end pipeline eval.")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=None, help="Run only the first N cases.")
    parser.add_argument("--compare", action="store_true", help="Run baseline without retry and optimized with retry.")
    args = parser.parse_args()

    if args.compare:
        baseline, optimized = await run_compare(limit=args.limit)
        baseline_summary = _summary(baseline)
        optimized_summary = _summary(optimized)
        baseline_rate = baseline_summary["pass_rate"]
        optimized_rate = optimized_summary["pass_rate"]
        absolute_lift = optimized_rate - baseline_rate
        relative_lift = (absolute_lift / baseline_rate) if baseline_rate else 0.0
        results = optimized
        print("\nBaseline vs Optimized")
        print(f"Baseline:  {baseline_summary['passed']}/{baseline_summary['cases']} ({baseline_rate:.1%})")
        print(f"Optimized: {optimized_summary['passed']}/{optimized_summary['cases']} ({optimized_rate:.1%})")
        print(f"Lift:      +{absolute_lift:.1%} absolute, +{relative_lift:.1%} relative")
    else:
        baseline = []
        baseline_summary = None
        optimized = await run_eval(allow_retry=True, limit=args.limit)
        optimized_summary = _summary(optimized)
        absolute_lift = None
        relative_lift = None
        results = optimized

    _print_report(results)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "description": (
            "Formal pipeline eval over the real LangGraph planner, synthesizer, "
            "grounding, and critic nodes with deterministic synthetic retrieval fixtures."
        ),
        "cases": len(results),
        "passed": sum(1 for r in results if r.passed),
        "failed": sum(1 for r in results if not r.passed),
        "comparison": {
            "baseline": baseline_summary,
            "optimized": optimized_summary,
            "absolute_lift": absolute_lift,
            "relative_lift": relative_lift,
        } if args.compare else None,
        "baseline_results": [asdict(r) for r in baseline],
        "results": [asdict(r) for r in results],
    }
    REPORT_DIR.mkdir(exist_ok=True)
    out_path = args.output or REPORT_DIR / f"e2e_pipeline_eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nReport: {out_path}")
    return 0 if payload["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main()))
