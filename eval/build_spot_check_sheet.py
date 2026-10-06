"""Build a blinded manual spot-check sheet for the LLM-assisted judge labels.

The sheet shows the question, evidence, answer and the judge's labels for a
risk-weighted sample, in shuffled order and without the serving format or the
selection reason. Reasons are saved to a separate selection file.
"""
from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path

from eval.judge_prompt import extract_evidence

_PAGE_RANGE = re.compile(r"\bp\.\d+-\d+")
VERDICT_FIELDS = ("answer_correct", "fully_supported", "unsupported_claim_count",
                  "citation_correct", "abstention_correct")


def select_rows(pack: list[dict], labels: list[dict], top_unsupported: int = 6,
                random_supported: int = 5, seed: int = 20261005) -> dict[str, list[str]]:
    """Return blind_id -> selection reasons."""
    by_pack = {row["blind_id"]: row for row in pack}
    reasons: dict[str, list[str]] = {}

    def add(blind_id: str, reason: str) -> None:
        reasons.setdefault(blind_id, []).append(reason)

    ok = [row for row in labels if row["parse_status"] == "ok"]
    for row in labels:
        if row["parse_status"] != "ok":
            add(row["blind_id"], "parse_failure")
    for row in ok:
        label = row["labels"]
        if label["answer_correct"] != "yes":
            add(row["blind_id"], f"answer_correct={label['answer_correct']}")
        if label["citation_correct"] in ("partial", "no"):
            add(row["blind_id"], f"citation_correct={label['citation_correct']}")
        if label["abstention_correct"] == "no":
            add(row["blind_id"], "abstention_correct=no")
        if _PAGE_RANGE.search(by_pack[row["blind_id"]]["answer"]) and label["citation_correct"] == "yes":
            add(row["blind_id"], "page_range_citation_marked_yes")
    worst = sorted(ok, key=lambda row: -row["labels"]["unsupported_claim_count"])[:top_unsupported]
    for row in worst:
        if row["labels"]["unsupported_claim_count"] > 0:
            add(row["blind_id"], "highest_unsupported_claims")
    clean = [row["blind_id"] for row in ok if row["labels"]["fully_supported"] == "yes"
             and row["blind_id"] not in reasons]
    for blind_id in random.Random(seed).sample(clean, min(random_supported, len(clean))):
        add(blind_id, "random_fully_supported")
    return reasons


def render(row: dict, label_row: dict, number: int) -> str:
    out = [f"## {number}. {row['blind_id']}", "", f"**Question:** {row['query']}", "",
           f"**Expected facts:** {'; '.join(fact['text'] for fact in row['expected_facts'])}",
           f"**Abstention expected:** {row['expected_abstention']}", "", "**Evidence:**", ""]
    out += [f"> {chunk}".replace("\n", "\n> ") + "\n" for chunk in extract_evidence(row["context"])]
    out += ["**Answer:**", "", row["answer"], "", "**Judge labels:**", ""]
    if label_row["parse_status"] != "ok":
        out += [f"- parse_status: {label_row['parse_status']}", f"- error: {label_row.get('error', '')[:600]}"]
    else:
        label = label_row["labels"]
        out += [f"- {field}: {label[field]}" for field in VERDICT_FIELDS]
        out += [f"- notes: {label['notes']}", "- claims:"]
        out += [f"  - [{'supported' if c['supported'] else 'UNSUPPORTED'}] {c['text']}" for c in label["claims"]]
    return "\n".join(out) + "\n\n---\n"


def build(pack_path: Path, labels_path: Path, seed: int = 20261005) -> tuple[str, list[dict], dict]:
    pack = [json.loads(line) for line in pack_path.read_text().splitlines() if line.strip()]
    labels = [json.loads(line) for line in labels_path.read_text().splitlines() if line.strip()]
    reasons = select_rows(pack, labels, seed=seed)
    by_pack = {row["blind_id"]: row for row in pack}
    by_label = {row["blind_id"]: row for row in labels}
    order = sorted(reasons)
    random.Random(seed + 1).shuffle(order)
    header = ("# Manual spot-check sheet (blinded)\n\nFor each row, compare the judge's labels to the "
              "evidence only. Mark agree/disagree per label in `quality-spot-check-verdicts.jsonl`. "
              "Serving format and selection reasons are hidden on purpose.\n\n---\n\n")
    sheet = header + "".join(render(by_pack[i], by_label[i], n) for n, i in enumerate(order, 1))
    template = [{"blind_id": i, **{f"{field}_agree": None for field in VERDICT_FIELDS}, "notes": ""}
                for i in order]
    return sheet, template, {i: reasons[i] for i in order}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, default=Path("reports/quality-review-pack.jsonl"))
    parser.add_argument("--labels", type=Path, default=Path("reports/quality-judge-labels.jsonl"))
    parser.add_argument("--sheet", type=Path, default=Path("reports/quality-spot-check-sheet.md"))
    parser.add_argument("--verdicts", type=Path, default=Path("reports/quality-spot-check-verdicts.jsonl"))
    parser.add_argument("--selection", type=Path, default=Path("reports/quality-spot-check-selection.json"))
    args = parser.parse_args()
    for path in (args.sheet, args.verdicts, args.selection):
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite {path}")
    sheet, template, selection = build(args.pack, args.labels)
    args.sheet.write_text(sheet)
    args.verdicts.write_text("".join(json.dumps(row) + "\n" for row in template))
    args.selection.write_text(json.dumps(selection, indent=2) + "\n")
    print(json.dumps({"rows": len(template), "sheet": str(args.sheet), "verdicts": str(args.verdicts),
                      "selection_reasons": str(args.selection)}, indent=2))


if __name__ == "__main__":
    main()
