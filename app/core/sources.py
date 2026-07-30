from __future__ import annotations

from typing import Any

SOURCE_CHUNKS_COLLECTION = "source_chunks"
LEGACY_SOURCE_COLLECTIONS = {
    "pdf": "pdf_chunks",
    "youtube": "youtube_chunks",
    "web": "web_chunks",
}
KNOWN_SOURCE_TYPES = tuple(LEGACY_SOURCE_COLLECTIONS.keys())


def source_collection() -> str:
    return SOURCE_CHUNKS_COLLECTION


def legacy_collection_for_source(source_type: str) -> str | None:
    return LEGACY_SOURCE_COLLECTIONS.get(source_type)


def source_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        k: v
        for k, v in payload.items()
        if k
        in {
            "source_id",
            "source_type",
            "filename",
            "title",
            "url",
            "video_url",
            "domain",
            "ingested_at",
            "scraped_at",
        }
    }


def citation_label(source_type: str, metadata: dict[str, Any]) -> str:
    label = source_type.strip() or "source"
    display = {
        "pdf": "PDF",
        "youtube": "YouTube",
        "web": "Web",
    }.get(label, label.replace("_", " ").title())

    if source_type == "pdf":
        filename = metadata.get("filename") or metadata.get("title") or "document"
        page = metadata.get("page_number")
        suffix = f" p.{page}" if page not in (None, "", 0) else ""
        return f"[{display} - {filename}{suffix}]"

    if source_type == "youtube":
        title = metadata.get("title") or metadata.get("video_url") or metadata.get("url") or "video"
        timestamp = metadata.get("timestamp_start")
        suffix = f" @{timestamp}s" if timestamp not in (None, "") else ""
        return f"[{display} - {title}{suffix}]"

    title = metadata.get("title") or metadata.get("url") or metadata.get("filename") or metadata.get("source_id") or "source"
    return f"[{display} - {title}]"
