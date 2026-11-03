"""Abstention examples and negative controls: questions borrowed from other documents, a strict check, a hidden hint."""
import json
import random

import pytest

from finetune import abstentions as ab
from finetune import corpus
from finetune.retrieval import CorpusIndex
from finetune.validate_examples import validate_example
from tests.test_finetune_generation import PAYING, FakeEmbedder, FakeTeacher, guide_json, lenient_retrieval, make_doc  # noqa: F401


@pytest.fixture
def ab_docs():
    return [make_doc("pay-guide"), make_doc("tax-guide"), make_doc("held-guide", "validation")]


@pytest.fixture
def index(ab_docs, tmp_path):
    points = []
    for doc in ab_docs:
        words = PAYING if doc.id == "pay-guide" else [f"Allowance rules for {doc.id}: the tax threshold is reviewed yearly. " * 12] * 3
        (tmp_path / f"{doc.id}.json").write_text(json.dumps(guide_json(doc.title, words)))
        points += corpus.build_doc_points(doc, tmp_path, FakeEmbedder())
    return CorpusIndex(points, FakeEmbedder().embed_query)


POOL = {"pay-guide": ["How long does statutory pay last?"], "tax-guide": ["Which tax rate applies to me?"],
        "held-guide": ["Who can claim the held benefit?"]}


def test_questions_are_borrowed_only_from_other_documents_of_the_same_split(ab_docs):
    pay = ab_docs[0]
    got = ab.borrowed_candidates(POOL, pay, ab_docs, random.Random(1), 10)
    assert got == ["Which tax rate applies to me?"]  # not its own question, not the validation document's
    assert ab.borrowed_candidates(POOL, ab_docs[2], ab_docs, random.Random(1), 10) == []  # the only validation doc has no peers


def test_borrowed_candidates_are_reproducible_and_capped(ab_docs):
    pool = {"tax-guide": [f"q{i}?" for i in range(20)]}
    a = ab.borrowed_candidates(pool, ab_docs[0], ab_docs, random.Random(7), 5)
    assert a == ab.borrowed_candidates(pool, ab_docs[0], ab_docs, random.Random(7), 5) and len(a) == 5


@pytest.mark.parametrize("reply,expected", [('{"answerable": false}', False), ('{"answerable": true}', True),
                                            ("not json at all", True), ('{"answerable": "no"}', True), ("{}", True)])
def test_only_an_explicit_false_counts_as_unanswerable(reply, expected):
    class T:
        def complete(self, *a, **k):
            return reply
    assert ab.context_can_answer(T(), "q?", [{"text": "some passage"}]) is expected


def test_abstention_examples_validate_and_never_store_the_hint(index, ab_docs):
    out = ab.abstention_examples(ab_docs[0], ab_docs, index, POOL, FakeTeacher(), random.Random(1), wanted=2)
    assert out and all(e.kind == "abstain" and e.doc_ids == ["pay-guide"] and e.split == "train" for e in out)
    assert all(validate_example(e) == [] for e in out), [validate_example(e) for e in out]
    for e in out:
        assert "Instruction for this test only" not in e.model_dump_json()  # the serving prompt is what is trained on
        assert e.messages[1].content == "Which tax rate applies to me?" and e.messages[-1].role == "assistant"


def test_the_hint_does_reach_the_teacher(index, ab_docs):
    class Spy(FakeTeacher):
        pass
    spy = Spy()
    ab.abstention_examples(ab_docs[0], ab_docs, index, POOL, spy, random.Random(1), wanted=1)
    hinted = [m for m in spy.calls if m[-1]["role"] == "user" and "Instruction for this test only" in m[-1]["content"]]
    assert hinted and "do not cite sources" in hinted[0][-1]["content"].lower()  # the teacher is told; the dataset is not


def test_a_question_the_context_can_answer_is_not_turned_into_an_abstention(index, ab_docs):
    class Answerable(FakeTeacher):
        def complete(self, messages, *a, **k):
            if messages[0]["content"].startswith("Decide whether the passages"):
                return json.dumps({"answerable": True})
            raise AssertionError("no answer may be written for an answerable question")
    assert ab.abstention_examples(ab_docs[0], ab_docs, index, POOL, Answerable(), random.Random(1)) == []


def test_teacher_failures_lose_only_that_question(index, ab_docs):
    class Down(FakeTeacher):
        def complete(self, *a, **k):
            raise RuntimeError("teacher failed after 3 attempts: HTTPStatusError (HTTP 503)")
    errors = []
    assert ab.abstention_examples(ab_docs[0], ab_docs, index, POOL, Down(), random.Random(1), on_error=errors.append) == []
    assert errors
    with pytest.raises(RuntimeError):
        ab.abstention_examples(ab_docs[0], ab_docs, index, POOL, Down(), random.Random(1))


def test_the_question_pool_uses_single_document_answerable_examples_only(tmp_path):
    rows = [{"kind": "answerable", "doc_ids": ["a"], "messages": [{}, {"content": "Q about a?"}]},
            {"kind": "answerable", "doc_ids": ["a", "b"], "messages": [{}, {"content": "Q about both?"}]},
            {"kind": "abstain", "doc_ids": ["a"], "messages": [{}, {"content": "Q abstain?"}]}]
    path = tmp_path / "e.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows))
    assert ab.question_pool(path) == {"a": ["Q about a?"]}
