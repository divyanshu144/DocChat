"""Leakage check: fail loudly if training data overlaps the evaluation material.

Method: lower-case word 8-grams. A training example is checked on its retrieved context, question and answer (the
fixed serving prompt is removed first, because every prompt shares it). Reference material is every long string in the
evaluation files. Any shared 8-gram is a leak by default. The held-out documents are checked the same way.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from finetune.schema import TrainingExample

N = 8
_TOKEN = re.compile(r"[a-z0-9]+")
MIN_STRING = 40  # shorter strings in the reference files are labels and ids, not evidence

DEFAULT_REFERENCES = (
    "reports/quality-review-pack.jsonl",
    "reports/quality-review-pack-citations-fixed.jsonl",
    "data/heldout-quality-workload.json",
    "data/bench_prompts.jsonl",
    "eval/retrieval_golden.json",
)


class LeakageError(Exception):
    """Raised when training data shares text with evaluation data."""


def _hash(gram: tuple[str, ...]) -> int:
    return int.from_bytes(hashlib.blake2b(" ".join(gram).encode(), digest_size=8).digest(), "big")


def ngram_hashes(text: str, n: int = N) -> set[int]:
    tokens = _TOKEN.findall(text.lower())
    return {_hash(tuple(tokens[i:i + n])) for i in range(len(tokens) - n + 1)}


def _strings(node):
    if isinstance(node, str):
        if len(node) >= MIN_STRING:
            yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _strings(value)


def reference_texts(path: Path) -> list[str]:
    raw = path.read_text()
    try:
        records = [json.loads(raw)]
    except json.JSONDecodeError:
        records = [json.loads(line) for line in raw.splitlines() if line.strip()]
    return [s for record in records for s in _strings(record)]


def build_reference_index(paths: list[Path], n: int = N) -> dict[str, set[int]]:
    """Map each reference file to its set of n-gram hashes. A missing file is an error, never a silent skip."""
    index: dict[str, set[int]] = {}
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(f"decontamination reference is missing: {path}")
        grams: set[int] = set()
        for text in reference_texts(path):
            grams |= ngram_hashes(text, n)
        index[str(path)] = grams
    return index


def _example_text(example: TrainingExample) -> str:
    from finetune.validate_examples import SERVING_PREFIX
    system = example.system.removeprefix(SERVING_PREFIX)
    return "\n".join([system, example.question, example.answer])


def overlap(text: str, index: dict[str, set[int]], n: int = N) -> dict[str, int]:
    grams = ngram_hashes(text, n)
    return {name: len(grams & ref) for name, ref in index.items() if grams & ref}


def check_examples(examples: list[TrainingExample], index: dict[str, set[int]], max_shared: int = 0) -> None:
    leaks = []
    for example in examples:
        shared = overlap(_example_text(example), index)
        if sum(shared.values()) > max_shared:
            leaks.append((example.id, example.doc_ids, shared))
    if leaks:
        shown = "; ".join(f"{i} docs={d} shared={s}" for i, d, s in leaks[:5])
        raise LeakageError(f"{len(leaks)} training example(s) overlap evaluation data: {shown}")


def check_texts(named_texts: dict[str, str], index: dict[str, set[int]], max_shared: int = 0) -> None:
    """Document-level check, for source documents or held-out documents against an index."""
    leaks = {name: overlap(text, index) for name, text in named_texts.items()}
    leaks = {name: shared for name, shared in leaks.items() if sum(shared.values()) > max_shared}
    if leaks:
        raise LeakageError(f"{len(leaks)} document(s) overlap evaluation data: "
                           + "; ".join(f"{n} {s}" for n, s in list(leaks.items())[:5]))


def stock_ngrams(texts: dict[str, str], min_documents: int = 3) -> set[int]:
    """8-grams found in at least `min_documents` of the given documents: disclaimers, contact lines and other stock text.

    Counted among the training documents only, never including the held-out one, so a held-out document cannot
    make its own copied passage look like stock text.
    """
    counts: dict[int, int] = {}
    for text in texts.values():
        for gram in ngram_hashes(text):
            counts[gram] = counts.get(gram, 0) + 1
    return {g for g, c in counts.items() if c >= min_documents}


def overlapping_training_docs(train_texts: dict[str, str], heldout_texts: dict[str, str], stock: set[int],
                              min_fraction: float = 0.01) -> list[tuple[str, str, float]]:
    """(training doc, held-out doc, fraction) where one training document alone carries more than `min_fraction` of a
    held-out document's non-stock 8-grams. Such a training document is a near-copy of a source and should be excluded."""
    found = []
    train_grams = {name: ngram_hashes(text) - stock for name, text in train_texts.items()}
    for held, text in heldout_texts.items():
        grams = ngram_hashes(text) - stock
        for name, theirs in train_grams.items():
            fraction = len(grams & theirs) / len(grams) if grams else 0.0
            if fraction > min_fraction:
                found.append((name, held, round(fraction, 4)))
    return sorted(found, key=lambda row: -row[2])


def check_documents_disjoint(train_texts: dict[str, str], heldout_texts: dict[str, str], max_fraction: float = 0.02,
                             stock: set[int] | None = None) -> dict[str, float]:
    """Training documents must not contain the held-out documents' text.

    Different documents from one publisher legitimately share stock sentences, so stock 8-grams are ignored and the check
    fails on a fraction, not on any single shared 8-gram: more than `max_fraction` of a held-out document's remaining
    8-grams found in training text is a leak. Returns the fraction per held-out document for the report.
    """
    stock = stock or set()
    train_grams: set[int] = set()
    for text in train_texts.values():
        train_grams |= ngram_hashes(text) - stock
    fractions = {}
    for name, text in heldout_texts.items():
        grams = ngram_hashes(text) - stock
        fractions[name] = len(grams & train_grams) / len(grams) if grams else 0.0
    bad = {n: round(f, 3) for n, f in fractions.items() if f > max_fraction}
    if bad:
        raise LeakageError(f"held-out document(s) found in training text above {max_fraction:.0%}: {bad}")
    return fractions


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def record_hashes(paths: list[Path]) -> dict[str, str]:
    return {str(p): sha256_file(p) for p in paths}


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("examples", type=Path, help="JSONL of TrainingExample to check")
    parser.add_argument("--reference", type=Path, action="append", help="evaluation file (default: the standard set)")
    parser.add_argument("--heldout-texts", type=Path, help="JSON {name: text} of held-out documents to check against")
    parser.add_argument("--hashes-out", type=Path, help="write sha256 of the training and reference files here")
    args = parser.parse_args()
    references = args.reference or [Path(p) for p in DEFAULT_REFERENCES]
    index = build_reference_index(references)
    if args.heldout_texts:
        index[str(args.heldout_texts)] = set().union(*(ngram_hashes(t) for t in json.loads(args.heldout_texts.read_text()).values()))
    from finetune.validate_examples import load_examples
    examples = load_examples(args.examples)
    check_examples(examples, index)
    hashes = record_hashes([args.examples, *references] + ([args.heldout_texts] if args.heldout_texts else []))
    if args.hashes_out:
        args.hashes_out.write_text(json.dumps(hashes, indent=2) + "\n")
    print(json.dumps({"checked_examples": len(examples), "references": list(index), "result": "no overlap",
                      "sha256": hashes}, indent=2))


if __name__ == "__main__":
    main()
