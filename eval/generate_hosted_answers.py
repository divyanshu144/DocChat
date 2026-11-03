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
from typing import Awaitable, Callable

from app.core.config import settings
from app.services import llm
from eval.workloads import load_workloads


BACKOFF_S = (5, 15, 30, 60, 60)


class DailyLimitReached(Exception):
    """The provider's per-day token allowance is spent; waiting a minute will not help."""


async def _with_backoff(call: Callable[[], Awaitable[str]], sleep=asyncio.sleep) -> str:
    """Retry rate limits and server errors with a pause. Anything else (a bad key, a bad request) is raised at once."""
    for pause in BACKOFF_S:
        try:
            return await call()
        except Exception as exc:
            if "tokens per day" in str(getattr(getattr(exc, "response", None), "text", "")).lower():
                raise DailyLimitReached(str(exc)[:200]) from exc
            if not llm._is_retryable_llm_error(exc):
                raise
            await sleep(pause)
    return await call()


def _read_rows(path: Path) -> dict[str, dict]:
    """Latest row per case id from a (possibly partial) output file."""
    rows: dict[str, dict] = {}
    for line in path.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            rows[row["case_id"]] = row
    return rows


async def generate(prompts_path: Path, output_path: Path, *, max_tokens: int, concurrency: int, sleep=asyncio.sleep,
                   resume: bool = False) -> dict:
    """Write one row per case as it finishes. With `resume`, cases already answered are kept and only the rest are run.

    A free tier can have a daily token allowance smaller than the workload. When it runs out the run stops without writing
    error rows for the cases it never tried, so `--resume` after the reset carries on where it stopped.
    """
    if output_path.exists() and not resume:
        raise FileExistsError(f"Refusing to overwrite {output_path} (use --resume to continue it)")
    # These rows are labelled with one provider and model, so a failure must not be answered by another one.
    settings.llm_provider, settings.fallback_llm_provider = "groq", "none"
    workloads = load_workloads(prompts_path, "replay")
    label = f"{settings.llm_provider}/{settings.chat_model}"
    gate = asyncio.Semaphore(concurrency)
    done = _read_rows(output_path) if resume and output_path.exists() else {}
    kept = {case_id: row for case_id, row in done.items() if row.get("status") == "ok"}
    out_of_tokens = asyncio.Event()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    target = output_path.open("w" if not resume else "a")

    async def one(case) -> dict:
        row = {"schema_version": 1, "case_id": case.id, "query": case.query,
               "messages": [m.model_dump() for m in case.messages], "model": label,
               "started_at": datetime.now(timezone.utc).isoformat(), "max_tokens": max_tokens, "temperature": 0.0,
               "category": case.category, "split": case.split, "expected_evidence": case.expected_evidence,
               "expected_facts": case.expected_facts, "corpus_sha256": workloads.corpus_sha256}
        started = time.perf_counter()
        async with gate:
            if out_of_tokens.is_set():
                return None  # never tried: leave no row, so a later --resume runs it
            try:
                row.update(answer=await _with_backoff(lambda: llm.chat_complete(
                    row["messages"], max_tokens=max_tokens, temperature=0.0), sleep), status="ok")
            except DailyLimitReached:
                out_of_tokens.set()
                return None
            except Exception as exc:  # keep failures in the denominator
                row.update(status="error", error=f"{type(exc).__name__}: {str(exc)[:300]}")
        row["latency_s"] = time.perf_counter() - started
        target.write(json.dumps(row, ensure_ascii=False) + "\n")
        target.flush()
        return row

    todo = [case for case in workloads.cases if case.id not in kept]
    new = {row["case_id"]: row for row in await asyncio.gather(*(one(case) for case in todo)) if row}
    target.close()
    final = {**kept, **new}
    with output_path.open("w") as rewritten:  # tidy rewrite in workload order, one row per case
        for case in workloads.cases:
            if case.id in final:
                rewritten.write(json.dumps(final[case.id], ensure_ascii=False) + "\n")
    await llm.close_llm_clients()
    summary = {"cases": len(workloads.cases), "answered": len(final), "errors": sum(r["status"] == "error" for r in final.values()),
               "not_tried_daily_limit": len(workloads.cases) - len(final), "model": label, "output": str(output_path)}
    print(json.dumps(summary))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-tokens", type=int, default=1400)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--resume", action="store_true", help="keep answered cases in --output and run only the rest")
    args = parser.parse_args()
    asyncio.run(generate(args.prompts, args.output, max_tokens=args.max_tokens, concurrency=args.concurrency, resume=args.resume))


if __name__ == "__main__":
    main()
