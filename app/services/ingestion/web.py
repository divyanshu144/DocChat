import re
import uuid
import asyncio
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
import trafilatura
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.chroma import get_collection
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
    """Scrape URL, chunk, embed, and store in ChromaDB. Returns source_id."""
    source_id = str(uuid.uuid4())
    loop = asyncio.get_running_loop()
    domain = urlparse(url).netloc

    scraped = await loop.run_in_executor(None, _scrape, url)
    chunk_texts = _splitter.split_text(scraped["content"])

    embedder = get_embedder()
    collection = get_collection(COLLECTION)
    ids, docs, metas, embs = [], [], [], []
    now = datetime.now(timezone.utc).isoformat()

    for i, text in enumerate(chunk_texts):
        if not text.strip() or not embedder:
            continue
        emb = embedder.embed_query(text)
        ids.append(f"{source_id}_{i}")
        docs.append(text)
        metas.append({
            "source_id": source_id,
            "url": url,
            "title": scraped["title"],
            "domain": domain,
            "chunk_index": i,
            "scraped_at": now,
        })
        embs.append(emb.tolist())

    if ids:
        collection.add(ids=ids, embeddings=embs, documents=docs, metadatas=metas)

    return source_id
