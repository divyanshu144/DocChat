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
