"""Build searchable chunk sets for the manifest's documents, using the app's own chunkers and embedder.

Points are the same `PointStruct` records `build_points` makes for a real ingest, so the metadata that ends up in
citation markers (`[Web - title]`, `[PDF - file p.N]`) is exactly what DocChat would show.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from qdrant_client.models import PointStruct

from finetune.extract import govuk_chunks, pdf_chunks
from finetune.fetch_sources import raw_name
from finetune.schema import Manifest, SourceDoc


def source_id(doc: SourceDoc) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"docchat-finetune:{doc.id}"))


def build_doc_points(doc: SourceDoc, raw_dir: Path, embedder) -> list[PointStruct]:
    from app.services.ingestion.storage import build_points
    path = raw_dir / raw_name(doc)
    if doc.kind == "govuk_guide":
        title, chunks = govuk_chunks(path)
        metadata = {"source_type": "web", "url": doc.url, "title": title, "domain": urlsplit(doc.url).netloc}
    else:
        chunks = pdf_chunks(path)
        metadata = {"source_type": "pdf", "filename": Path(urlsplit(doc.url).path).name, "title": doc.title}
    return build_points(source_id(doc), chunks, embedder, metadata)


def write_points(path: Path, points: list[PointStruct]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps({"id": str(p.id), "vector": list(map(float, p.vector)), "payload": p.payload},
                                       ensure_ascii=False) + "\n" for p in points))


def read_points(path: Path) -> list[PointStruct]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return [PointStruct(id=r["id"], vector=r["vector"], payload=r["payload"]) for r in rows]


def build_all(manifest: Manifest, raw_dir: Path, out_dir: Path, embedder) -> dict[str, int]:
    counts = {}
    for doc in manifest.documents:
        points = build_doc_points(doc, raw_dir, embedder)
        write_points(out_dir / f"{doc.id}.points.jsonl", points)
        counts[doc.id] = len(points)
    return counts


def main() -> None:
    import argparse
    from app.services.embedder import get_embedder
    from finetune.fetch_sources import load_manifest
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("finetune/manifest.json"))
    parser.add_argument("--raw", type=Path, default=Path("data/finetune/raw"))
    parser.add_argument("--out", type=Path, default=Path("data/finetune/corpus"))
    args = parser.parse_args()
    embedder = get_embedder()
    if embedder is None:
        raise SystemExit("fastembed failed to load; cannot build the corpus")
    counts = build_all(load_manifest(args.manifest), args.raw, args.out, embedder)
    print(json.dumps({"documents": len(counts), "chunks": sum(counts.values())}, indent=2))


if __name__ == "__main__":
    main()
