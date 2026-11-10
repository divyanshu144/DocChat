#!/usr/bin/env python3
"""Copy the dense-only source collection into a hybrid (dense + BM25) collection.

    venv/bin/python -m scripts.migrate_to_hybrid_collection --dry-run
    venv/bin/python -m scripts.migrate_to_hybrid_collection
    # then switch the app over (restart it):  QDRANT_SOURCE_COLLECTION=source_chunks_hybrid
    # roll back by unsetting that variable; the original collection is never modified or deleted.

Dense vectors and payloads are copied as stored, so nothing is re-embedded. Re-run it (idempotent) after
quiescing ingestion if sources were added while it ran. Exits 1 if the target does not match the source.
"""
from __future__ import annotations

import argparse
import sys

from app.core.config import settings
from app.core.qdrant import get_qdrant_client
from app.services.embedder import get_embedder
from app.services.hybrid_migration import migrate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", default=settings.qdrant_source_collection)
    parser.add_argument("--target", default="source_chunks_hybrid")
    parser.add_argument("--batch-size", type=int, default=settings.ingest_batch_size)
    parser.add_argument("--dry-run", action="store_true", help="read and embed, but write nothing")
    args = parser.parse_args(argv)

    client = get_qdrant_client()
    if not client.collection_exists(args.source):
        print(f"Source collection {args.source!r} does not exist", file=sys.stderr)
        return 2
    embedder = get_embedder()
    if embedder is None:
        print("The embedding service failed to load", file=sys.stderr)
        return 2

    report = migrate(client, embedder, args.source, args.target, batch_size=args.batch_size, dry_run=args.dry_run,
                     progress=lambda n: print(f"  copied {n} points", flush=True))
    verb = "would copy" if args.dry_run else "copied"
    print(f"{args.source} -> {args.target}: {verb} {report.copied}/{report.source_points} points"
          f" ({report.without_text} without text, dense-only)")
    if args.dry_run:
        return 0
    if not report.consistent:
        print(f"MISMATCH: {len(report.missing_in_target)} missing in target, "
              f"{len(report.extra_in_target)} only in target (deleted from source since an earlier run?)",
              file=sys.stderr)
        return 1
    print(f"Verified: both collections hold the same {report.source_points} point ids.\n"
          f"Switch over by setting QDRANT_SOURCE_COLLECTION={args.target} and restarting the app and any MCP server.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
