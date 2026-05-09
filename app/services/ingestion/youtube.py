import uuid
import asyncio
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs

from app.core.chroma import get_collection
from app.services.embedder import get_embedder

COLLECTION = "youtube_chunks"
CHUNK_DURATION_SECONDS = 60


def _extract_video_id(url: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname in ("youtu.be",):
        return parsed.path.lstrip("/")
    qs = parse_qs(parsed.query)
    return qs["v"][0]


def _fetch_transcript(video_id: str) -> list[dict]:
    from youtube_transcript_api import YouTubeTranscriptApi
    api = YouTubeTranscriptApi()
    transcript = api.fetch(video_id)
    return [{"text": s.text, "start": s.start, "duration": s.duration} for s in transcript]


def _get_video_metadata(video_id: str, url: str) -> dict:
    import re
    import httpx
    try:
        resp = httpx.get(url, timeout=15, follow_redirects=True,
                         headers={"User-Agent": "Mozilla/5.0 (compatible; DocChatBot/2.0)"})
        title_match = re.search(r'"title":"([^"]+)"', resp.text)
        author_match = re.search(r'"ownerChannelName":"([^"]+)"', resp.text)
        title = title_match.group(1) if title_match else url
        channel = author_match.group(1) if author_match else "Unknown"
    except Exception:
        title, channel = url, "Unknown"
    return {"title": title, "channel": channel, "video_id": video_id}


def _chunk_transcript(transcript: list[dict]) -> list[dict]:
    if not transcript:
        return []
    chunks: list[dict] = []
    current_texts: list[str] = []
    current_start = transcript[0]["start"]
    current_end = current_start

    for seg in transcript:
        seg_end = seg["start"] + seg.get("duration", 0)
        # Check if adding this segment would exceed the duration limit
        if current_texts and seg_end - current_start >= CHUNK_DURATION_SECONDS:
            # Save current chunk and start a new one
            chunks.append({
                "text": " ".join(current_texts),
                "timestamp_start": round(current_start),
                "timestamp_end": round(current_end),
            })
            current_texts = []
            current_start = seg["start"]

        current_texts.append(seg["text"])
        current_end = seg_end

    if current_texts:
        chunks.append({
            "text": " ".join(current_texts),
            "timestamp_start": round(current_start),
            "timestamp_end": round(current_end),
        })
    return chunks


async def ingest_youtube(url: str) -> str:
    """Fetch YouTube transcript, chunk, embed, and store in ChromaDB. Returns source_id."""
    source_id = str(uuid.uuid4())
    loop = asyncio.get_running_loop()
    video_id = _extract_video_id(url)

    meta, transcript = await asyncio.gather(
        loop.run_in_executor(None, _get_video_metadata, video_id, url),
        loop.run_in_executor(None, _fetch_transcript, video_id),
    )

    chunks = _chunk_transcript(transcript)
    embedder = get_embedder()
    collection = get_collection(COLLECTION)
    ids, docs, metas, embs = [], [], [], []
    now = datetime.now(timezone.utc).isoformat()

    for i, chunk in enumerate(chunks):
        if not embedder:
            continue
        emb = embedder.embed_query(chunk["text"])
        ids.append(f"{source_id}_{i}")
        docs.append(chunk["text"])
        metas.append({
            "source_id": source_id,
            "video_id": meta["video_id"],
            "video_url": url,
            "title": meta["title"],
            "channel": meta["channel"],
            "timestamp_start": chunk["timestamp_start"],
            "timestamp_end": chunk["timestamp_end"],
            "chunk_index": i,
            "ingested_at": now,
        })
        embs.append(emb.tolist())

    if ids:
        collection.add(ids=ids, embeddings=embs, documents=docs, metadatas=metas)

    return source_id
