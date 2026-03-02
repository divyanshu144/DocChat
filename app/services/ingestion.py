import asyncio
import logging
from pathlib import Path

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus
from app.services.storage import delete_file

logger = logging.getLogger(__name__)

CHUNK_SIZE = 500      # characters
CHUNK_OVERLAP = 50    # characters

assert CHUNK_OVERLAP < CHUNK_SIZE, "CHUNK_OVERLAP must be less than CHUNK_SIZE"

SUPPORTED_TYPES = {
    "application/pdf",
    "text/plain",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _extract_text(file_path: str, content_type: str) -> str:
    """Extract plain text from a file based on its content type."""
    path = Path(file_path)

    if content_type == "text/plain":
        return path.read_text(encoding="utf-8", errors="replace")

    if content_type == "application/pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    if content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        from docx import Document as DocxDocument
        doc = DocxDocument(str(path))
        return "\n".join(p.text for p in doc.paragraphs)

    raise ValueError(f"Unsupported content type: {content_type}")


def _chunk_text(text: str) -> list[str]:
    """Split text into overlapping fixed-size chunks."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunks.append(text[start:end])
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return [c for c in chunks if c.strip()]


async def ingest_document(document: Document, db: AsyncSession) -> None:
    """Extract text from a document, chunk it, embed chunks, and persist to DB."""
    from app.services.retrieval import _get_embedder, invalidate_bm25

    document.status = DocumentStatus.processing
    await db.commit()

    try:
        text = _extract_text(document.file_path, document.content_type)
        raw_chunks = _chunk_text(text)

        # Embed all chunks in a thread pool to avoid blocking the event loop
        embedder = _get_embedder()
        loop = asyncio.get_running_loop()
        if embedder is not None:
            embeddings = await loop.run_in_executor(
                None, lambda: list(embedder.embed(raw_chunks))
            )
        else:
            embeddings = [None] * len(raw_chunks)

        chunks = [
            Chunk(
                document_id=document.id,
                chunk_index=i,
                text=chunk_text,
                embedding=(
                    np.array(emb, dtype=np.float32).tobytes()
                    if emb is not None else None
                ),
            )
            for i, (chunk_text, emb) in enumerate(zip(raw_chunks, embeddings))
        ]

        db.add_all(chunks)
        document.chunk_count = len(chunks)
        document.status = DocumentStatus.ready
        await db.commit()

        # Remove raw upload after successful ingestion
        delete_file(document.file_path)
        # Invalidate any stale BM25 index for this document
        invalidate_bm25(document.id)

        logger.info("ingestion_complete", extra={"document_id": document.id, "chunks": len(chunks)})

    except Exception as exc:
        document.status = DocumentStatus.error
        document.error_message = str(exc)
        await db.commit()
        delete_file(document.file_path)
        logger.exception("ingestion_failed", extra={"document_id": document.id})
        raise
