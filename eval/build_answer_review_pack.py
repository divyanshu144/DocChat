"""Join generated answers to workload evidence in a blinded review pack."""
from __future__ import annotations

import argparse
import json
import re
import secrets
from pathlib import Path

from eval.citations import CITATION_MARKER
from eval.workloads import load_workloads

_SOURCE_MARKER = re.compile(r"Source marker:\s*(\[[^\]\n]+\])")
_CITATION = CITATION_MARKER


def build_pack(workload_path: Path, answer_paths: list[Path]) -> tuple[list[dict], list[dict]]:
    workloads = load_workloads(workload_path, "replay")
    cases = {case.id: case for case in workloads.cases}
    pack, key = [], []
    for answer_path in answer_paths:
        with answer_path.open() as source:
            for line_number, line in enumerate(source, 1):
                if not line.strip():
                    continue
                answer = json.loads(line)
                case_id = answer.get("case_id")
                if case_id not in cases:
                    raise ValueError(f"{answer_path}:{line_number}: unknown case_id {case_id!r}")
                case = cases[case_id]
                blind_id = "review-" + secrets.token_hex(6)
                messages = answer.get("messages") or [message.model_dump() for message in case.messages]
                system = next((message["content"] for message in messages if message["role"] == "system"), "")
                context_markers = list(dict.fromkeys(_SOURCE_MARKER.findall(system)))
                citations = list(dict.fromkeys(_CITATION.findall(answer.get("answer", ""))))
                facts = [{"id": f"fact-{index:02d}", "text": text}
                         for index, text in enumerate(case.expected_facts, 1)]
                pack.append({
                    "blind_id": blind_id,
                    "workload_case_id": case.id,
                    "split": case.split,
                    "category": case.category,
                    "query": case.query,
                    "context": system,
                    "answer": answer.get("answer", ""),
                    "answer_status": answer.get("status", "ok"),
                    "expected_facts": facts,
                    "expected_evidence_chunk_ids": case.expected_evidence,
                    "source_markers_in_context": context_markers,
                    "emitted_citations": citations,
                    "expected_abstention": case.category == "negative_control",
                    "review": None if answer.get("status", "ok") != "ok" else {
                        "emitted_fact_ids": [],
                        "claims": [],
                        "abstained": None,
                        "pairwise_preference_group": case.id,
                        "notes": "",
                    },
                })
                key.append({"blind_id": blind_id, "workload_case_id": case.id,
                            "answer_file": str(answer_path), "model": answer.get("model"),
                            "run": answer.get("run_id"), "status": answer.get("status")})
    if not pack:
        raise ValueError("No answer samples were provided")
    return pack, key


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workload", type=Path, required=True)
    parser.add_argument("--answers", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True,
                        help="Store separately from the reviewer-facing pack")
    args = parser.parse_args()
    for path in (args.output, args.key):
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite {path}")
    pack, key = build_pack(args.workload, args.answers)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.key.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output:
        for row in pack:
            output.write(json.dumps(row, ensure_ascii=False) + "\n")
    with args.key.open("x") as output:
        json.dump({"schema_version": 1, "records": key}, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(json.dumps({"review_rows": len(pack), "workload_cases": len({row['workload_case_id'] for row in pack}),
                      "review_pack": str(args.output), "unblinding_key": str(args.key)}, indent=2))


if __name__ == "__main__":
    main()
