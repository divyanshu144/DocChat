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
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable
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
                          multi_doc_rate: float = 0.2,
                          on_error: Callable[[Exception], None] | None = None) -> list[TrainingExample]:
    sid = source_id(doc)
    ids = index.chunk_ids_in_order(sid)
    texts = {i: index.text(i) for i in ids}
    out: list[TrainingExample] = []
    for window in pick_windows(ids, texts, windows, rng):
        try:
            questions, off_topic = ask_questions(teacher, window, answerable, unanswerable)
        except RuntimeError as exc:  # the teacher gave up on this call; lose this window, not the whole run
            if on_error is None:
                raise
            on_error(exc)
            continue
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
            try:
                answer = _answer(teacher, messages)
            except RuntimeError as exc:
                if on_error is None:
                    raise
                on_error(exc)
                continue
            messages.append({"role": "assistant", "content": answer})
            out.append(TrainingExample(id=TrainingExample.make_id(messages), split=doc.split, kind=kind,
                                       doc_ids=doc_ids, messages=messages, teacher=teacher.name))
    return out


class _LockedIndex:
    """Serialises access to the in-memory index. Only the teacher calls, which dominate the time, run in parallel."""

    def __init__(self, index: CorpusIndex):
        self._index, self._lock = index, threading.Lock()

    def __getattr__(self, name):
        method = getattr(self._index, name)

        def locked(*args, **kwargs):
            with self._lock:
                return method(*args, **kwargs)
        return locked


def generate(manifest: Manifest, corpus_dir: Path, teacher: Teacher, output: Path, *, seed: int = 13,
             limit_docs: int | None = None, workers: int = 1, resume: bool = False,
             max_failure_rate: float = 0.25, **kwargs) -> int:
    from app.services.embedder import get_embedder
    embedder = get_embedder()
    if embedder is None:
        raise RuntimeError("fastembed failed to load")
    docs = [d for d in manifest.documents if d.split in {"train", "validation"}][:limit_docs]
    points = [p for d in docs for p in read_points(corpus_dir / f"{d.id}.points.jsonl")]
    index = _LockedIndex(CorpusIndex(points, lambda q: embedder.embed_query(q).tolist()))

    failures: list[Exception] = []

    def for_document(doc: SourceDoc) -> list[TrainingExample]:
        same_split = [d for d in docs if d.split == doc.split and d.id != doc.id]  # never mix train with validation
        # One generator per document, so the result does not depend on which worker finishes first.
        return examples_for_document(doc, index, same_split, teacher, random.Random(f"{seed}:{doc.id}"),
                                     on_error=failures.append, **kwargs)

    # A document is written whole, as soon as it is done, so a crash loses at most the documents in flight.
    # With resume, documents already in the file are skipped and the file is appended to.
    done: set[str] = set()
    if resume and output.exists():
        done = {json.loads(line)["doc_ids"][0] for line in output.read_text().splitlines() if line.strip()}
    todo = [d for d in docs if d.id not in done]
    written = 0
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a" if resume else "w") as target, ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(for_document, d): d for d in todo}
        for future in as_completed(futures):
            examples = future.result()
            for example in examples:
                target.write(example.model_dump_json() + "\n")
                written += 1
            target.flush()
            print(f"{futures[future].id}: {len(examples)} examples ({len(failures)} teacher failures so far)",
                  file=sys.stderr, flush=True)
    calls = max(1, written + len(failures))
    if failures and len(failures) / calls > max_failure_rate:
        raise RuntimeError(f"{len(failures)} teacher calls failed ({len(failures) / calls:.0%}); last: {failures[-1]}")
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
    parser.add_argument("--workers", type=int, default=1, help="documents processed in parallel (teacher calls overlap)")
    parser.add_argument("--unanswerable", type=int, default=1, help="off-topic questions per window")
    parser.add_argument("--resume", action="store_true", help="append, skipping documents already in the output file")
    args = parser.parse_args()
    teacher = HttpTeacher(args.base_url, args.model, args.api_key_file)
    count = generate(load_manifest(args.manifest), args.corpus, teacher, args.output, seed=args.seed,
                     limit_docs=args.limit_docs, windows=args.windows, workers=args.workers,
                     unanswerable=args.unanswerable, resume=args.resume)
    print(json.dumps({"examples_written": count, "output": str(args.output)}))


if __name__ == "__main__":
    main()
