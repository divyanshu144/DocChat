"""Questions the supplied context cannot answer: abstention training examples and held-out negative controls.

The first version asked the teacher for questions "the excerpt does not answer". Retrieval then searches the whole
document, which often does answer them, so most of those examples were real answers and the held-out negative controls
were not negative. Here a question is borrowed from a different document of the same split and asked against this
document, and a strict teacher check must say the retrieved context cannot answer it. Anything unclear counts as
answerable and is dropped.

For the training example the teacher is given a one-line hint to write a short abstention. The hint is not stored: the
example keeps the exact serving prompt, so the model learns to abstain from the context and the question alone.
"""
from __future__ import annotations

import argparse
import json
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from finetune.corpus import read_points, source_id
from finetune.fetch_sources import load_manifest
from finetune.retrieval import CorpusIndex, build_messages
from finetune.schema import SourceDoc, TrainingExample
from finetune.teacher import Teacher, parse_json_object

CHECK_PROMPT = """\
Decide whether the passages below contain the facts needed to answer the question.

Question: {question}

Passages:
{context}

Be strict. Related background, the same general topic or a similar rule is NOT enough: the passages must state what the
question asks for. Reply with only one JSON object: {{"answerable": true}} or {{"answerable": false}}.
"""

ABSTAIN_HINT = (
    "\n\n(Instruction for this test only: the sources above do not answer this question. Reply in one or two plain "
    "sentences saying that the provided sources do not contain the information needed to answer it. You may say what "
    "the sources do cover. Do not cite sources, do not write a Sources section, and use no Markdown.)"
)


def context_can_answer(teacher: Teacher, question: str, chunks: list[dict]) -> bool:
    """True unless the teacher says explicitly that the passages cannot answer the question."""
    context = "\n\n".join(chunk["text"] for chunk in chunks)
    reply = teacher.complete([{"role": "user", "content": CHECK_PROMPT.format(question=question, context=context)}],
                             max_tokens=20, temperature=0.0)
    return (parse_json_object(reply) or {}).get("answerable") is not False


def borrowed_candidates(pool: dict[str, list[str]], doc: SourceDoc, docs: list[SourceDoc], rng: random.Random,
                        count: int) -> list[str]:
    """Questions written about other documents of the same split, in a reproducible random order."""
    candidates = sorted({q for d in docs if d.id != doc.id and d.split == doc.split for q in pool.get(d.id, [])})
    rng.shuffle(candidates)
    return candidates[:count]


def unanswerable_for(doc: SourceDoc, index, candidates: list[str], teacher: Teacher, wanted: int,
                     on_error: Callable[[Exception], None] | None = None) -> list[tuple[str, list[dict]]]:
    """Up to `wanted` (question, retrieved chunks) pairs where context was retrieved and cannot answer the question."""
    sid = source_id(doc)
    found: list[tuple[str, list[dict]]] = []
    for question in candidates:
        if len(found) >= wanted:
            break
        chunks = index.retrieve(question, [sid])
        if not chunks:
            continue  # serving answers this case without the model
        try:
            if context_can_answer(teacher, question, chunks):
                continue
        except RuntimeError as exc:
            if on_error is None:
                raise
            on_error(exc)
            continue
        found.append((question, chunks))
    return found


def abstention_examples(doc: SourceDoc, docs: list[SourceDoc], index, pool: dict[str, list[str]], teacher: Teacher,
                        rng: random.Random, wanted: int = 3, attempts: int = 12,
                        on_error: Callable[[Exception], None] | None = None) -> list[TrainingExample]:
    out: list[TrainingExample] = []
    candidates = borrowed_candidates(pool, doc, docs, rng, attempts)
    for question, chunks in unanswerable_for(doc, index, candidates, teacher, wanted, on_error):
        messages = build_messages(question, chunks)
        hinted = [messages[0], {"role": "user", "content": question + ABSTAIN_HINT}]
        try:
            answer = teacher.complete(hinted, max_tokens=300, temperature=0.2).strip()
        except RuntimeError as exc:
            if on_error is None:
                raise
            on_error(exc)
            continue
        messages.append({"role": "assistant", "content": answer})
        out.append(TrainingExample(id=TrainingExample.make_id(messages), split=doc.split, kind="abstain",
                                   doc_ids=[doc.id], messages=messages, teacher=teacher.name))
    return out


def question_pool(examples_path: Path) -> dict[str, list[str]]:
    """Answerable single-document questions from already validated examples, by document."""
    pool: dict[str, list[str]] = {}
    for line in examples_path.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            if row["kind"] == "answerable" and len(row["doc_ids"]) == 1:
                pool.setdefault(row["doc_ids"][0], []).append(row["messages"][1]["content"])
    return pool


def main() -> None:
    from app.services.embedder import get_embedder
    from finetune.generate_examples import _LockedIndex
    from finetune.teacher import HttpTeacher
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("finetune/manifest.json"))
    parser.add_argument("--corpus", type=Path, default=Path("data/finetune/corpus"))
    parser.add_argument("--examples", type=Path, default=Path("data/finetune/examples.jsonl"),
                        help="validated examples; their questions are borrowed across documents")
    parser.add_argument("--output", type=Path, default=Path("data/finetune/abstentions.raw.jsonl"))
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-key-file", type=Path)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--wanted", type=int, default=3, help="abstention examples per document")
    parser.add_argument("--attempts", type=int, default=12, help="borrowed questions tried per document")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    manifest = load_manifest(args.manifest)
    docs = [d for d in manifest.documents if d.split in {"train", "validation"}]
    embedder = get_embedder()
    if embedder is None:
        raise SystemExit("fastembed failed to load")
    index = _LockedIndex(CorpusIndex([p for d in docs for p in read_points(args.corpus / f"{d.id}.points.jsonl")],
                                     lambda q: embedder.embed_query(q).tolist()))
    teacher = HttpTeacher(args.base_url, args.model, args.api_key_file)
    pool = question_pool(args.examples)
    failures: list[Exception] = []

    def one(doc: SourceDoc) -> list[TrainingExample]:
        return abstention_examples(doc, docs, index, pool, teacher, random.Random(f"{args.seed}:{doc.id}"),
                                   args.wanted, args.attempts, failures.append)

    with ThreadPoolExecutor(max_workers=args.workers) as workers:
        results = list(workers.map(one, docs))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rows = [example for examples in results for example in examples]
    args.output.write_text("".join(example.model_dump_json() + "\n" for example in rows))
    print(json.dumps({"abstentions_written": len(rows), "teacher_failures": len(failures), "output": str(args.output)}))


if __name__ == "__main__":
    main()
