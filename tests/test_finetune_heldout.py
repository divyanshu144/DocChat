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
