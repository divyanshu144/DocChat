"""Unit tests for eval/capture_bench_prompts.py's pure logic.

No network, no tokenizer download, no LLM. The live pipeline orchestration
(_capture_one, main) is exercised manually against real Qdrant data, same bar
as eval/benchmark.py and eval/inference_benchmark.py.
"""

from unittest.mock import MagicMock

from eval.capture_bench_prompts import _count_tokens, _new_state


def _fake_tokenizer(tokens_per_char: float = 1.0):
    """A tokenizer stub whose .encode(text).ids has len == len(text) * tokens_per_char."""
    tok = MagicMock()

    def encode(text):
        enc = MagicMock()
        enc.ids = list(range(round(len(text) * tokens_per_char)))
        return enc

    tok.encode = encode
    return tok


def test_count_tokens_sums_across_messages():
    tokenizer = _fake_tokenizer(tokens_per_char=1.0)
    messages = [{"role": "system", "content": "abc"}, {"role": "user", "content": "de"}]
    assert _count_tokens(tokenizer, messages) == 5  # 3 + 2


def test_count_tokens_empty_messages_is_zero():
    tokenizer = _fake_tokenizer()
    assert _count_tokens(tokenizer, []) == 0


def test_count_tokens_uses_each_messages_own_content():
    tokenizer = _fake_tokenizer(tokens_per_char=1.0)
    messages = [{"role": "system", "content": "x" * 100}, {"role": "user", "content": "y" * 10}]
    assert _count_tokens(tokenizer, messages) == 110


def test_new_state_has_every_agent_state_field():
    """A missing field would KeyError deep inside a node, not here — this
    catches that class of bug at the source instead."""
    state = _new_state("what is the vector dimension?")
    required = {
        "query", "conversation_id", "conversation_history", "sources_to_use",
        "source_ids", "retrieved_chunks", "answer", "critic_feedback",
        "needs_replan", "iteration", "grounding_passed", "pending_rejection",
    }
    assert required <= state.keys()


def test_new_state_carries_the_given_query():
    state = _new_state("hello")
    assert state["query"] == "hello"


def test_new_state_starts_with_empty_sources_and_chunks():
    """sources_to_use and retrieved_chunks start empty -- planner and retriever
    are what populate them; a non-empty default here would mask a node that
    silently didn't run."""
    state = _new_state("q")
    assert state["sources_to_use"] == []
    assert state["retrieved_chunks"] == []
