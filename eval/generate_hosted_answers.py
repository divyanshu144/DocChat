"""Generate answers for a workload with the app's hosted provider (the production default, Groq `openai/gpt-oss-120b`).

Writes the same JSONL rows as `generate_answer_samples.py`, so the review-pack builder, judge and audits read it
unchanged. The call goes through `app.services.llm.chat_complete`, so the key comes from settings and is never printed.
Failed cases are kept in the file with `status: error`, so they stay in the denominator.

Usage:  python -m eval.generate_hosted_answers --prompts data/finetune/heldout-v2-workload.json --output answers.jsonl
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.services import llm
from eval.workloads import load_workloads


async def generate(prompts_path: Path, output_path: Path, *, max_tokens: int, concurrency: int) -> None:
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite {output_path}")
    workloads = load_workloads(prompts_path, "replay")
    label = f"{settings.llm_provider}/{settings.chat_model}"
    gate = asyncio.Semaphore(concurrency)

    async def one(case) -> dict:
        row = {"schema_version": 1, "case_id": case.id, "query": case.query,
               "messages": [m.model_dump() for m in case.messages], "model": label,
               "started_at": datetime.now(timezone.utc).isoformat(), "max_tokens": max_tokens, "temperature": 0.0,
               "category": case.category, "split": case.split, "expected_evidence": case.expected_evidence,
               "expected_facts": case.expected_facts, "corpus_sha256": workloads.corpus_sha256}
        started = time.perf_counter()
        async with gate:
            try:
                row.update(answer=await llm.chat_complete(row["messages"], max_tokens=max_tokens, temperature=0.0),
                           status="ok")
            except Exception as exc:  # keep failures in the denominator
                row.update(status="error", error=f"{type(exc).__name__}: {str(exc)[:300]}")
        row["latency_s"] = time.perf_counter() - started
        return row

    rows = await asyncio.gather(*(one(case) for case in workloads.cases))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as target:
        for row in rows:  # workload order, whatever order the calls finished in
            target.write(json.dumps(row, ensure_ascii=False) + "\n")
    await llm.close_llm_clients()
    errors = sum(row["status"] == "error" for row in rows)
    print(json.dumps({"cases": len(rows), "errors": errors, "model": label, "output": str(output_path)}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-tokens", type=int, default=1400)
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()
    asyncio.run(generate(args.prompts, args.output, max_tokens=args.max_tokens, concurrency=args.concurrency))


if __name__ == "__main__":
    main()
