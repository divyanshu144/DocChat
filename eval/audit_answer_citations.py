"""Measure exact source-marker citation coverage without judging claim support."""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from eval.citations import CITATION_MARKER

_MARKER = CITATION_MARKER
_CONTEXT_MARKER = re.compile(r"Source marker:\s*(\[[^\]\n]+\])")


def _context(row: dict) -> str:
    return "\n".join(message.get("content", "") for message in row.get("messages", [])
                     if message.get("role") == "system")


def _score(rows: list[dict]) -> dict:
    successful = [row for row in rows if row.get("status") == "ok"]
    citation_ids, valid_ids, answer_with_valid = 0, 0, 0
    per_case = []
    for row in successful:
        context_ids = set(_CONTEXT_MARKER.findall(_context(row)))
        emitted = _MARKER.findall(row.get("answer", ""))
        valid = [citation for citation in emitted if citation in context_ids]
        citation_ids += len(emitted)
        valid_ids += len(valid)
        answer_with_valid += bool(valid)
        per_case.append({"case_id": row.get("case_id"), "emitted": len(emitted),
                         "valid": len(valid), "invalid": len(emitted) - len(valid)})
    return {"requests": len(rows), "successful_answers": len(successful),
            "failed_answers": len(rows) - len(successful),
            "answer_citation_coverage": answer_with_valid / len(successful) if successful else None,
            "citation_precision": valid_ids / citation_ids if citation_ids else None,
            "emitted_citation_markers": citation_ids, "valid_citation_markers": valid_ids,
            "invalid_citation_markers": citation_ids - valid_ids, "cases": per_case}


def audit(paths: list[Path]) -> dict:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for path in paths:
        with path.open() as source:
            for line in source:
                if not line.strip():
                    continue
                row = json.loads(line)
                groups[(str(row.get("model", path.stem)), str(row.get("split", "unknown")))].append(row)
    if not groups:
        raise ValueError("No answer rows found")
    return {"groups": [{"model": model, "split": split, **_score(rows)}
                       for (model, split), rows in sorted(groups.items())],
            "definition": "Valid means the exact cited bracket marker occurs in the captured context. This does not assess whether claims are supported."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("answers", nargs="+", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit(args.answers)
    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n")
    print(rendered)


if __name__ == "__main__":
    main()
