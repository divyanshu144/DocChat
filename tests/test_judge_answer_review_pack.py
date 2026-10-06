import asyncio
import json
from pathlib import Path

import pytest

from eval.judge_answer_review_pack import load_pack, run_judge
from eval.judge_prompt import JUDGE_PROMPT_VERSION, PROMPT_SHA256

PACK = Path("reports/quality-review-pack.jsonl")
JUDGE = {"provider": "openai", "model": "judge-x", "prompt_version": JUDGE_PROMPT_VERSION,
         "prompt_sha256": PROMPT_SHA256, "temperature_requested": 0}
GOOD = json.dumps({"answer_correct": "yes", "fully_supported": "yes", "unsupported_claim_count": 0,
                   "citation_correct": "not_applicable", "abstention_correct": "not_applicable",
                   "claims": [{"text": "c", "supported": True}], "notes": "ok"})


def rows(n=3):
    context = "Context:\nSource marker: [PDF - a p.1]\ntext"
    context = "rules\n\n" + context
    return [{"blind_id": f"review-{i}", "query": "q", "context": context, "answer": "a",
             "expected_facts": [{"id": "fact-01", "text": "f"}], "expected_abstention": False,
             "emitted_citations": []} for i in range(n)]


def stub(replies):
    calls = []

    async def complete(messages):
        calls.append(messages)
        return replies[min(len(calls), len(replies)) - 1] if callable(replies) is False else replies(messages)
    complete.calls = calls
    return complete


def read(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_runner_writes_one_blinded_row_per_answer(tmp_path):
    out = tmp_path / "labels.jsonl"
    asyncio.run(run_judge(rows(), out, JUDGE, stub([GOOD])))
    written = read(out)
    assert [r["blind_id"] for r in written] == ["review-0", "review-1", "review-2"]
    assert all(r["label_source"] == "llm_assisted" and r["human_verified"] is False
               and r["parse_status"] == "ok" for r in written)


def test_runner_resumes_and_skips_judged_rows(tmp_path):
    out = tmp_path / "labels.jsonl"
    asyncio.run(run_judge(rows(), out, JUDGE, stub([GOOD]), limit=1))
    complete = stub([GOOD])
    summary = asyncio.run(run_judge(rows(), out, JUDGE, complete))
    assert summary == {"already_judged": 1, "judged_now": 2, "remaining": 0}
    assert len(complete.calls) == 2
    assert [r["blind_id"] for r in read(out)] == ["review-0", "review-1", "review-2"]


def test_runner_retries_once_after_invalid_json(tmp_path):
    out = tmp_path / "labels.jsonl"
    complete = stub(["not json", GOOD])
    asyncio.run(run_judge(rows(1), out, JUDGE, complete))
    assert len(complete.calls) == 2 and read(out)[0]["parse_status"] == "ok"
    assert "rejected" in complete.calls[1][-1]["content"]


def test_runner_records_failure_after_second_bad_reply(tmp_path):
    out = tmp_path / "labels.jsonl"
    bad_schema = json.dumps(json.loads(GOOD) | {"unsupported_claim_count": 5})
    complete = stub(["nope", bad_schema])
    asyncio.run(run_judge(rows(1), out, JUDGE, complete))
    row = read(out)[0]
    assert len(complete.calls) == 2
    assert row["parse_status"] == "schema_error" and row["labels"] is None
    asyncio.run(run_judge(rows(1), tmp_path / "b.jsonl", JUDGE, stub(["x", "y"])))
    assert read(tmp_path / "b.jsonl")[0]["parse_status"] == "invalid_json"


def test_runner_refuses_unsafe_overwrite(tmp_path):
    out = tmp_path / "labels.jsonl"
    asyncio.run(run_judge(rows(), out, JUDGE, stub([GOOD]), limit=1))
    before = out.read_text()
    for judge in (JUDGE | {"model": "other"}, JUDGE | {"prompt_sha256": "different"}):
        with pytest.raises(FileExistsError):
            asyncio.run(run_judge(rows(), out, judge, stub([GOOD])))
    with pytest.raises(FileExistsError):
        asyncio.run(run_judge(rows()[1:], out, JUDGE, stub([GOOD])))  # blind_id not in pack
    out.write_text(before + "{broken")
    with pytest.raises(FileExistsError):
        asyncio.run(run_judge(rows(), out, JUDGE, stub([GOOD])))


@pytest.mark.skipif(not PACK.exists(), reason="review pack not present")
def test_all_120_blind_ids_unique_and_judged_once(tmp_path):
    pack = load_pack(PACK)
    assert len(pack) == 120 and len({r["blind_id"] for r in pack}) == 120
    out = tmp_path / "labels.jsonl"
    asyncio.run(run_judge(pack, out, JUDGE, stub([GOOD])))
    asyncio.run(run_judge(pack, out, JUDGE, stub([GOOD])))  # idempotent resume
    ids = [r["blind_id"] for r in read(out)]
    assert len(ids) == 120 and set(ids) == {r["blind_id"] for r in pack}


def test_runner_records_sampling_and_honours_only_ids(tmp_path):
    out = tmp_path / "labels.jsonl"
    summary = asyncio.run(run_judge(rows(), out, JUDGE, stub([GOOD]), temperature_applied=lambda: False,
                                    only_ids={"review-2"}))
    assert summary["judged_now"] == 1
    judge = read(out)[0]["judge"]
    assert judge["sampling"] == "provider_default" and judge["temperature_applied"] is False
    with pytest.raises(ValueError, match="not in the pack"):
        asyncio.run(run_judge(rows(), out, JUDGE, stub([GOOD]), only_ids={"nope"}))


# --- v2 / anthropic ----------------------------------------------------------------------

from eval.judge_prompt import PROMPT_SHA256_V2  # noqa: E402

JUDGE_V2 = JUDGE | {"prompt_version": "v2", "prompt_sha256": PROMPT_SHA256_V2}
GOOD_V2 = json.dumps({"answer_correct": "yes", "fully_supported": "yes", "unsupported_claim_count": 0,
                      "minor_imprecision_count": 0, "citation_correct": "not_applicable",
                      "abstention_correct": "not_applicable",
                      "claims": [{"text": "c", "status": "supported"}], "notes": "ok"})


def test_runner_validates_against_the_requested_prompt_version(tmp_path):
    out = tmp_path / "v2.jsonl"
    asyncio.run(run_judge(rows(1), out, JUDGE_V2, stub([GOOD_V2]), version="v2"))
    assert read(out)[0]["parse_status"] == "ok" and read(out)[0]["judge"]["prompt_version"] == "v2"
    # a v1-shaped reply is a schema error under v2 (and is retried once)
    bad = tmp_path / "bad.jsonl"
    complete = stub([GOOD])
    asyncio.run(run_judge(rows(1), bad, JUDGE_V2, complete, version="v2"))
    assert read(bad)[0]["parse_status"] == "schema_error" and len(complete.calls) == 2


def test_v1_and_v2_outputs_cannot_be_mixed(tmp_path):
    out = tmp_path / "labels.jsonl"
    asyncio.run(run_judge(rows(), out, JUDGE, stub([GOOD]), limit=1))
    with pytest.raises(FileExistsError):
        asyncio.run(run_judge(rows(), out, JUDGE_V2, stub([GOOD_V2]), version="v2"))


def test_anthropic_provider_requires_a_key(monkeypatch):
    from app.core.config import settings
    from eval.judge_answer_review_pack import _configure_provider

    monkeypatch.setattr(settings, "anthropic_api_key", "")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        _configure_provider("anthropic", "claude-opus-5-5")


def test_with_retries_backs_off_on_rate_limits_and_reraises_other_errors():
    from eval.judge_answer_review_pack import with_retries

    class Http(Exception):
        def __init__(self, status):
            self.response = type("R", (), {"status_code": status})()

    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise Http(429)
        return "ok"
    assert asyncio.run(with_retries(flaky, base_delay=0)) == "ok" and calls["n"] == 3

    async def always_429():
        raise Http(429)
    with pytest.raises(Http):
        asyncio.run(with_retries(always_429, attempts=3, base_delay=0))

    async def bad_request():
        calls["n"] += 1
        raise Http(400)
    calls["n"] = 0
    with pytest.raises(Http):
        asyncio.run(with_retries(bad_request, base_delay=0))
    assert calls["n"] == 1


def test_with_retries_does_not_retry_when_out_of_credit():
    from eval.judge_answer_review_pack import with_retries

    for text in ('{"error": {"type": "insufficient_quota"}}',
                 "Rate limit reached ... on tokens per day (TPD): Limit 200000, Used 198811"):
        class Quota(Exception):
            response = type("R", (), {"status_code": 429, "text": text})()
        calls = []

        async def broke(calls=calls, quota=Quota):
            calls.append(1)
            raise quota()
        with pytest.raises(Quota):
            asyncio.run(with_retries(broke, base_delay=0))
        assert len(calls) == 1
