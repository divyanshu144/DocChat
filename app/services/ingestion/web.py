import re
import asyncio
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx
import trafilatura
from langchain_text_splitters import RecursiveCharacterTextSplitter

import uuid as _uuid
from app.core.qdrant import get_qdrant_client, get_qdrant_collection
from qdrant_client.models import PointStruct
from app.services.embedder import get_embedder

COLLECTION = "web_chunks"

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
    # overwrite same-index chunks; no document-version cleanup is done here.
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
    chunk_texts = _splitter.split_text(scraped["content"])

    embedder = get_embedder()
    get_qdrant_collection(COLLECTION)
    client = get_qdrant_client()
    points: list[PointStruct] = []
    now = datetime.now(timezone.utc).isoformat()

    for i, text in enumerate(chunk_texts):
        if not text.strip() or not embedder:
            continue
        emb = embedder.embed_query(text)
        point_id = str(_uuid.uuid5(_uuid.NAMESPACE_DNS, f"{source_id}_{i}"))
        points.append(PointStruct(
            id=point_id,
            vector=emb.tolist(),
            payload={
                "text": text,
                "source_id": source_id,
                "url": normalized_url,
                "title": scraped["title"],
                "domain": domain,
                "chunk_index": i,
                "scraped_at": now,
            },
        ))

    if points:
        client.upsert(collection_name=COLLECTION, points=points)

    return source_id
