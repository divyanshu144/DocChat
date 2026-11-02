"""Turn raw downloads into text and chunks, using the same splitters the app uses at ingestion."""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

_BREAKS = re.compile(r"</(?:p|li|h[1-6]|tr|div|ul|ol|table)>|<br\s*/?>", re.IGNORECASE)
_TAGS = re.compile(r"<[^>]+>")


def html_to_text(markup: str) -> str:
    text = _TAGS.sub("", _BREAKS.sub("\n", markup))
    text = html.unescape(text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def govuk_text(data: dict) -> str:
    """Plain text of a GOV.UK guide: each part's title on its own line, then its body."""
    parts = data.get("details", {}).get("parts") or []
    blocks = [data.get("title", "")]
    for part in parts:
        blocks.append(part.get("title", ""))
        blocks.append(html_to_text(part.get("body", "")))
    return "\n\n".join(block for block in blocks if block)


def govuk_chunks(path: Path) -> tuple[str, list[dict]]:
    """(title, chunks) using the web ingestion splitter (1,500 characters, 200 overlap)."""
    from app.services.ingestion.web import _splitter
    data = json.loads(path.read_text())
    return data["title"], [{"text": t} for t in _splitter.split_text(govuk_text(data)) if t.strip()]


def pdf_chunks(path: Path) -> list[dict]:
    """Chunks with page numbers, using the PDF ingestion extractor and splitter."""
    from app.services.ingestion.pdf import _chunk_segments, _extract_pdf_segments
    return _chunk_segments(_extract_pdf_segments(path))
