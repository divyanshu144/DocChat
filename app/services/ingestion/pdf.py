import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.core.chroma import get_collection
from app.services.embedder import get_embedder

COLLECTION = "pdf_chunks"
CHUNK_SIZE = 1500
CHUNK_OVERLAP = 200

SUPPORTED_TYPES = {
    "application/pdf",
    "text/plain",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@dataclass
class _Segment:
    text: str
    page_number: int | None = None
    section_heading: str | None = None


def _detect_pdf_heading(page) -> str | None:
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
        import fitz
        doc = fitz.open(str(path))
        segments: list[_Segment] = []
        for page_num, page in enumerate(doc, start=1):
            text = page.get_text()
            heading = _detect_pdf_heading(page)
            if not text.strip():
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
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        return [
            _Segment(text=page.extract_text() or "", page_number=i + 1)
            for i, page in enumerate(reader.pages)
            if (page.extract_text() or "").strip()
        ]


def _extract_docx_segments(path: Path) -> list[_Segment]:
    from docx import Document as DocxDocument
    doc = DocxDocument(str(path))
    segments: list[_Segment] = []
    current_heading: str | None = None
    current_paragraphs: list[str] = []
    for para in doc.paragraphs:
        if para.style.name.startswith("Heading"):
            if current_paragraphs:
                segments.append(_Segment(text="\n".join(current_paragraphs), section_heading=current_heading))
                current_paragraphs = []
            current_heading = para.text or current_heading
        elif para.text.strip():
            current_paragraphs.append(para.text)
    if current_paragraphs:
        segments.append(_Segment(text="\n".join(current_paragraphs), section_heading=current_heading))
    return segments


def _extract_segments(file_path: "str | Path", content_type: str) -> list[_Segment]:
    path = Path(file_path)
    if content_type == "text/plain":
        return [_Segment(text=path.read_text(encoding="utf-8", errors="replace"))]
    if content_type == "application/pdf":
        return _extract_pdf_segments(path)
    if content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return _extract_docx_segments(path)
    raise ValueError(f"Unsupported content type: {content_type}")


def _get_splitter():
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    return RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", "! ", "? ", "; ", " ", ""],
        length_function=len,
        add_start_index=True,
    )


def _chunk_segments(segments: list[_Segment]) -> list[dict]:
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


def _embed_chunks_late(raw_chunks: list[dict], segments: list[_Segment], embedder) -> list:
    results: list = [None] * len(raw_chunks)
    i = 0
    while i < len(raw_chunks):
        seg_idx = raw_chunks[i].get("seg_idx")
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


async def ingest_pdf(file_path: "str | Path", filename: str, content_type: str) -> str:
    """Extract, chunk, embed and store document in ChromaDB. Returns source_id."""
    source_id = str(uuid.uuid4())
    loop = asyncio.get_running_loop()

    segments = await loop.run_in_executor(None, _extract_segments, file_path, content_type)
    raw_chunks = await loop.run_in_executor(None, _chunk_segments, segments)

    embedder = get_embedder()
    if embedder:
        embeddings = await loop.run_in_executor(
            None, _embed_chunks_late, raw_chunks, segments, embedder
        )
    else:
        embeddings = [None] * len(raw_chunks)

    collection = get_collection(COLLECTION)
    ids, docs, metas, embs = [], [], [], []
    now = datetime.now(timezone.utc).isoformat()

    for i, (chunk, emb) in enumerate(zip(raw_chunks, embeddings)):
        if emb is None:
            continue
        ids.append(f"{source_id}_{i}")
        docs.append(chunk["text"])
        metas.append({
            "source_id": source_id,
            "filename": filename,
            "page_number": chunk.get("page_number") or 0,
            "section_heading": chunk.get("section_heading") or "",
            "chunk_index": i,
            "ingested_at": now,
        })
        embs.append(emb.tolist())

    if ids:
        collection.add(ids=ids, embeddings=embs, documents=docs, metadatas=metas)

    return source_id
