"""Generate grounded-answer training examples with a teacher model.

For each training or validation document: pick windows, have the teacher write answerable and unanswerable questions,
retrieve real context for each question with the app's retriever logic, and let the teacher answer using the real
synthesizer prompt. Answerable questions are kept only when retrieval brought back the window they came from. Questions
with no retrieved context are skipped, because serving never calls the model in that case. Nothing is validated
here: `validate_examples.py` decides what survives.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from finetune.corpus import read_points, source_id
from finetune.fetch_sources import load_manifest
from finetune.questions import ask_questions, pick_windows
from finetune.retrieval import CorpusIndex, build_messages
from finetune.schema import Manifest, SourceDoc, TrainingExample
from finetune.teacher import Teacher


def _answer(teacher: Teacher, messages: list[dict]) -> str:
    return teacher.complete(messages, max_tokens=700, temperature=0.2).strip()


def examples_for_document(doc: SourceDoc, index: CorpusIndex, other_ids: list[SourceDoc], teacher: Teacher,
                          rng: random.Random, windows: int = 6, answerable: int = 3, unanswerable: int = 1,
                          multi_doc_rate: float = 0.2) -> list[TrainingExample]:
    sid = source_id(doc)
    ids = index.chunk_ids_in_order(sid)
    texts = {i: index.text(i) for i in ids}
    out: list[TrainingExample] = []
    for window in pick_windows(ids, texts, windows, rng):
        questions, off_topic = ask_questions(teacher, window, answerable, unanswerable)
        jobs = [(q["question"], "answerable") for q in questions] + [(q, "abstain") for q in off_topic]
        for question, kind in jobs:
            scope, doc_ids = [sid], [doc.id]
            if other_ids and rng.random() < multi_doc_rate:
                extra = rng.choice(other_ids)
                scope, doc_ids = [sid, source_id(extra)], [doc.id, extra.id]
            chunks = index.retrieve(question, scope)
            if not chunks:
                continue  # serving answers this case without the model
            if kind == "answerable" and not set(window.chunk_ids) & {c["id"] for c in chunks}:
                continue  # retrieval missed the passage; the answer would not be grounded in what was supplied
            messages = build_messages(question, chunks)
            answer = _answer(teacher, messages)
            messages.append({"role": "assistant", "content": answer})
            out.append(TrainingExample(id=TrainingExample.make_id(messages), split=doc.split, kind=kind,
                                       doc_ids=doc_ids, messages=messages, teacher=teacher.name))
    return out


def generate(manifest: Manifest, corpus_dir: Path, teacher: Teacher, output: Path, *, seed: int = 13,
             limit_docs: int | None = None, **kwargs) -> int:
    from app.services.embedder import get_embedder
    embedder = get_embedder()
    if embedder is None:
        raise RuntimeError("fastembed failed to load")
    docs = [d for d in manifest.documents if d.split in {"train", "validation"}][:limit_docs]
    points = [p for d in docs for p in read_points(corpus_dir / f"{d.id}.points.jsonl")]
    index = CorpusIndex(points, lambda q: embedder.embed_query(q).tolist())
    rng = random.Random(seed)
    written = 0
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w") as target:
        for doc in docs:
            same_split = [d for d in docs if d.split == doc.split and d.id != doc.id]  # never mix train with validation
            for example in examples_for_document(doc, index, same_split, teacher, rng, **kwargs):
                target.write(example.model_dump_json() + "\n")
                target.flush()
                written += 1
    return written


def main() -> None:
    from finetune.teacher import HttpTeacher
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("finetune/manifest.json"))
    parser.add_argument("--corpus", type=Path, default=Path("data/finetune/corpus"))
    parser.add_argument("--output", type=Path, default=Path("data/finetune/examples.raw.jsonl"))
    parser.add_argument("--base-url", required=True, help="OpenAI-compatible endpoint of the teacher")
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-key-file", type=Path)
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument("--limit-docs", type=int)
    parser.add_argument("--windows", type=int, default=6)
    args = parser.parse_args()
    teacher = HttpTeacher(args.base_url, args.model, args.api_key_file)
    count = generate(load_manifest(args.manifest), args.corpus, teacher, args.output, seed=args.seed,
                     limit_docs=args.limit_docs, windows=args.windows)
    print(json.dumps({"examples_written": count, "output": str(args.output)}))


if __name__ == "__main__":
    main()
