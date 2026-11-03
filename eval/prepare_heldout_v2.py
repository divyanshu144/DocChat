#!/usr/bin/env python3
"""Build the larger held-out answer-quality workload (heldout-v2) from the held-out documents only.

The existing held-out set has 16 distinct questions, which cannot separate two models. This builds about 100 from new
open-licence documents that are never used for training, in the same `Workloads` format the rest of the harness reads
(`generate_answer_samples.py`, `build_answer_review_pack.py`, the judge). Context is retrieved with the app's own
retriever logic and the prompt is the real synthesizer prompt. Questions are written by a teacher model and are
LLM-generated; the report must say so.

Mix (per held-out document unless noted): 4 document questions, 1 summary (first 8 docs), 1 long-context (first 8),
1 negative control (a question about another held-out document that the teacher confirms the context cannot answer), plus one comparison per pair of documents (first 8 pairs).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

from eval.workloads import Message, WorkloadCase, Workloads
from finetune.corpus import read_points, source_id
from finetune.fetch_sources import load_manifest
from finetune.abstentions import borrowed_candidates, unanswerable_for
from finetune.questions import ask_questions, pick_windows
from finetune.retrieval import CorpusIndex, build_messages
from finetune.schema import SourceDoc
from finetune.teacher import Teacher

MAX_TOKENS = {"document_qa": 300, "summarisation": 550, "long_context": 800, "multi_document": 650, "negative_control": 250}
BROAD_PROMPT = ("Write one broad question about the document below that can only be answered well by combining several of its "
                "sections (for example who it applies to, the main steps, and the exceptions). Do not mention 'the document'; "
                "name the subject. Reply with only the question.\n\nDocument title: {title}\n\nOpening text:\n{opening}")


def corpus_fingerprint(index: CorpusIndex, docs: list[SourceDoc]) -> str:
    digest = hashlib.sha256()
    for doc in sorted(docs, key=lambda d: d.id):
        for chunk_id in index.chunk_ids_in_order(source_id(doc)):
            digest.update(chunk_id.encode() + hashlib.sha256(index.text(chunk_id).encode()).digest())
    return digest.hexdigest()


def _case(case_id, category, query, scope, index, expected_evidence, expected_facts=None):
    chunks = index.retrieve(query, scope)
    if not chunks:
        return None
    messages = [Message(**m) for m in build_messages(query, chunks)]
    retrieved = [c["id"] for c in chunks]
    return WorkloadCase(id=case_id, split="held_out", category=category, query=query, source_ids=scope, messages=messages,
                        max_tokens=MAX_TOKENS[category], expected_evidence=expected_evidence,
                        expected_facts=expected_facts or [], evidence_retrieved=[e for e in expected_evidence if e in retrieved])


def build_cases(docs: list[SourceDoc], index: CorpusIndex, teacher: Teacher, rng: random.Random,
                qa_windows: int = 2, broad_docs: int = 8, pairs: int = 8, negative_attempts: int = 10) -> list[WorkloadCase]:
    cases: list[WorkloadCase] = []
    asked: dict[str, list[str]] = {}
    for position, doc in enumerate(docs):
        sid = source_id(doc)
        ids = index.chunk_ids_in_order(sid)
        texts = {i: index.text(i) for i in ids}
        windows = pick_windows(ids, texts, qa_windows + 1, rng)
        count = 0
        for window in windows[:qa_windows]:
            answerable, _ = ask_questions(teacher, window, answerable=2, unanswerable=0)
            for item in answerable:
                count += 1
                case = _case(f"v2-qa-{doc.id}-{count}", "document_qa", item["question"], [sid], index, window.chunk_ids, item["facts"])
                if case and case.evidence_retrieved:  # keep only questions whose source passage was actually retrieved
                    cases.append(case)
                    asked.setdefault(doc.id, []).append(item["question"])
        if position < broad_docs:
            summary = f"Summarise the main points of '{doc.title}': what it covers, who it applies to, the key rules and any exceptions."
            for case in [_case(f"v2-summary-{doc.id}", "summarisation", summary, [sid], index, ids)]:
                if case:
                    cases.append(case)
            broad = teacher.complete([{"role": "user", "content": BROAD_PROMPT.format(
                title=doc.title, opening="\n\n".join(texts[i] for i in ids[:3])[:3000])}], max_tokens=120, temperature=0.4).strip()
            if broad.endswith("?") and len(broad) < 400:
                case = _case(f"v2-long-{doc.id}", "long_context", broad, [sid], index, ids)
                if case:
                    cases.append(case)
    # Negative controls: a question written about another held-out document, asked against this one, kept only when the
    # teacher confirms the retrieved context cannot answer it. (Questions the teacher wrote as "not answered by this
    # excerpt" were often answered elsewhere in the same document, so they were not negative.)
    for doc in docs:
        sid = source_id(doc)
        candidates = borrowed_candidates(asked, doc, docs, rng, negative_attempts)
        for question, _ in unanswerable_for(doc, index, candidates, teacher, wanted=1):
            case = _case(f"v2-negative-{doc.id}", "negative_control", question, [sid], index, [])
            if case:
                cases.append(case)
    for a, b in zip(docs[:pairs], docs[1:pairs + 1], strict=False):
        query = f"Compare the purpose and key information in '{a.title}' and '{b.title}'."
        case = _case(f"v2-multi-{a.id}-{b.id}"[:128], "multi_document", query, [source_id(a), source_id(b)], index,
                     index.chunk_ids_in_order(source_id(a)) + index.chunk_ids_in_order(source_id(b)))
        if case:
            cases.append(case)
    return cases


def main() -> None:
    from app.services.embedder import get_embedder
    from finetune.teacher import HttpTeacher
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("finetune/manifest.json"))
    parser.add_argument("--corpus", type=Path, default=Path("data/finetune/corpus"))
    parser.add_argument("--output", type=Path, default=Path("data/finetune/heldout-v2-workload.json"))
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-key-file", type=Path)
    parser.add_argument("--seed", type=int, default=29)
    args = parser.parse_args()
    manifest = load_manifest(args.manifest)
    docs = manifest.by_split("heldout")
    embedder = get_embedder()
    if embedder is None:
        raise SystemExit("fastembed failed to load")
    index = CorpusIndex([p for d in docs for p in read_points(args.corpus / f"{d.id}.points.jsonl")],
                        lambda q: embedder.embed_query(q).tolist())
    teacher = HttpTeacher(args.base_url, args.model, args.api_key_file)
    cases = build_cases(docs, index, teacher, random.Random(args.seed))
    workloads = Workloads(corpus_sha256=corpus_fingerprint(index, docs), cases=cases)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(workloads.model_dump_json(indent=1))
    by_category: dict[str, int] = {}
    for case in cases:
        by_category[case.category] = by_category.get(case.category, 0) + 1
    print(json.dumps({"cases": len(cases), "by_category": by_category, "fingerprint": workloads.fingerprint(),
                      "output": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
