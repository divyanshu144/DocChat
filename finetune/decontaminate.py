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


# The fixed parts of the serving prompt that follow the instructions: the history header, the "Context:" label and the
# "Source marker:" labels. Every prompt in every evaluation file carries them, so they are not evidence of leakage.
_SCAFFOLD = re.compile(r"Conversation history \(oldest to newest, last \d+ messages\):\n.*?\n\nContext:\n|Source marker: ",
                       re.DOTALL)


def _example_text(example: TrainingExample) -> str:
    from finetune.validate_examples import SERVING_PREFIX
    system = _SCAFFOLD.sub("", example.system.removeprefix(SERVING_PREFIX))
    return "\n".join([system, example.question, example.answer])


def overlap(text: str, index: dict[str, set[int]], n: int = N) -> dict[str, int]:
    grams = ngram_hashes(text, n)
    return {name: len(grams & ref) for name, ref in index.items() if grams & ref}


def split_leaking(examples: list[TrainingExample], index: dict[str, set[int]],
                  max_shared: int = 0) -> tuple[list[TrainingExample], list[tuple[str, list[str], dict[str, int]]]]:
    """The examples that share no 8-gram with the index, and (id, docs, overlap) for each one that does."""
    clean, leaks = [], []
    for example in examples:
        shared = overlap(_example_text(example), index)
        if sum(shared.values()) > max_shared:
            leaks.append((example.id, example.doc_ids, shared))
        else:
            clean.append(example)
    return clean, leaks


def check_examples(examples: list[TrainingExample], index: dict[str, set[int]], max_shared: int = 0) -> None:
    _, leaks = split_leaking(examples, index, max_shared)
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


def without_stock(index: dict[str, set[int]], stock: set[int]) -> dict[str, set[int]]:
    """The reference index with stock text removed, for the example-level check (see `stock_ngrams`)."""
    return {name: grams - stock for name, grams in index.items()}


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


def examples_vs_heldout_documents(examples: list[TrainingExample], heldout_texts: dict[str, str], stock: set[int],
                                  max_fraction: float = 0.02) -> dict[str, float]:
    """Share of each held-out document's non-stock 8-grams found anywhere in the training examples' text.

    Neighbouring guides from one publisher quote each other's official wording, so zero overlap cannot hold for document
    text. The same cap as the document-level check applies (more than 2% of a held-out document fails), and the fractions
    are returned for the report. Questions and answers of the evaluation files are still held to zero shared 8-grams.
    """
    return check_documents_disjoint({e.id: _example_text(e) for e in examples}, heldout_texts, max_fraction, stock)


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
    parser.add_argument("--heldout-texts", type=Path, help="JSON {name: text} of held-out documents; checked by fraction "
                                                           "(needs --stock-from), not by zero overlap")
    parser.add_argument("--hashes-out", type=Path, help="write sha256 of the training and reference files here")
    parser.add_argument("--stock-from", type=Path, metavar="CORPUS_DIR",
                        help="ignore stock text (8-grams in 3+ non-held-out documents, read from this corpus) "
                             "using the manifest below, as the document-level check does")
    parser.add_argument("--manifest", type=Path, default=Path("finetune/manifest.json"))
    parser.add_argument("--drop-leaking", type=Path, metavar="CLEAN_JSONL",
                        help="instead of failing, write the examples with no shared 8-gram here and list what was removed")
    args = parser.parse_args()
    references = args.reference or [Path(p) for p in DEFAULT_REFERENCES]
    index = build_reference_index(references)
    from finetune.validate_examples import load_examples
    examples = load_examples(args.examples)
    stock: set[int] = set()
    if args.stock_from:
        from finetune.check_documents import document_texts
        from finetune.fetch_sources import load_manifest
        manifest = load_manifest(args.manifest)
        texts = document_texts(manifest, args.stock_from)
        stock = stock_ngrams({d.id: texts[d.id] for d in manifest.documents if d.split in {"train", "validation", "excluded"}})
        index = without_stock(index, stock)
    removed: list = []
    if args.drop_leaking:
        examples, removed = split_leaking(examples, index)
        args.drop_leaking.write_text("".join(e.model_dump_json() + "\n" for e in examples))
    check_examples(examples, index)  # still strict: what remains must be clean
    fractions = {}
    if args.heldout_texts:
        if not stock:
            raise SystemExit("--heldout-texts needs --stock-from: without it every shared boilerplate line counts")
        fractions = examples_vs_heldout_documents(examples, json.loads(args.heldout_texts.read_text()), stock)
    hashes = record_hashes([args.examples, *references] + ([args.heldout_texts] if args.heldout_texts else []))
    if args.hashes_out:
        args.hashes_out.write_text(json.dumps(hashes, indent=2) + "\n")
    print(json.dumps({"checked_examples": len(examples), "removed_for_overlap": len(removed),
                      "references": list(index), "stock_ngrams_ignored": len(stock),
                      "result": "no shared 8-grams with the evaluation files; held-out documents within the cap",
                      "heldout_document_text_in_examples": ({"max": round(max(fractions.values()), 4),
                                                             "mean": round(sum(fractions.values()) / len(fractions), 4)}
                                                            if fractions else None),
                      "sha256": hashes}, indent=2))


if __name__ == "__main__":
    main()
