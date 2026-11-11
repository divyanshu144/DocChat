"""Build the larger retrieval evaluation set (corpus + labeled questions).

Two subcommands, both writing only to a *separate* Qdrant collection (never `source_chunks`):

  corpus  Ingest the pages in PAGES into the eval collection, copy the existing golden-set chunks in as
          distractors, and write a text snapshot (eval/retrieval_corpus_v2.json) so the labels survive
          Wikipedia edits. `corpus --from-snapshot` rebuilds the collection from that snapshot offline.
  label   Sample chunks, have the LLM write one question per chunk (alternating exact-term / paraphrase
          strata), validate each question is answerable from the chunk alone, and write
          eval/retrieval_golden_v2.json in the schema `eval.retrieval_eval` already reads.

Run with QDRANT_SOURCE_COLLECTION=eval_corpus_v2 so the ingesters write to the eval collection:

  QDRANT_SOURCE_COLLECTION=eval_corpus_v2 python -m eval.build_retrieval_set_v2 corpus
  QDRANT_SOURCE_COLLECTION=eval_corpus_v2 python -m eval.build_retrieval_set_v2 label
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "eval/retrieval_corpus_v2.json"
GOLDEN_V2 = ROOT / "eval/retrieval_golden_v2.json"
GOLDEN_V1 = ROOT / "eval/retrieval_golden.json"
EVAL_COLLECTION = "eval_corpus_v2"
LEGACY_COPY_FROM = "source_chunks_hybrid"  # holds the 17 original chunks with dense + BM25 vectors

# Mixed on purpose: technical and non-technical, number- and name-heavy, so neither lexical nor semantic
# retrieval gets a corpus built for it.
PAGES = [
    "https://en.wikipedia.org/wiki/Okapi_BM25",
    "https://en.wikipedia.org/wiki/PostgreSQL",
    "https://en.wikipedia.org/wiki/Kubernetes",
    "https://en.wikipedia.org/wiki/Transmission_Control_Protocol",
    "https://en.wikipedia.org/wiki/Git",
    "https://en.wikipedia.org/wiki/Apollo_11",
    "https://en.wikipedia.org/wiki/Marie_Curie",
    "https://en.wikipedia.org/wiki/Mount_Everest",
    "https://en.wikipedia.org/wiki/Photosynthesis",
    "https://en.wikipedia.org/wiki/Great_Barrier_Reef",
    "https://en.wikipedia.org/wiki/Black_Death",
    "https://en.wikipedia.org/wiki/Euro",
]

QUESTIONS_PER_PAGE = 10
MIN_CHUNK_CHARS = 400
QUOTE_MIN_CHARS = 20
MAX_RELEVANT_CHUNKS = 3  # a quote found in many chunks is boilerplate, not evidence for one passage

STRATA = {
    "exact_term": (
        "Write a question that a user could only answer by finding THIS passage because it hinges on a specific "
        "name, number, date, identifier or technical term that appears in the passage. Use that exact term in the question."
    ),
    "paraphrase": (
        "Write a question about the passage's content using DIFFERENT words than the passage: do not reuse its "
        "distinctive nouns, numbers or names; describe the idea in your own words (synonyms, general descriptions)."
    ),
}


def _prompt(stratum: str, text: str) -> list[dict]:
    return [
        {"role": "system", "content": "You write evaluation questions for a document search system. Reply with JSON only."},
        {"role": "user", "content": (
            f"{STRATA[stratum]}\n\nRules:\n"
            "- The question must be answerable from the passage alone and be specific enough that a different, "
            "unrelated passage would not answer it. Name the topic (e.g. the article subject) in the question.\n"
            "- Also give `quote`: a verbatim span of 20-120 characters copied exactly from the passage that contains the answer.\n"
            '- Reply as {"question": "...", "quote": "..."}.\n\n'
            f"Passage:\n{text}"
        )},
    ]


def _validation_prompt(question: str, text: str) -> list[dict]:
    return [
        {"role": "system", "content": "You check evaluation questions. Reply with JSON only."},
        {"role": "user", "content": (
            'Can the question be fully answered using only the passage? Reply as {"answerable": true|false}.\n\n'
            f"Question: {question}\n\nPassage:\n{text}"
        )},
    ]


def _parse_json(raw: str) -> dict | None:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        value = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def relevant_chunks_for_quote(quote: str, chunks: list[dict]) -> list[str]:
    """Every chunk containing the verbatim quote is relevant (chunk overlap puts some facts in two chunks)."""
    return [chunk["id"] for chunk in chunks if quote in chunk["text"]]


def accept_question(question: str, quote: str, chunk_text: str) -> str | None:
    """Reason to reject a generated question, or None to accept it."""
    if not question or not question.strip().endswith("?"):
        return "not a question"
    if len(quote) < QUOTE_MIN_CHARS:
        return "quote too short"
    if quote not in chunk_text:
        return "quote not verbatim in chunk"
    return None


def content_overlap(question: str, chunk_text: str) -> float:
    """Share of the question's content words that also occur in the chunk: how much lexical help the question gives BM25."""
    from eval.retrieval_eval import _tokens

    stop = {"the", "a", "an", "of", "in", "on", "to", "and", "or", "is", "are", "was", "were", "what", "which", "who",
            "how", "why", "when", "where", "does", "did", "do", "for", "by", "with", "as", "at", "from", "that", "this",
            "it", "its", "be", "according"}
    words = [w for w in _tokens(question) if w not in stop]
    if not words:
        return 0.0
    chunk_words = set(_tokens(chunk_text))
    return sum(w in chunk_words for w in words) / len(words)


def _scroll_all(client, collection: str, with_vectors: bool = False) -> list:
    points, offset = [], None
    while True:
        batch, offset = client.scroll(collection, limit=200, offset=offset, with_payload=True, with_vectors=with_vectors)
        points.extend(batch)
        if offset is None:
            return points


def build_corpus(from_snapshot: bool) -> None:
    from qdrant_client import models

    from app.core.qdrant import get_qdrant_client, get_qdrant_collection
    from app.services.embedder import get_embedder
    from app.services.ingestion.storage import point_vector

    client = get_qdrant_client()
    if client.collection_exists(EVAL_COLLECTION):
        client.delete_collection(EVAL_COLLECTION)
    get_qdrant_collection(EVAL_COLLECTION, sparse=True)

    if from_snapshot:
        rows = json.loads(SNAPSHOT.read_text())["chunks"]
        embedder = get_embedder()
        dense = list(embedder.embed([row["text"] for row in rows]))
        sparse = embedder.embed_sparse_documents([row["text"] for row in rows])
        for start in range(0, len(rows), 64):
            client.upsert(EVAL_COLLECTION, points=[
                models.PointStruct(id=row["id"], payload={**row["payload"], "text": row["text"]},
                                   vector=point_vector(vec, sp))
                for row, vec, sp in zip(rows[start:start + 64], dense[start:start + 64], sparse[start:start + 64], strict=True)])
        print(f"rebuilt {len(rows)} chunks from {SNAPSHOT.name}")
        return

    from app.services.ingestion.web import COLLECTION, ingest_web

    if COLLECTION != EVAL_COLLECTION:
        raise SystemExit(f"Refusing to ingest into '{COLLECTION}'. Run with QDRANT_SOURCE_COLLECTION={EVAL_COLLECTION}.")

    async def ingest_all() -> None:
        for url in PAGES:
            source_id = await ingest_web(url)
            print(f"ingested {url} -> {source_id[:8]}")

    asyncio.run(ingest_all())
    legacy = _scroll_all(client, LEGACY_COPY_FROM, with_vectors=True)
    client.upsert(EVAL_COLLECTION, points=[models.PointStruct(id=p.id, payload=p.payload, vector=p.vector) for p in legacy])
    print(f"copied {len(legacy)} original chunks from {LEGACY_COPY_FROM} as distractors")

    points = _scroll_all(client, EVAL_COLLECTION)
    rows = [{"id": str(p.id), "text": p.payload["text"], "payload": {k: v for k, v in p.payload.items() if k != "text"}}
            for p in sorted(points, key=lambda p: (p.payload.get("source_id", ""), p.payload.get("chunk_index", 0)))]
    SNAPSHOT.write_text(json.dumps({"description": "Text snapshot of the v2 retrieval-eval corpus; rebuild with "
                                    "`corpus --from-snapshot`.", "chunks": rows}, indent=1))
    print(f"snapshot: {len(rows)} chunks -> {SNAPSHOT}")


async def _ask(messages: list[dict]) -> str:
    from app.services.llm import chat_complete

    for attempt in range(4):
        try:
            return await chat_complete(messages, max_tokens=2000, temperature=0)
        except Exception:  # provider rate limits / transient errors: back off and retry
            if attempt == 3:
                raise
            await asyncio.sleep(2 ** attempt * 2)
    return ""


async def label(seed: int) -> None:
    rows = json.loads(SNAPSHOT.read_text())["chunks"]
    legacy_ids = {c["relevant_ids"][0] for c in json.loads(GOLDEN_V1.read_text())["cases"]}
    legacy_source_ids = {r["payload"]["source_id"] for r in rows if r["id"] in legacy_ids}
    by_source: dict[str, list[dict]] = {}
    for row in rows:
        by_source.setdefault(row["payload"]["source_id"], []).append(row)

    rng = random.Random(seed)
    cases, rejected, stratum_cycle = [], {}, 0
    for source_id, chunks in sorted(by_source.items()):
        if source_id in legacy_source_ids:
            continue  # the original sources already have their own hand-reviewed questions
        eligible = [c for c in chunks if len(c["text"]) >= MIN_CHUNK_CHARS]
        for chunk in rng.sample(eligible, min(QUESTIONS_PER_PAGE, len(eligible))):
            stratum = list(STRATA)[stratum_cycle % len(STRATA)]
            stratum_cycle += 1
            parsed = _parse_json(await _ask(_prompt(stratum, chunk["text"])))
            question, quote = (parsed or {}).get("question", ""), (parsed or {}).get("quote", "")
            reason = accept_question(question, quote, chunk["text"])
            if reason is None and len(relevant_chunks_for_quote(quote, rows)) > MAX_RELEVANT_CHUNKS:
                reason = "quote appears in too many chunks"
            if reason is None:
                verdict = _parse_json(await _ask(_validation_prompt(question, chunk["text"])))
                if not (verdict or {}).get("answerable"):
                    reason = "validator: not answerable from the chunk"
            if reason:
                rejected[reason] = rejected.get(reason, 0) + 1
                continue
            cases.append({
                "id": f"v2-{len(cases) + 1:03d}", "stratum": stratum, "query": question.strip(),
                "relevant_ids": relevant_chunks_for_quote(quote, rows),
                "evidence": [{"point_id": c["id"], "quote": quote} for c in rows if quote in c["text"]],
                "expected_sources": [{"source_id": chunk["payload"]["source_id"], "source_type": "web",
                                      "chunk_index": chunk["payload"].get("chunk_index")}],
                "lexical_overlap": round(content_overlap(question, chunk["text"]), 3),
            })
        print(f"{chunks[0]['payload'].get('title', source_id)[:50]:50s} cases so far: {len(cases)}")

    v1 = json.loads(GOLDEN_V1.read_text())["cases"]
    for case in v1:
        case.setdefault("stratum", "original_24")
    GOLDEN_V2.write_text(json.dumps({
        "description": f"{len(v1)} original hand-reviewed questions plus {len(cases)} LLM-written, validated questions over "
                       f"{len(rows)} chunks ({len(by_source)} sources).",
        "annotation": "Original 24: single annotator. New questions: written by an LLM from one sampled chunk each "
                      "(alternating exact_term / paraphrase), gated on a verbatim evidence quote and an answerable-from-chunk "
                      "check; every chunk containing the quote is labelled relevant. Not independently audited; "
                      "`lexical_overlap` records how many question words appear in the gold chunk.",
        "rejected": rejected,
        "cases": v1 + cases,
    }, indent=1))
    print(f"wrote {len(v1) + len(cases)} cases ({len(cases)} new); rejected: {rejected} -> {GOLDEN_V2}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    corpus = sub.add_parser("corpus")
    corpus.add_argument("--from-snapshot", action="store_true")
    lab = sub.add_parser("label")
    lab.add_argument("--seed", type=int, default=20261111)
    args = parser.parse_args()
    if args.command == "corpus":
        build_corpus(args.from_snapshot)
    else:
        asyncio.run(label(args.seed))


if __name__ == "__main__":
    main()
