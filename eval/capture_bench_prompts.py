#!/usr/bin/env python3
"""Part B — capture realistic DocChat-sized prompts.

Runs the real planner -> retriever -> synthesizer pipeline for each of the 8
eval queries (`eval/cases.py`) against whatever is actually ingested in
Qdrant, and records the exact messages `synthesizer_node` would send to the
LLM (system prompt with real retrieved-chunk context + conversation history,
user message) -- without making that completion call.

Interception is via patching `app.agent.nodes.synthesizer.chat_complete`, the
same pattern `tests/test_llm_temperature.py` already uses to assert what a
node sends without hitting a real API. No app code changes.

`planner_node`'s own LLM call (source selection + query rewrite) DOES run for
real -- skipping it would mean capturing prompts built from a hardcoded
sources_to_use rather than what the app would actually decide, defeating the
point of "realistic" prompts. This costs one small classification-temperature
LLM call per query against whatever LLM_PROVIDER is configured in .env.

Usage:
    python eval/capture_bench_prompts.py

Requires Qdrant reachable with real ingested chunks in source_chunks
(check with e.g. `curl localhost:6333/collections/source_chunks`)
and a working LLM_PROVIDER for the planner step.

Writes one row per query to data/bench_prompts.jsonl, OVERWRITING the file --
this is a snapshot against the current Qdrant index, not an append-only run
log (unlike eval/inference_benchmark.py's JSONL). Always exits 0; a single
query's failure is reported and skipped rather than aborting the whole run.
"""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch

# Invoked as a script (`python eval/capture_bench_prompts.py`), sys.path[0] is
# eval/, not the repo root — so `app` and `eval` are unimportable without this.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.nodes import planner as planner_module  # noqa: E402
from app.agent.nodes import retriever as retriever_module  # noqa: E402
from app.agent.nodes import synthesizer as synthesizer_module  # noqa: E402
from app.agent.state import AgentState  # noqa: E402
from eval.cases import CASES, CriticCase  # noqa: E402

_OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "bench_prompts.jsonl"
_TOKENIZER_MODEL = "Qwen/Qwen2.5-7B-Instruct"


def _load_tokenizer():
    from tokenizers import Tokenizer

    return Tokenizer.from_pretrained(_TOKENIZER_MODEL)


def _count_tokens(tokenizer, messages: list[dict]) -> int:
    """Sum of each message's own content token count.

    Not the exact chat-template token count (real serving adds role markers
    and special tokens around each message) -- a lower-bound approximation of
    the real prompt size. Good enough to size a benchmark's max_tokens /
    context budget against; not a substitute for the provider's own reported
    `prompt_tokens` when precision matters (see eval/inference_benchmark.py's
    usage_sink for that).
    """
    return sum(len(tokenizer.encode(m["content"]).ids) for m in messages)


def _new_state(query: str) -> AgentState:
    return {
        "query": query,
        "original_query": query,
        "conversation_id": "",
        "conversation_history": [],
        "sources_to_use": [],
        "source_ids": [],
        "retrieved_chunks": [],
        "answer": "",
        "critic_feedback": "",
        "needs_replan": False,
        "iteration": 0,
        "grounding_passed": False,
        "pending_rejection": None,
    }


async def _capture_one(case: CriticCase, tokenizer) -> dict:
    state = _new_state(case.query)

    planner_result = await planner_module.planner_node(state)
    state.update(planner_result)  # real sources_to_use + rewritten query

    retriever_result = await retriever_module.retriever_node(state)
    state.update(retriever_result)  # real retrieved_chunks from Qdrant

    captured: dict = {}

    async def fake_chat_complete(messages, max_tokens=1400, temperature=None):
        captured["messages"] = messages
        return "[captured, not generated]"

    with patch.object(synthesizer_module, "chat_complete", fake_chat_complete):
        await synthesizer_module.synthesizer_node(state)

    messages = captured["messages"]
    return {
        "id": case.label,
        "query": case.query,
        "rewritten_query": state["query"],
        "sources_to_use": state["sources_to_use"],
        "n_chunks": len(state["retrieved_chunks"]),
        "input_tokens": _count_tokens(tokenizer, messages),
        "messages": messages,
    }


async def main() -> None:
    print(f"Loading {_TOKENIZER_MODEL} tokenizer...")
    tokenizer = _load_tokenizer()
    _OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    print(f"\nCapturing {len(CASES)} realistic prompts against real Qdrant data\n")
    rows = []
    for case in CASES:
        try:
            row = await _capture_one(case, tokenizer)
        except Exception as exc:
            print(f"[ERROR] {case.label}: {type(exc).__name__}: {exc}")
            continue
        rows.append(row)
        print(
            f"[OK] {case.label:<32} sources={row['sources_to_use']!s:<24} "
            f"n_chunks={row['n_chunks']:<3} input_tokens={row['input_tokens']}"
        )

    with _OUT_PATH.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    print(f"\nWrote {len(rows)}/{len(CASES)} rows to {_OUT_PATH}")
    if len(rows) < len(CASES):
        print("Some queries failed — see [ERROR] lines above.")


if __name__ == "__main__":
    asyncio.run(main())
