import re
import asyncio
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx
import trafilatura
from langchain_text_splitters import RecursiveCharacterTextSplitter

import uuid as _uuid
from app.core.sources import source_collection
from app.core.qdrant import get_qdrant_client, get_qdrant_collection
from app.services.ingestion.storage import build_points, replace_source_points
from app.services.embedder import get_embedder

COLLECTION = source_collection()

_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1500,
    chunk_overlap=200,
    separators=["\n\n", "\n", ". ", " ", ""],
)


_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; DocChatBot/2.0; +https://github.com/docchat)"
}


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    return urlunparse((scheme, netloc, path, "", query, ""))


def _source_id_for_url(url: str) -> str:
    # Idempotency scope: canonical URL identity. Content changes at the same URL
    # replace all chunks for that source identity.
    return str(_uuid.uuid5(_uuid.NAMESPACE_URL, f"docchat:web:{_normalize_url(url)}"))


def _scrape(url: str) -> dict:
    response = httpx.get(url, timeout=30, follow_redirects=True, headers=_HEADERS)
    response.raise_for_status()
    content = trafilatura.extract(response.text, include_comments=False, include_tables=False)
    if not content:
        raise ValueError(f"Could not extract readable content from {url}")
    title_match = re.search(r"<title>(.*?)</title>", response.text, re.IGNORECASE | re.DOTALL)
    title = title_match.group(1).strip() if title_match else url
    return {"content": content, "title": title}


async def ingest_web(url: str) -> str:
    """Scrape URL, chunk, embed, and store in Qdrant. Returns source_id."""
    source_id = _source_id_for_url(url)
    loop = asyncio.get_running_loop()
    normalized_url = _normalize_url(url)
    domain = urlparse(normalized_url).netloc

    scraped = await loop.run_in_executor(None, _scrape, url)
    chunk_texts = await asyncio.to_thread(_splitter.split_text, scraped["content"])

    embedder = await asyncio.to_thread(get_embedder)
    points = await asyncio.to_thread(
        build_points, source_id, [{"text": text} for text in chunk_texts], embedder,
        {"source_type": "web", "url": normalized_url, "title": scraped["title"],
         "domain": domain, "scraped_at": datetime.now(timezone.utc).isoformat()},
    )
    await asyncio.to_thread(get_qdrant_collection, COLLECTION)
    client = await asyncio.to_thread(get_qdrant_client)
    await asyncio.to_thread(replace_source_points, client, COLLECTION, source_id, points)
    return source_id
