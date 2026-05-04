import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus
from app.services.storage import delete_file, download_for_processing

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1500     # chars — ~375 tokens, within bge-small's 512-token window
CHUNK_OVERLAP = 200

SUPPORTED_TYPES = {
    "application/pdf",
    "text/plain",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


# ---------------------------------------------------------------------------
# Text segment — carries text plus optional provenance metadata
# ---------------------------------------------------------------------------

@dataclass
class _Segment:
    text: str
    page_number: int | None = None
    section_heading: str | None = None


# ---------------------------------------------------------------------------
# Splitter
# ---------------------------------------------------------------------------

def _get_splitter():
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    return RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", "! ", "? ", "; ", " ", ""],
        length_function=len,
        add_start_index=True,  # enables char-offset tracking for late chunking
    )


# ---------------------------------------------------------------------------
# PDF extraction — pymupdf primary, pypdf fallback, pytesseract OCR for scans
# ---------------------------------------------------------------------------

def _detect_pdf_heading(page) -> str | None:
    """Return the largest-font span on a page if it looks like a heading (>13pt)."""
    try:
        max_size, heading = 0.0, None
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    size = span.get("size", 0.0)
                    txt = span.get("text", "").strip()
                    if size > max_size and 3 < len(txt) < 200:
                        max_size, heading = size, txt
        return heading if max_size > 13 else None
    except Exception:
        return None


def _extract_pdf_segments(path: Path) -> list[_Segment]:
    try:
        import fitz  # pymupdf
        doc = fitz.open(str(path))
        segments: list[_Segment] = []
        for page_num, page in enumerate(doc, start=1):
            text = page.get_text()
            heading = _detect_pdf_heading(page)

            if not text.strip():
                # Scanned page — attempt OCR
                try:
                    import pytesseract
                    from PIL import Image
                    pix = page.get_pixmap(dpi=200)
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    text = pytesseract.image_to_string(img)
                except Exception:
                    pass

            if text.strip():
                segments.append(_Segment(text=text, page_number=page_num, section_heading=heading))
        doc.close()
        return segments
    except ImportError:
        # pymupdf not installed — fall back to pypdf (no per-page heading detection)
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        return [
            _Segment(text=page.extract_text() or "", page_number=i + 1)
            for i, page in enumerate(reader.pages)
            if (page.extract_text() or "").strip()
        ]


# ---------------------------------------------------------------------------
# DOCX extraction — groups paragraphs by Heading style
# ---------------------------------------------------------------------------

def _extract_docx_segments(path: Path) -> list[_Segment]:
    from docx import Document as DocxDocument
    doc = DocxDocument(str(path))

    segments: list[_Segment] = []
    current_heading: str | None = None
    current_paragraphs: list[str] = []

    for para in doc.paragraphs:
        if para.style.name.startswith("Heading"):
            if current_paragraphs:
                segments.append(_Segment(
                    text="\n".join(current_paragraphs),
                    section_heading=current_heading,
                ))
                current_paragraphs = []
            current_heading = para.text or current_heading
        elif para.text.strip():
            current_paragraphs.append(para.text)

    if current_paragraphs:
        segments.append(_Segment(text="\n".join(current_paragraphs), section_heading=current_heading))

    return segments


# ---------------------------------------------------------------------------
# Dispatcher + chunker
# ---------------------------------------------------------------------------

def _extract_segments(file_path: "str | Path", content_type: str) -> list[_Segment]:
    path = Path(file_path)
    if content_type == "text/plain":
        return [_Segment(text=path.read_text(encoding="utf-8", errors="replace"))]
    if content_type == "application/pdf":
        return _extract_pdf_segments(path)
    if content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return _extract_docx_segments(path)
    raise ValueError(f"Unsupported content type: {content_type}")


def _chunk_segments(segments: list[_Segment]) -> list[dict]:
    """Sentence-aware split of each segment; metadata + char offsets are carried forward.

    Each returned dict includes:
      - text, page_number, section_heading  (as before)
      - seg_idx    — index into the segments list (for late chunking)
      - char_start — character offset of this chunk within its segment's text
    """
    splitter = _get_splitter()
    chunks: list[dict] = []
    for seg_idx, seg in enumerate(segments):
        for doc in splitter.create_documents([seg.text]):
            if doc.page_content.strip():
                chunks.append({
                    "text": doc.page_content,
                    "page_number": seg.page_number,
                    "section_heading": seg.section_heading,
                    "seg_idx": seg_idx,
                    "char_start": doc.metadata.get("start_index", 0),
                })
    return chunks


def _embed_chunks_late(
    raw_chunks: list[dict],
    segments: list[_Segment],
    embedder: "LateChunkingEmbedder",
) -> list["np.ndarray | None"]:
    """Group chunks by their source segment and embed each group with late chunking.

    Chunks whose segment fits within 512 tokens get contextual embeddings where
    each chunk's embedding reflects the full page context.  Chunks on longer
    segments fall back to independent embedding automatically.
    """
    from app.services.embedder import LateChunkingEmbedder  # type hint only

    results: list = [None] * len(raw_chunks)
    i = 0
    while i < len(raw_chunks):
        seg_idx = raw_chunks[i].get("seg_idx")

        # Find the contiguous run of chunks belonging to this segment
        j = i
        while j < len(raw_chunks) and raw_chunks[j].get("seg_idx") == seg_idx:
            j += 1

        group = raw_chunks[i:j]
        chunk_texts = [c["text"] for c in group]
        char_starts = [c.get("char_start", 0) for c in group]

        if seg_idx is not None and seg_idx < len(segments):
            embs = embedder.embed_late(segments[seg_idx].text, chunk_texts, char_starts)
        else:
            embs = embedder.embed_independently(chunk_texts)

        for k, emb in enumerate(embs):
            results[i + k] = emb
        i = j

    return results


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def ingest_document(document: Document, db: AsyncSession) -> None:
    """Extract → chunk → late-chunk embed → persist; delete raw file on completion."""
    from app.core.metrics import ingestion_chunks, ingestion_duration
    from app.services.embedder import get_embedder
    from app.services.retrieval import invalidate_bm25

    document.status = DocumentStatus.processing
    await db.commit()

    t_start = time.perf_counter()

    try:
        loop = asyncio.get_running_loop()

        # Download from S3 (or yield local path directly) for extraction
        async with download_for_processing(document.file_path) as path:
            # CPU/IO-bound extraction runs off the event loop
            segments = await loop.run_in_executor(
                None, _extract_segments, path, document.content_type
            )

        # CPU-bound chunking also runs off the event loop to avoid blocking
        # in-flight requests (200-page PDF can take 200–600ms on the event loop)
        raw_chunks = await loop.run_in_executor(None, _chunk_segments, segments)

        # Late-chunking embed: each chunk gets contextual embeddings from its page.
        # Falls back to independent embedding for pages > 512 tokens.
        embedder = get_embedder()
        if embedder is not None:
            embeddings = await loop.run_in_executor(
                None, _embed_chunks_late, raw_chunks, segments, embedder
            )
        else:
            embeddings = [None] * len(raw_chunks)

        chunks = [
            Chunk(
                document_id=document.id,
                chunk_index=i,
                text=c["text"],
                page_number=c["page_number"],
                section_heading=c["section_heading"],
                # float16 halves storage vs float32 with negligible cosine-sim quality loss
                embedding=(
                    np.array(emb, dtype=np.float16).tobytes() if emb is not None else None
                ),
            )
            for i, (c, emb) in enumerate(zip(raw_chunks, embeddings))
        ]

        db.add_all(chunks)
        document.chunk_count = len(chunks)
        document.status = DocumentStatus.ready
        await db.commit()

        delete_file(document.file_path)
        invalidate_bm25(document.id)
        ingestion_chunks.inc(len(chunks))
        ingestion_duration.observe(time.perf_counter() - t_start)

        logger.info("ingestion_complete", extra={"document_id": document.id, "chunks": len(chunks)})

    except Exception as exc:
        document.status = DocumentStatus.error
        document.error_message = str(exc)
        await db.commit()
        delete_file(document.file_path)
        logger.exception("ingestion_failed", extra={"document_id": document.id})
        raise
