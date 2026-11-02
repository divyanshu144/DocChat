"""Pick GOV.UK guides for the manifest, deterministically.

GOV.UK content is Crown copyright published under the Open Government Licence (https://www.gov.uk/help/terms-conditions).
Selection rules: guides of 6,000 to 40,000 characters, no topic that is evaluation evidence, ordered by a hash of the
path so the choice does not depend on popularity at the time it was run. The first N after sorting are used, split by
document: 12 held out, 4 validation, the rest train.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import httpx

from finetune.extract import govuk_text
from finetune.fetch_sources import GOVUK_API, USER_AGENT
from finetune.schema import FORBIDDEN_TITLE_WORDS, slug

SEARCH = "https://www.gov.uk/api/search.json"
OGL_URL = "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/"
TERMS_URL = "https://www.gov.uk/help/terms-conditions"
# Topics that overlap the existing evaluation (working-time rules) or are thin transaction pages.
SKIP_WORDS = FORBIDDEN_TITLE_WORDS + ("sign in", "log in", "one login", "hmrc online services")


def candidate_paths(client: httpx.Client, count: int = 600) -> list[dict]:
    rows: list[dict] = []
    for start in range(0, count, 100):
        response = client.get(SEARCH, params={"filter_format": "guide", "count": 100, "start": start,
                                              "fields": "link,title"})
        response.raise_for_status()
        rows.extend(response.json()["results"])
    return rows


def pick(rows: list[dict], client: httpx.Client, total: int, heldout: int, validation: int) -> list[dict]:
    ordered = sorted(rows, key=lambda r: hashlib.sha256(r["link"].encode()).hexdigest())
    chosen: list[dict] = []
    for row in ordered:
        if len(chosen) == total:
            break
        if any(word in row["title"].lower() for word in SKIP_WORDS):
            continue
        time.sleep(0.2)
        response = client.get(GOVUK_API + row["link"])
        if response.status_code != 200:
            continue
        data = response.json()
        if data.get("withdrawn_notice") or data.get("document_type") != "guide":
            continue
        length = len(govuk_text(data))
        if not 6000 <= length <= 40000:
            continue
        chosen.append({"link": row["link"], "title": data["title"], "chars": length})
    docs = []
    for index, row in enumerate(chosen):
        split = "heldout" if index < heldout else "validation" if index < heldout + validation else "train"
        docs.append({"id": f"govuk-{slug(row['link'].strip('/'))}"[:80], "title": row["title"], "kind": "govuk_guide",
                     "url": "https://www.gov.uk" + row["link"], "licence": "Open Government Licence v3.0 (Crown copyright)",
                     "licence_url": TERMS_URL, "split": split})
    return docs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--total", type=int, default=48)
    parser.add_argument("--heldout", type=int, default=12)
    parser.add_argument("--validation", type=int, default=4)
    parser.add_argument("--output", type=Path, default=Path("finetune/govuk_selection.json"))
    args = parser.parse_args()
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60) as client:
        docs = pick(candidate_paths(client), client, args.total, args.heldout, args.validation)
    args.output.write_text(json.dumps(docs, indent=2) + "\n")
    print(f"selected {len(docs)} guides -> {args.output}")


if __name__ == "__main__":
    main()
