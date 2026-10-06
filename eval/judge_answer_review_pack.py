"""Run a blinded LLM judge over the answer review pack.

Output labels are LLM-assisted, not human-verified. Rows are keyed only by
``blind_id``; the unblinding key is never read here.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Awaitable, Callable

from eval.judge_prompt import PROMPTS, build_messages, parse_labels, validate_labels

Complete = Callable[[list[dict]], Awaitable[str]]
PROVIDER_MODEL_SETTING = {"openai": "openai_chat_model", "mistral": "mistral_chat_model",
                          "groq": "chat_model"}
ANTHROPIC_DEFAULT_MODEL = "claude-opus-5-5"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
PROVIDERS = sorted([*PROVIDER_MODEL_SETTING, "anthropic"])
MAX_TOKENS = 4000  # reasoning models spend completion budget on hidden reasoning


def load_pack(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    ids = [row.get("blind_id") for row in rows]
    if not rows or any(not value for value in ids) or len(set(ids)) != len(ids):
        raise ValueError("pack must be non-empty with unique, non-empty blind_id values")
    return rows


def _read_existing(output: Path, pack_ids: set[str], judge: dict) -> set[str]:
    """Return blind_ids already judged, refusing if the file is not safely resumable."""
    done: set[str] = set()
    for number, line in enumerate(output.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise FileExistsError(f"{output}:{number} is not valid JSON ({exc}); refusing to append") from exc
        existing = row.get("judge", {})
        same = all(existing.get(key) == judge[key] for key in ("provider", "model", "prompt_sha256"))
        if row.get("blind_id") not in pack_ids or not same or row["blind_id"] in done:
            raise FileExistsError(
                f"{output}:{number} does not match this pack/judge/prompt; refusing to overwrite or mix. "
                "Use a different --output.")
        done.add(row["blind_id"])
    return done


async def judge_row(row: dict, complete: Complete, version: str = "v1") -> tuple[dict | None, str, str]:
    """Judge one row, retrying once on invalid JSON or schema failure.

    Returns (labels or None, parse_status, error message).
    """
    messages = build_messages(row, version)
    reply, error = "", ""
    for attempt in range(2):
        reply = await complete(messages)
        try:
            return validate_labels(parse_labels(reply), version), "ok", ""
        except ValueError as exc:
            error = str(exc)
        if attempt == 0:
            messages = messages + [
                {"role": "assistant", "content": reply},
                {"role": "user", "content": f"That reply was rejected ({error}). "
                                            "Return only the corrected JSON object."}]
    return None, error.split(":", 1)[0], error + " | raw: " + reply[:500]


def label_row(blind_id: str, labels: dict | None, parse_status: str, error: str, judge: dict) -> dict:
    row = {"blind_id": blind_id, "label_source": "llm_assisted", "human_verified": False,
           "judge": judge, "labels": labels, "parse_status": parse_status}
    if error:
        row["error"] = error
    return row


async def run_judge(rows: list[dict], output: Path, judge: dict, complete: Complete,
                    limit: int | None = None, temperature_applied: Callable[[], bool] | None = None,
                    only_ids: set[str] | None = None, version: str = "v1") -> dict:
    done = _read_existing(output, {row["blind_id"] for row in rows}, judge) if output.exists() else set()
    if only_ids is not None and not only_ids <= {row["blind_id"] for row in rows}:
        raise ValueError("--ids-file contains blind_ids that are not in the pack")
    todo = [row for row in rows if row["blind_id"] not in done
            and (only_ids is None or row["blind_id"] in only_ids)]
    if limit is not None:
        todo = todo[:limit]
    output.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with output.open("a") as sink:
        for row in todo:
            labels, status, error = await judge_row(row, complete, version)
            record_judge = dict(judge)
            if temperature_applied:
                applied = temperature_applied()
                record_judge["temperature_applied"] = applied
                record_judge["sampling"] = "temperature_0" if applied else "provider_default"
            sink.write(json.dumps(label_row(row["blind_id"], labels, status, error, record_judge),
                                  ensure_ascii=False) + "\n")
            sink.flush()
            written += 1
    return {"already_judged": len(done), "judged_now": written,
            "remaining": len(rows) - len(done) - written}


RETRYABLE_STATUS = {429, 500, 502, 503, 529}


async def with_retries(call: Callable[[], Awaitable[str]], attempts: int = 6, base_delay: float = 5.0) -> str:
    """Retry rate-limit and server errors with exponential backoff; re-raise anything else or the last error."""
    for attempt in range(attempts):
        try:
            return await call()
        except Exception as exc:  # noqa: BLE001 - classify by HTTP status when one is present
            response = getattr(exc, "response", None)
            status = getattr(response, "status_code", None)
            body = (getattr(response, "text", "") or "").lower()
            out_of_credit = any(marker in body for marker in (
                "insufficient_quota", "credit balance", "no credits", "tokens per day", "(tpd)"))
            if status not in RETRYABLE_STATUS or out_of_credit or attempt == attempts - 1:
                raise
            await asyncio.sleep(min(90.0, base_delay * 2 ** attempt))
    raise AssertionError("unreachable")


def _configure_provider(provider: str, model: str) -> tuple[Complete, Callable[[], bool]]:
    """Return (complete, temperature_applied) for the judge, with no silent fallbacks."""
    if provider == "anthropic":
        return _anthropic_complete(model)
    from app.core.config import settings
    from app.services import llm

    settings.llm_provider = provider
    setattr(settings, PROVIDER_MODEL_SETTING[provider], model)
    settings.fallback_llm_provider = "none"
    settings.groq_fallback_chat_model = ""

    async def complete(messages: list[dict]) -> str:
        return await with_retries(lambda: llm.chat_complete(messages, max_tokens=MAX_TOKENS, temperature=0))
    return complete, lambda: model not in llm._TEMPERATURE_UNSUPPORTED


def _anthropic_complete(model: str) -> tuple[Complete, Callable[[], bool]]:
    """Direct Messages API call (the chat facade has no Anthropic provider; this is eval-only)."""
    import httpx

    from app.core.config import settings

    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured")
    state = {"temperature": True, "served_model": None}
    headers = {"x-api-key": settings.anthropic_api_key, "anthropic-version": "2023-06-01",
               "content-type": "application/json"}

    async def complete(messages: list[dict]) -> str:
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        turns = [m for m in messages if m["role"] != "system"]
        payload = {"model": model, "max_tokens": MAX_TOKENS, "system": system, "messages": turns}
        async with httpx.AsyncClient(timeout=180) as client:
            for _ in range(2):
                if state["temperature"]:
                    payload["temperature"] = 0
                response = await client.post(ANTHROPIC_URL, headers=headers, json=payload)
                if response.status_code == 400 and "temperature" in response.text and state["temperature"]:
                    state["temperature"] = False  # remembered, and recorded as temperature_applied=false
                    payload.pop("temperature", None)
                    continue
                break
        if response.status_code >= 400:
            raise RuntimeError(f"Anthropic API {response.status_code}: {response.text[:300]}")
        data = response.json()
        state["served_model"] = data.get("model")
        return "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")

    complete.state = state
    return complete, lambda: state["temperature"]


def main(argv: list[str] | None = None) -> int:
    from app.core.config import settings

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, default=Path("reports/quality-review-pack.jsonl"))
    parser.add_argument("--output", type=Path, default=None,
                        help="Default: reports/quality-judge-labels-<prompt-version>.jsonl")
    parser.add_argument("--judge-provider", choices=PROVIDERS, default="anthropic")
    parser.add_argument("--prompt-version", choices=sorted(PROMPTS), default="v2")
    parser.add_argument("--judge-model", default=None,
                        help="Defaults to the provider's configured chat model. Must not be a Qwen model.")
    parser.add_argument("--limit", type=int, help="Judge at most this many unjudged rows")
    parser.add_argument("--ids-file", type=Path,
                        help="JSON list of blind_ids to judge (a targeted subset); others are skipped")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the exact judge inputs and exit; no API calls, no output written")
    args = parser.parse_args(argv)

    args.output = args.output or Path(f"reports/quality-judge-labels-{args.prompt_version}.jsonl")
    model = args.judge_model or (ANTHROPIC_DEFAULT_MODEL if args.judge_provider == "anthropic"
                                 else getattr(settings, PROVIDER_MODEL_SETTING[args.judge_provider]))
    if "qwen" in model.lower():
        parser.error("judge must not be a Qwen model (the evaluated family)")
    rows = load_pack(args.pack)
    judge = {"provider": args.judge_provider, "model": model, "prompt_version": args.prompt_version,
             "prompt_sha256": PROMPTS[args.prompt_version][1], "temperature_requested": 0}

    if args.dry_run:
        for row in rows[: args.limit or len(rows)]:
            print(json.dumps({"blind_id": row["blind_id"], "judge": judge,
                              "messages": build_messages(row, args.prompt_version)}, ensure_ascii=False, indent=2))
        print(f"[dry-run] {len(rows[: args.limit or len(rows)])} rows; no API calls made", file=sys.stderr)
        return 0

    complete, applied = _configure_provider(args.judge_provider, model)
    only_ids = set(json.loads(args.ids_file.read_text())) if args.ids_file else None
    summary = asyncio.run(run_judge(rows, args.output, judge, complete, args.limit, applied, only_ids,
                                    args.prompt_version))
    served = getattr(complete, "state", {}).get("served_model")
    if served:
        summary["served_model"] = served
    print(json.dumps({**summary, "output": str(args.output), "judge": judge}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
