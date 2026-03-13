import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus
from app.services.storage import delete_file

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

def _extract_segments(file_path: str, content_type: str) -> list[_Segment]:
    path = Path(file_path)
    if content_type == "text/plain":
        return [_Segment(text=path.read_text(encoding="utf-8", errors="replace"))]
    if content_type == "application/pdf":
        return _extract_pdf_segments(path)
    if content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return _extract_docx_segments(path)
    raise ValueError(f"Unsupported content type: {content_type}")


def _chunk_segments(segments: list[_Segment]) -> list[dict]:
    """Sentence-aware split of each segment; metadata is carried forward."""
    splitter = _get_splitter()
    chunks: list[dict] = []
    for seg in segments:
        for chunk_text in splitter.split_text(seg.text):
            if chunk_text.strip():
                chunks.append({
                    "text": chunk_text,
                    "page_number": seg.page_number,
                    "section_heading": seg.section_heading,
                })
    return chunks


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def ingest_document(document: Document, db: AsyncSession) -> None:
    """Extract → chunk → embed → persist; delete raw file on completion."""
    from app.core.metrics import ingestion_chunks, ingestion_duration
    from app.services.retrieval import _get_embedder, invalidate_bm25

    document.status = DocumentStatus.processing
    await db.commit()

    t_start = time.perf_counter()

    try:
        loop = asyncio.get_running_loop()

        # CPU/IO-bound extraction runs off the event loop
        segments = await loop.run_in_executor(
            None, _extract_segments, document.file_path, document.content_type
        )
        raw_chunks = _chunk_segments(segments)
        chunk_texts = [c["text"] for c in raw_chunks]

        # Embed in thread pool to avoid blocking
        embedder = _get_embedder()
        if embedder is not None:
            embeddings = await loop.run_in_executor(
                None, lambda: list(embedder.embed(chunk_texts))
            )
        else:
            embeddings = [None] * len(chunk_texts)

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
