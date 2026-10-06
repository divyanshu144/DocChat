"""Write a copy of the review pack with `emitted_citations` recomputed by the stricter marker pattern.

The original pack is never modified and blind ids are unchanged, so the existing unblinding key and
judge labels still join. Only rows whose emitted citations change are reported.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from eval.citations import CITATION_MARKER


def refresh(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    out, changed = [], []
    for row in rows:
        fixed = list(dict.fromkeys(CITATION_MARKER.findall(row.get("answer", ""))))
        if fixed != row.get("emitted_citations"):
            changed.append({"blind_id": row["blind_id"], "before": row.get("emitted_citations"), "after": fixed})
        out.append({**row, "emitted_citations": fixed})
    return out, changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, default=Path("reports/quality-review-pack.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("reports/quality-review-pack-citations-fixed.jsonl"))
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite {args.output}")
    rows = [json.loads(line) for line in args.pack.read_text().splitlines() if line.strip()]
    fixed, changed = refresh(rows)
    args.output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in fixed))
    print(json.dumps({"rows": len(fixed), "rows_changed": len(changed), "changed": changed,
                      "output": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
