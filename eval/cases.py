from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class CriticCase:
    label: str                         # failure-mode slug — used as pytest id and report label
    query: str
    answer: str
    expected: Literal["good", "poor"]  # human-readable; test owns translation to needs_replan bool
    reason: str                        # why this label exists — survives prompt refactors


CASES: list[CriticCase] = [
    CriticCase(
        label="correct_well_grounded",
        query="What embedding model does DocChat use and what is the vector dimension?",
        answer=(
            "DocChat uses the BAAI/bge-small-en-v1.5 model via the fastembed ONNX runtime, "
            "producing 384-dimensional float32 vectors. The model runs entirely on CPU with no "
            "GPU required.\n\nSources:\n- [PDF — architecture.pdf p.2]"
        ),
        expected="good",
        reason="Complete, specific, cited answer with no ambiguity — critic should always approve",
    ),
    CriticCase(
        label="correct_multi_part_answer",
        query="What are the three ingestion sources in DocChat and what library handles each one?",
        answer=(
            "DocChat supports three ingestion sources: "
            "(1) PDFs are extracted using PyMuPDF (fitz) with pytesseract OCR as a fallback for scanned pages; "
            "(2) YouTube videos use youtube-transcript-api to fetch auto-generated or manual subtitles; "
            "(3) web pages are scraped using httpx for HTTP requests and trafilatura for content extraction.\n\n"
            "Sources:\n- [PDF — architecture.pdf p.3]"
        ),
        expected="good",
        reason="All three parts of the query answered with specific library names and a citation — critic should always approve",
    ),
    CriticCase(
        label="vague_no_substance",
        query="How does the retrieval pipeline work?",
        answer=(
            "The retrieval pipeline works by processing information in a systematic and efficient "
            "way to provide relevant and accurate results based on user queries using advanced techniques."
        ),
        expected="poor",
        reason="Pure filler with zero factual content — no mechanism described at all; critic should always flag",
    ),
    CriticCase(
        label="incomplete_two_part_query",
        query="What vector store does DocChat use and why was it chosen over ChromaDB?",
        answer=(
            "DocChat uses Qdrant as its vector store, which provides HNSW indexing for fast "
            "approximate nearest neighbour search via a REST API."
        ),
        expected="poor",
        reason="Addresses only the first part — the ChromaDB comparison is entirely ignored; critic should always flag",
    ),
    CriticCase(
        label="hallucinated_claim",
        query="How many nodes does the LangGraph agent have and what are they called?",
        answer=(
            "The LangGraph agent has 5 nodes: planner, retriever, synthesizer, grounding, and critic. "
            "It also contains 9 nodes in total, including 4 additional internal routing nodes "
            "for error recovery and state validation."
        ),
        expected="poor",
        reason="Answer contradicts itself (claims 5 nodes then 9 nodes) with fabricated details — internally inconsistent; critic should always flag",
    ),
    CriticCase(
        label="off_topic",
        query="How are PDF documents chunked before ingestion?",
        answer=(
            "YouTube videos are ingested by fetching transcripts via youtube-transcript-api. "
            "The transcript is split into overlapping chunks and embedded before storage in Qdrant."
        ),
        expected="poor",
        reason="Answers the YouTube ingestion question instead of PDF chunking — completely off topic; critic should always flag",
    ),
    CriticCase(
        label="fabricated_source",
        query="What does the research paper say about transformer self-attention?",
        answer=(
            "Sources:\n- [PDF — transformer_paper.pdf p.1]\n"
            "- [PDF — transformer_paper.pdf p.4]\n"
            "- [PDF — transformer_paper.pdf p.9]"
        ),
        expected="poor",
        reason="Response contains only citation markers with no actual content — query is entirely unaddressed",
    ),
    CriticCase(
        label="contradicts_context",
        query="Does DocChat support real-time token streaming?",
        answer=(
            "Yes, DocChat fully supports real-time token streaming via Server-Sent Events, "
            "delivering tokens word-by-word as the LLM generates them. "
            "However, DocChat does not support streaming at all — responses are returned as a "
            "complete JSON payload only after the full answer is generated."
        ),
        expected="poor",
        reason="Answer directly contradicts itself on the core question — self-contradictory answers cannot adequately address a query",
    ),
]


# ---------------------------------------------------------------------------
# Layer A — ambiguous edge cases for eval/benchmark.py
#
# Deliberately borderline: these sit near the critic's decision boundary and
# would flap if asserted binomially, so they are NEVER imported by the Layer B
# regression guard. `CASES` and `BENCHMARK_CASES` stay independent.
#
# Skewed 4 good / 1 poor on purpose — the critic's known failure mode is
# over-firing "poor" on hedged or partial answers, so most ambiguous cases land
# in the false-positive region.
# ---------------------------------------------------------------------------

BENCHMARK_CASES: list[CriticCase] = [
    CriticCase(
        label="correct_admits_gaps",
        query="What is the internal training loss curve for BAAI/bge-small-en-v1.5?",
        answer=(
            "The provided context does not contain information about the training loss curve "
            "for BAAI/bge-small-en-v1.5. I cannot answer this question from the available sources."
        ),
        expected="good",
        reason="Appropriate acknowledgement of missing context — borderline because critic reads "
               "'doesn't address query' as poor, but human expert reads it as correct RAG behavior",
    ),
    CriticCase(
        label="hedged_but_correct",
        query="What database does DocChat use to store conversations?",
        answer=(
            "DocChat appears to use PostgreSQL for storing conversations, though this may depend "
            "on the specific deployment configuration. The system likely uses an async SQLAlchemy "
            "connection, but I'm not entirely certain of the exact setup."
        ),
        expected="good",
        reason="Directionally correct (PostgreSQL + SQLAlchemy) but hedged — critic may flag as "
               "vague despite the factual content being present",
    ),
    CriticCase(
        label="partially_addresses_multipart",
        query="What chunking strategy does DocChat use for PDFs and what are the chunk size and overlap?",
        answer=(
            "DocChat uses LangChain's RecursiveCharacterTextSplitter, which splits text recursively "
            "using paragraph breaks, line breaks, and sentence boundaries as separators."
        ),
        expected="poor",
        reason="Correctly describes the strategy but omits the specific numbers explicitly asked "
               "for — borderline because the strategy part IS answered",
    ),
    CriticCase(
        label="correct_but_terse",
        query="What LLM does DocChat use for generating answers?",
        answer="DocChat uses the Groq API with the llama-3.3-70b-versatile model.",
        expected="good",
        reason="One sentence, directly correct — borderline because critic may expect elaboration "
               "or flag brevity as insufficient",
    ),
    CriticCase(
        label="admits_gaps_with_partial_answer",
        query="What are the access token and refresh token expiry times in DocChat?",
        answer=(
            "Access tokens expire after 30 minutes. I don't have information about the refresh "
            "token expiry time in the available context."
        ),
        expected="good",
        reason="First part answered correctly, second part honestly acknowledged as missing — "
               "borderline because the query is only half-answered",
    ),
]
