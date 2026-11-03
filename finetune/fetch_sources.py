"""Download the manifest's documents and record a hash lock.

Raw files go to data/finetune/raw/ (git-ignored). Only the manifest and `finetune/sources.lock.json`, which holds each
file's sha256, size and retrieval date, are committed. Web content changes over time, so a changed hash on a later
fetch is reported and the local copy of the first fetch stays authoritative for a run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from finetune.schema import LockEntry, Manifest, SourceDoc

USER_AGENT = "Mozilla/5.0 (compatible; DocChatResearch/1.0; building an open-licence evaluation corpus)"
GOVUK_API = "https://www.gov.uk/api/content"


def raw_name(doc: SourceDoc) -> str:
    return f"{doc.id}.json" if doc.kind == "govuk_guide" else f"{doc.id}.pdf"


def download_url(doc: SourceDoc) -> str:
    if doc.kind == "govuk_guide":
        path = doc.url.split("gov.uk", 1)[1]
        return GOVUK_API + path
    return doc.url


def load_manifest(path: Path) -> Manifest:
    return Manifest.model_validate_json(path.read_text())


def load_lock(path: Path) -> dict[str, LockEntry]:
    if not path.exists():
        return {}
    return {k: LockEntry.model_validate(v) for k, v in json.loads(path.read_text()).items()}


def fetch(manifest: Manifest, out_dir: Path, lock_path: Path, *, client: httpx.Client | None = None,
          pause_s: float = 0.3) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    lock = load_lock(lock_path)
    client = client or httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True)
    result = {"downloaded": 0, "reused": 0, "changed_upstream": []}
    for doc in manifest.documents:
        target = out_dir / raw_name(doc)
        if target.exists() and doc.id in lock:
            data = target.read_bytes()
            if hashlib.sha256(data).hexdigest() != lock[doc.id].sha256:
                raise ValueError(f"{target} does not match its recorded hash; delete it to fetch again")
            result["reused"] += 1
            continue
        response = client.get(download_url(doc))
        response.raise_for_status()
        data = response.content
        if doc.kind == "pdf" and not data.startswith(b"%PDF"):
            raise ValueError(f"{doc.url} did not return a PDF")
        digest = hashlib.sha256(data).hexdigest()
        if doc.id in lock and lock[doc.id].sha256 != digest:
            result["changed_upstream"].append(doc.id)
        target.write_bytes(data)
        lock[doc.id] = LockEntry(sha256=digest, bytes=len(data), retrieved_at=datetime.now(timezone.utc).isoformat())
        result["downloaded"] += 1
        time.sleep(pause_s)
    lock_path.write_text(json.dumps({k: v.model_dump() for k, v in sorted(lock.items())}, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("finetune/manifest.json"))
    parser.add_argument("--out", type=Path, default=Path("data/finetune/raw"))
    parser.add_argument("--lock", type=Path, default=Path("finetune/sources.lock.json"))
    args = parser.parse_args()
    print(json.dumps(fetch(load_manifest(args.manifest), args.out, args.lock), indent=2))


if __name__ == "__main__":
    main()
