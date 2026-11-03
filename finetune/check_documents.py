"""Document-level leakage report: do any source documents overlap the evaluation files, or do training documents
contain the held-out ones? Fails loudly (LeakageError) and otherwise writes a small JSON report with hashes.

Stock text (8-grams found in three or more training documents, such as publisher disclaimers) is ignored. A training
document that alone carries more than 1% of a held-out document's remaining text is treated as a near-copy: it must be
set to the `excluded` split in the manifest, with a note saying why.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from finetune.corpus import read_points
from finetune.decontaminate import (
    DEFAULT_REFERENCES, LeakageError, build_reference_index, check_documents_disjoint, check_texts,
    overlapping_training_docs, record_hashes, stock_ngrams)
from finetune.fetch_sources import load_manifest
from finetune.schema import Manifest


def document_texts(manifest: Manifest, corpus_dir: Path) -> dict[str, str]:
    return {d.id: "\n".join(p.payload["text"] for p in sorted(read_points(corpus_dir / f"{d.id}.points.jsonl"),
                                                              key=lambda p: p.payload["chunk_index"]))
            for d in manifest.documents}


def run(manifest: Manifest, corpus_dir: Path, references: list[Path], lock_path: Path) -> dict:
    texts = document_texts(manifest, corpus_dir)
    index = build_reference_index(references)
    check_texts(texts, index)  # no document may share an 8-gram with the evaluation material
    train = {d.id: texts[d.id] for d in manifest.documents if d.split in {"train", "validation"}}
    heldout = {d.id: texts[d.id] for d in manifest.documents if d.split == "heldout"}
    # Excluded documents still count as evidence of what is stock text: a passage that appears in three non-held-out
    # documents is boilerplate whether or not each of them is used for training.
    stock = stock_ngrams({**train, **{d.id: texts[d.id] for d in manifest.by_split("excluded")}})
    copies = overlapping_training_docs(train, heldout, stock)
    if copies:
        raise LeakageError("training document(s) carry over 1% of a held-out document's text; set their split to "
                           f"'excluded' in the manifest: {copies[:5]}")
    fractions = check_documents_disjoint(train, heldout, stock=stock)
    return {
        "documents": {s: len(manifest.by_split(s)) for s in ("train", "validation", "heldout", "excluded")},
        "excluded": {d.id: d.note for d in manifest.by_split("excluded")},
        "stock_ngrams_ignored": len(stock),
        "references_checked": [str(p) for p in references],
        "documents_vs_evaluation_files": "no shared 8-grams",
        "heldout_in_training_text_fraction": {"max": round(max(fractions.values()), 4),
                                              "mean": round(sum(fractions.values()) / len(fractions), 4)},
        "sha256": {"sources_lock": record_hashes([lock_path])[str(lock_path)], **record_hashes(references)},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("finetune/manifest.json"))
    parser.add_argument("--corpus", type=Path, default=Path("data/finetune/corpus"))
    parser.add_argument("--lock", type=Path, default=Path("finetune/sources.lock.json"))
    parser.add_argument("--output", type=Path, default=Path("finetune/document-leakage-report.json"))
    parser.add_argument("--reference", type=Path, action="append")
    args = parser.parse_args()
    references = args.reference or [Path(p) for p in DEFAULT_REFERENCES]
    report = run(load_manifest(args.manifest), args.corpus, references, args.lock)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
