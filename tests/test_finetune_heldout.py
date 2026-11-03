"""The heldout-v2 builder: produces harness-compatible workloads, only from held-out documents, grounded in retrieval."""
import json
import random

import pytest

from eval.prepare_heldout_v2 import build_cases, corpus_fingerprint
from eval.workloads import Workloads, load_workloads
from finetune import corpus
from finetune.retrieval import CorpusIndex
from tests.test_finetune_generation import FakeEmbedder, FakeTeacher, guide_json, make_doc, lenient_retrieval  # noqa: F401


class BroadTeacher(FakeTeacher):
    def complete(self, messages, max_tokens=700, temperature=0.2):
        text = messages[0]["content"]
        if text.startswith("Write one broad question"):
            return "What does the pay guide cover, who can claim, and what exceptions apply?"
        return super().complete(messages, max_tokens, temperature)


@pytest.fixture
def held(tmp_path):
    docs = [make_doc("held-one", "heldout"), make_doc("held-two", "heldout")]
    for d in docs:
        body = ["Statutory pay lasts 39 weeks and is paid by your employer every month. " * 6,
                "You must tell your employer at least 28 days before you want the pay to start. " * 6]
        (tmp_path / f"{d.id}.json").write_text(json.dumps(guide_json(d.title, body)))
    points = [p for d in docs for p in corpus.build_doc_points(d, tmp_path, FakeEmbedder())]
    return docs, CorpusIndex(points, FakeEmbedder().embed_query)


def test_cases_cover_every_category_and_are_held_out(held):
    docs, index = held
    cases = build_cases(docs, index, BroadTeacher(), random.Random(1))
    categories = {c.category for c in cases}
    assert categories == {"document_qa", "summarisation", "long_context", "multi_document", "negative_control"}
    assert all(c.split == "held_out" and c.messages[0].role == "system" and c.messages[1].role == "user" for c in cases)
    assert len({c.id for c in cases}) == len(cases)


def test_document_questions_are_grounded_in_retrieval_and_negatives_expect_nothing(held):
    docs, index = held
    cases = build_cases(docs, index, BroadTeacher(), random.Random(1))
    asked = {c.query for c in cases if c.category == "document_qa"}
    assert any(c.category == "negative_control" for c in cases)
    for c in cases:
        if c.category == "document_qa":
            assert c.evidence_retrieved and set(c.evidence_retrieved) <= set(c.expected_evidence)
        if c.category == "negative_control":
            assert c.expected_evidence == [] and c.query in asked  # borrowed from a document question, not invented


def test_only_the_held_out_documents_are_ever_used(held):
    docs, index = held
    allowed = {corpus.source_id(d) for d in docs}
    for c in build_cases(docs, index, BroadTeacher(), random.Random(1)):
        assert set(c.source_ids) <= allowed


def test_the_output_loads_in_the_existing_harness_and_the_fingerprint_is_stable(held, tmp_path):
    docs, index = held
    cases = build_cases(docs, index, BroadTeacher(), random.Random(1))
    workloads = Workloads(corpus_sha256=corpus_fingerprint(index, docs), cases=cases)
    path = tmp_path / "w.json"
    path.write_text(workloads.model_dump_json())
    loaded = load_workloads(path, "replay")
    assert loaded.fingerprint() == workloads.fingerprint() and len(loaded.cases) == len(cases)
    assert corpus_fingerprint(index, docs) == corpus_fingerprint(index, list(reversed(docs)))


def test_a_broad_question_that_is_not_a_question_is_dropped(held):
    docs, index = held

    class Rambling(BroadTeacher):
        def complete(self, messages, *a, **k):
            if messages[0]["content"].startswith("Write one broad question"):
                return "Here is some text without a question mark"
            return super().complete(messages, *a, **k)

    assert "long_context" not in {c.category for c in build_cases(docs, index, Rambling(), random.Random(1))}


def test_hosted_answers_keep_failures_in_workload_order_and_feed_the_review_pack(held, tmp_path, monkeypatch):
    import asyncio

    from eval import generate_hosted_answers as hosted
    from eval.build_answer_review_pack import build_pack

    docs, index = held
    cases = build_cases(docs, index, BroadTeacher(), random.Random(1))
    workload = tmp_path / "w.json"
    workload.write_text(Workloads(corpus_sha256=corpus_fingerprint(index, docs), cases=cases).model_dump_json())
    failing = [c.id for c in cases if c.messages[-1].content == cases[1].messages[-1].content]

    async def fake_chat(messages, max_tokens, temperature=None):
        if messages[-1]["content"] == cases[1].messages[-1].content:
            raise RuntimeError("provider down")
        return "An answer.\n\nSources:\n\n[Web - Pay guide]"

    async def no_close():
        return None

    from app.core.config import settings
    # generate() switches the global provider settings; monkeypatch puts the originals back after the test
    monkeypatch.setattr(settings, "llm_provider", settings.llm_provider)
    monkeypatch.setattr(settings, "fallback_llm_provider", settings.fallback_llm_provider)
    monkeypatch.setattr(hosted.llm, "chat_complete", fake_chat)
    monkeypatch.setattr(hosted.llm, "close_llm_clients", no_close)
    out = tmp_path / "answers.jsonl"
    asyncio.run(hosted.generate(workload, out, max_tokens=100, concurrency=2))
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert [r["case_id"] for r in rows] == [c.id for c in cases]  # workload order
    assert [r["case_id"] for r in rows if r["status"] == "error"] == failing  # kept in the denominator, marked as errors
    pack, key = build_pack(workload, [out])  # the unchanged review-pack builder accepts the rows
    assert len(pack) == len(cases) and {k["model"] for k in key} == {rows[0]["model"]}
    with pytest.raises(FileExistsError):
        asyncio.run(hosted.generate(workload, out, max_tokens=100, concurrency=2))


def test_a_negative_control_is_dropped_when_the_teacher_says_the_context_can_answer_it(held):
    class Answerable(BroadTeacher):
        def complete(self, messages, *a, **k):
            if messages[0]["content"].startswith("Decide whether the passages"):
                return json.dumps({"answerable": True})
            return super().complete(messages, *a, **k)

    docs, index = held
    cases = build_cases(docs, index, Answerable(), random.Random(1))
    assert not any(c.category == "negative_control" for c in cases)
    assert any(c.category == "document_qa" for c in cases)


def test_hosted_answers_never_fall_back_and_retry_rate_limits(held, tmp_path, monkeypatch):
    import asyncio

    import httpx

    from app.core.config import settings
    from eval import generate_hosted_answers as hosted

    docs, index = held
    cases = build_cases(docs, index, BroadTeacher(), random.Random(1))[:2]
    workload = tmp_path / "w.json"
    workload.write_text(Workloads(corpus_sha256=corpus_fingerprint(index, docs), cases=cases).model_dump_json())
    monkeypatch.setattr(settings, "llm_provider", settings.llm_provider)
    monkeypatch.setattr(settings, "fallback_llm_provider", "openai")
    seen, pauses = [], []

    async def flaky(messages, max_tokens, temperature=None):
        seen.append(settings.fallback_llm_provider)
        if len(seen) == 1:
            request = httpx.Request("POST", "https://api.groq.com/x")
            raise httpx.HTTPStatusError("429", request=request, response=httpx.Response(429, request=request))
        return "An answer.\n\nSources:\n\n[Web - Pay guide]"

    async def no_close():
        return None

    async def fake_sleep(seconds):
        pauses.append(seconds)

    monkeypatch.setattr(hosted.llm, "chat_complete", flaky)
    monkeypatch.setattr(hosted.llm, "close_llm_clients", no_close)
    asyncio.run(hosted.generate(workload, tmp_path / "a.jsonl", max_tokens=50, concurrency=1, sleep=fake_sleep))
    rows = [json.loads(line) for line in (tmp_path / "a.jsonl").read_text().splitlines()]
    assert [r["status"] for r in rows] == ["ok", "ok"] and pauses == [5]  # one rate limit, one pause, then success
    assert set(seen) == {"none"}  # a failure can never be answered by another provider


def _hosted_workload(held, tmp_path, count=4):
    docs, index = held
    cases = build_cases(docs, index, BroadTeacher(), random.Random(1))[:count]
    path = tmp_path / "w.json"
    path.write_text(Workloads(corpus_sha256=corpus_fingerprint(index, docs), cases=cases).model_dump_json())
    return path, cases


def test_hosted_run_stops_cleanly_at_a_daily_token_limit_and_resumes_the_rest(held, tmp_path, monkeypatch):
    import asyncio

    import httpx

    from app.core.config import settings
    from eval import generate_hosted_answers as hosted

    workload, cases = _hosted_workload(held, tmp_path)
    monkeypatch.setattr(settings, "llm_provider", settings.llm_provider)
    monkeypatch.setattr(settings, "fallback_llm_provider", settings.fallback_llm_provider)
    calls = []

    async def spent_after_two(messages, max_tokens, temperature=None):
        calls.append(messages[-1]["content"])
        if len(calls) > 2:
            request = httpx.Request("POST", "https://api.groq.com/x")
            body = '{"error":{"message":"Rate limit reached ... on tokens per day (TPD): Limit 200000, Used 199000"}}'
            raise httpx.HTTPStatusError("429", request=request, response=httpx.Response(429, request=request, text=body))
        return "An answer.\n\nSources:\n\n[Web - Pay guide]"

    async def fine(messages, max_tokens, temperature=None):
        calls.append(messages[-1]["content"])
        return "An answer.\n\nSources:\n\n[Web - Pay guide]"

    async def no_close():
        return None

    async def no_sleep(seconds):
        return None

    monkeypatch.setattr(hosted.llm, "close_llm_clients", no_close)
    out = tmp_path / "a.jsonl"
    monkeypatch.setattr(hosted.llm, "chat_complete", spent_after_two)
    first = asyncio.run(hosted.generate(workload, out, max_tokens=50, concurrency=1, sleep=no_sleep))
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert first["answered"] == 2 and first["not_tried_daily_limit"] == 2 and first["errors"] == 0
    assert [r["status"] for r in rows] == ["ok", "ok"]  # no error rows invented for cases that were never tried
    calls.clear()
    monkeypatch.setattr(hosted.llm, "chat_complete", fine)
    second = asyncio.run(hosted.generate(workload, out, max_tokens=50, concurrency=1, sleep=no_sleep, resume=True))
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert second["answered"] == 4 and len(calls) == 2  # only the two missing cases were asked
    assert [r["case_id"] for r in rows] == [c.id for c in cases]


def test_resume_retries_error_rows_and_keeps_good_ones(held, tmp_path, monkeypatch):
    import asyncio

    from app.core.config import settings
    from eval import generate_hosted_answers as hosted

    workload, cases = _hosted_workload(held, tmp_path, count=2)
    monkeypatch.setattr(settings, "llm_provider", settings.llm_provider)
    monkeypatch.setattr(settings, "fallback_llm_provider", settings.fallback_llm_provider)
    out = tmp_path / "a.jsonl"
    good = {"case_id": cases[0].id, "status": "ok", "answer": "kept answer"}
    bad = {"case_id": cases[1].id, "status": "error", "error": "RuntimeError: boom"}
    out.write_text(json.dumps(good) + "\n" + json.dumps(bad) + "\n")
    asked = []

    async def fine(messages, max_tokens, temperature=None):
        asked.append(messages[-1]["content"])
        return "fresh answer"

    async def no_close():
        return None

    monkeypatch.setattr(hosted.llm, "chat_complete", fine)
    monkeypatch.setattr(hosted.llm, "close_llm_clients", no_close)
    asyncio.run(hosted.generate(workload, out, max_tokens=50, concurrency=1, resume=True))
    rows = {json.loads(line)["case_id"]: json.loads(line) for line in out.read_text().splitlines()}
    assert rows[cases[0].id]["answer"] == "kept answer" and rows[cases[1].id]["answer"] == "fresh answer"
    assert len(asked) == 1
