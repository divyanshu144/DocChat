"""Blinded human spot-check sheet for rows where two judges disagree.

Judges appear as "Judge A" and "Judge B" (the mapping is saved separately), the serving format is
never shown, and the human records which judge is closer to the evidence for each differing label.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from eval.compare_judge_labels import FIELDS, compare_files, load
from eval.judge_prompt import extract_evidence


def _claims(labels: dict) -> list[str]:
    out = []
    for claim in labels["claims"]:
        status = claim.get("status") or ("supported" if claim.get("supported") else "unsupported")
        out.append(f"  - [{status.upper() if status != 'supported' else status}] {claim['text']}")
    return out


def render(row: dict, a: dict, b: dict, number: int, differing: list[str]) -> str:
    out = [f"## {number}. {row['blind_id']}", "", f"**Question:** {row['query']}", "",
           f"**Expected facts:** {'; '.join(fact['text'] for fact in row['expected_facts'])}",
           f"**Abstention expected:** {row['expected_abstention']}",
           f"**Labels that differ:** {', '.join(differing) or 'claim counts only'}", "", "**Evidence:**", ""]
    out += [f"> {chunk}".replace("\n", "\n> ") + "\n" for chunk in extract_evidence(row["context"])]
    out += ["**Answer:**", "", row["answer"], ""]
    for name, labels in (("Judge A", a), ("Judge B", b)):
        out += [f"**{name}:**", ""]
        out += [f"- {field}: {labels[field]}" for field in FIELDS]
        out += [f"- unsupported: {labels['unsupported_claim_count']}, minor_imprecision: "
                f"{labels.get('minor_imprecision_count', 'n/a')}", f"- notes: {labels['notes']}", "- claims:",
                *_claims(labels), ""]
    return "\n".join(out) + "\n---\n"


def build(pack_path: Path, path_a: Path, path_b: Path, seed: int = 20261006) -> tuple[str, list[dict], dict]:
    pack = {r["blind_id"]: r for r in map(json.loads, pack_path.read_text().splitlines()) if r}
    a, b = load(path_a), load(path_b)
    details = compare_files(path_a, path_b)["row_details"]
    order = [d["blind_id"] for d in details]
    random.Random(seed).shuffle(order)
    by_id = {d["blind_id"]: d for d in details}
    header = ("# Judge disagreement sheet (blinded)\n\nFor every differing label decide which judge is closer to "
              "the evidence (A, B or neither) in `quality-judge-disagreement-verdicts.jsonl`. Judge identity and "
              "serving format are hidden on purpose.\n\n---\n\n")
    sheet = header + "".join(render(pack[i], a[i]["labels"], b[i]["labels"], n, list(by_id[i]["label_changes"]))
                             for n, i in enumerate(order, 1))
    template = [{"blind_id": i, "preferred": {f: None for f in by_id[i]["label_changes"]}
                 | ({"unsupported_claims": None} if by_id[i]["counts"]["unsupported"][0] != by_id[i]["counts"]["unsupported"][1] else {}),
                 "notes": ""} for i in order]
    selection = {"judge_a": sorted({f"{r['judge']['model']}/{r['judge']['prompt_version']}" for r in a.values()}),
                 "judge_b": sorted({f"{r['judge']['model']}/{r['judge']['prompt_version']}" for r in b.values()}),
                 "rows": {i: {"label_changes": by_id[i]["label_changes"], "counts": by_id[i]["counts"]} for i in order}}
    return sheet, template, selection


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--judge-a", type=Path, default=Path("reports/quality-judge-labels-v2.jsonl"))
    parser.add_argument("--judge-b", type=Path, default=Path("reports/quality-judge-labels-v2-gpt-6-astra.jsonl"))
    parser.add_argument("--pack", type=Path, default=Path("reports/quality-review-pack.jsonl"))
    parser.add_argument("--sheet", type=Path, default=Path("reports/quality-judge-disagreement-sheet.md"))
    parser.add_argument("--verdicts", type=Path, default=Path("reports/quality-judge-disagreement-verdicts.jsonl"))
    parser.add_argument("--selection", type=Path, default=Path("reports/quality-judge-disagreement-selection.json"))
    args = parser.parse_args()
    for path in (args.sheet, args.verdicts, args.selection):
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite {path}")
    sheet, template, selection = build(args.pack, args.judge_a, args.judge_b)
    args.sheet.write_text(sheet)
    args.verdicts.write_text("".join(json.dumps(row) + "\n" for row in template))
    args.selection.write_text(json.dumps(selection, indent=2) + "\n")
    print(json.dumps({"rows": len(template), "sheet": str(args.sheet), "verdicts": str(args.verdicts),
                      "selection": str(args.selection)}, indent=2))


if __name__ == "__main__":
    main()
