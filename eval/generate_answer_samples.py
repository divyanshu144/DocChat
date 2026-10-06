"""Generate and retain answer/evidence pairs from captured DocChat prompts."""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.core.config import settings
from eval.workloads import load_workloads


def generate(prompts_path: Path, output_path: Path, *, model: str, max_tokens: int) -> None:
    if not settings.local_base_url:
        raise ValueError("Set LOCAL_BASE_URL to the OpenAI-compatible inference endpoint")
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite {output_path}")
    headers = {"Authorization": f"Bearer {settings.local_api_key}"} if settings.local_api_key else {}
    client = httpx.Client(headers=headers, timeout=settings.inference_read_timeout_s)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    raw = prompts_path.read_text()
    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError:
        manifest = None
    if isinstance(manifest, dict) and "cases" in manifest:
        workloads = load_workloads(prompts_path, "replay")
        cases = [case.model_dump() for case in workloads.cases]
        corpus_sha256 = workloads.corpus_sha256
    else:
        cases = [json.loads(line) for line in raw.splitlines() if line.strip()]
        corpus_sha256 = None
    with output_path.open("w") as target:
        for case in cases:
            started = time.perf_counter()
            case_max_tokens = case.get("max_tokens", max_tokens)
            row = {
                "schema_version": 1,
                "case_id": case.get("id", case.get("case_id")),
                "query": case.get("query", ""),
                "messages": case["messages"],
                "model": model,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "max_tokens": case_max_tokens,
                "temperature": 0.0,
            }
            if case.get("category"):
                row["category"] = case["category"]
            if case.get("split"):
                row["split"] = case["split"]
            if case.get("expected_evidence") is not None:
                row["expected_evidence"] = case["expected_evidence"]
            if case.get("expected_facts") is not None:
                row["expected_facts"] = case["expected_facts"]
            if corpus_sha256:
                row["corpus_sha256"] = corpus_sha256
            try:
                response = client.post(f"{settings.local_base_url.rstrip('/')}/chat/completions", json={
                    "model": model,
                    "messages": case["messages"],
                    "max_tokens": case_max_tokens,
                    "temperature": 0.0,
                })
                response.raise_for_status()
                payload = response.json()
                row.update(
                    answer=payload["choices"][0]["message"].get("content") or "",
                    finish_reason=payload["choices"][0].get("finish_reason"),
                    usage=payload.get("usage"),
                    status="ok",
                )
            except Exception as exc:  # retain failed cases in the denominator
                row.update(status="error", error=f"{type(exc).__name__}: {str(exc)[:300]}")
            row["latency_s"] = time.perf_counter() - started
            target.write(json.dumps(row, ensure_ascii=False) + "\n")
            target.flush()
            print(json.dumps({"case_id": row["case_id"], "status": row["status"],
                              "latency_s": round(row["latency_s"], 3)}), flush=True)
    client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompts", type=Path, default=Path("data/bench_prompts.jsonl"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="Qwen2.5-7B-Instruct")
    parser.add_argument("--max-tokens", type=int, default=1400)
    args = parser.parse_args()
    generate(args.prompts, args.output, model=args.model, max_tokens=args.max_tokens)


if __name__ == "__main__":
    main()
