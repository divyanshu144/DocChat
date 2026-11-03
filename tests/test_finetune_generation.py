"""Question and example generation, retrieval, corpus and fetch helpers, all with fakes: no model, network or GPU."""
import hashlib
import json
import random
import re
from pathlib import Path

import httpx
import numpy as np
import pytest

from finetune import corpus, fetch_sources, generate_examples as gen
from finetune.extract import govuk_text, html_to_text
from finetune.questions import ask_questions, pick_windows
from finetune.retrieval import CorpusIndex, build_messages
from finetune.schema import Manifest, SourceDoc
from finetune.teacher import HttpTeacher, parse_json_object
from finetune.validate_examples import validate_example

OGL = "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/"


class FakeEmbedder:
    """Bag-of-words hashing into 384 dimensions, so cosine search behaves like a (crude) topical search."""
    def _vec(self, text):
        v = np.zeros(384, dtype=np.float32)
        for word in re.findall(r"[a-z0-9]+", text.lower()):
            v[int(hashlib.md5(word.encode()).hexdigest(), 16) % 384] += 1.0
        n = np.linalg.norm(v)
        return v / n if n else v

    def embed_query(self, text):
        return self._vec(text)

    def embed_independently(self, texts):
        return [self._vec(t) for t in texts]


def make_doc(doc_id, split="train", url=None):
    return SourceDoc(id=doc_id, title=doc_id.replace("-", " ").title(), kind="govuk_guide", url=url or f"https://www.gov.uk/{doc_id}",
                     licence="Open Government Licence v3.0", licence_url=OGL, split=split)


def guide_json(title, paragraphs):
    return {"title": title, "details": {"parts": [{"title": "Overview", "body": "".join(f"<p>{p}</p>" for p in paragraphs)}]}}


PAYING = ["Statutory pay lasts 39 weeks and is paid by your employer every month. " * 6,
          "You must tell your employer at least 28 days before you want the pay to start. " * 6,
          "Payment stops if you return to work early, and you can claim again for the next child. " * 6]


@pytest.fixture(autouse=True)
def lenient_retrieval(monkeypatch):
    """The hashing embedder is far cruder than the real one, so its cosine scores sit lower than 0.3."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "retrieval_min_score", 0.05)


@pytest.fixture
def raw_dir(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    for doc_id, title in [("pay-guide", "Pay guide"), ("tax-guide", "Tax guide"), ("held-guide", "Held guide")]:
        words = PAYING if doc_id == "pay-guide" else [f"Allowance rules for {doc_id}: the tax threshold is reviewed yearly and reported to HMRC. " * 12] * 3
        (raw / f"{doc_id}.json").write_text(json.dumps(guide_json(title, words)))
    return raw


@pytest.fixture
def docs():
    return [make_doc("pay-guide"), make_doc("tax-guide"), make_doc("held-guide", "validation")]


@pytest.fixture
def points(docs, raw_dir):
    out = {d.id: corpus.build_doc_points(d, raw_dir, FakeEmbedder()) for d in docs}
    return out


class FakeTeacher:
    name = "fake-teacher"

    def __init__(self, drop_window_words=False):
        self.calls = []

    def complete(self, messages, max_tokens=700, temperature=0.2):
        self.calls.append(messages)
        text = messages[0]["content"]
        if text.startswith("You write test questions"):
            return ("```json\n" + json.dumps({"answerable": [
                {"question": "How long does statutory pay last?", "facts": ["It lasts 39 weeks."]},
                {"question": "When must I tell my employer about the pay start?", "facts": ["28 days before."]}],
                "unanswerable": ["What is the exact bonus rate paid on overtime in the pay guide?"]}) + "\n```")
        if text.startswith("Decide whether the passages"):
            return json.dumps({"answerable": False})
        if "Instruction for this test only" in messages[-1]["content"]:
            return "The provided sources do not contain the information needed to answer this question."
        marker = re.search(r"^Source marker: (\[[^\]\n]+\])", messages[0]["content"], re.MULTILINE).group(1)
        if "bonus" in messages[1]["content"]:
            return "The context does not contain the bonus rate for overtime."
        return f"Statutory pay lasts 39 weeks and your employer pays it monthly.\n\nSources:\n\n{marker}"


# ---------------- extraction, corpus, retrieval ----------------
def test_html_and_guide_text():
    assert html_to_text("<p>One &amp; two</p><ul><li>a</li><li>b</li></ul>") == "One & two\na\nb"
    text = govuk_text(guide_json("A guide", ["Body one."]))
    assert text.splitlines()[0] == "A guide" and "Overview" in text and "Body one." in text


def test_points_carry_the_metadata_that_makes_citation_markers(points):
    payload = points["pay-guide"][0].payload
    assert payload["source_type"] == "web" and payload["title"] == "Pay guide" and payload["domain"] == "www.gov.uk"
    assert payload["source_id"] == corpus.source_id(make_doc("pay-guide"))
    assert corpus.source_id(make_doc("pay-guide")) != corpus.source_id(make_doc("tax-guide"))


def test_pdf_points_have_page_numbers(tmp_path):
    fitz = pytest.importorskip("fitz")
    pdf = fitz.open()
    pdf.new_page().insert_text((72, 72), "Section one text. " * 40)
    pdf.new_page().insert_text((72, 72), "Section two text. " * 40)
    (tmp_path / "paper-one.pdf").write_bytes(pdf.tobytes())
    doc = SourceDoc(id="paper-one", title="Paper one", kind="pdf", url="https://example.gov/pubs/paper.pdf",
                    licence="US government work", licence_url="https://example.gov/c", split="train")
    pts = corpus.build_doc_points(doc, tmp_path, FakeEmbedder())
    assert {p.payload["page_number"] for p in pts} == {1, 2} and pts[0].payload["filename"] == "paper.pdf"


def test_points_round_trip_through_disk(tmp_path, points):
    corpus.write_points(tmp_path / "x.jsonl", points["pay-guide"])
    again = corpus.read_points(tmp_path / "x.jsonl")
    assert [str(p.id) for p in again] == [str(p.id) for p in points["pay-guide"]] and again[0].payload == points["pay-guide"][0].payload


def test_retrieval_is_scoped_to_the_requested_documents(points, docs):
    index = CorpusIndex([p for pts in points.values() for p in pts], FakeEmbedder().embed_query)
    pay, tax = corpus.source_id(docs[0]), corpus.source_id(docs[1])
    chunks = index.retrieve("How long does statutory pay last?", [pay])
    assert chunks and {c["metadata"]["source_id"] for c in chunks} == {pay}
    for question, scope in [("How long does statutory pay last?", tax), ("tax threshold allowance", pay), ("tax threshold allowance", tax)]:
        assert all(c["metadata"]["source_id"] == scope for c in index.retrieve(question, [scope]))
    assert index.retrieve("zzz qqq xxx unrelated gibberish", [pay]) == []


def test_prompt_is_the_serving_prompt_with_real_markers(points, docs):
    index = CorpusIndex(points["pay-guide"], FakeEmbedder().embed_query)
    chunks = index.retrieve("How long does statutory pay last?", [corpus.source_id(docs[0])])
    messages = build_messages("How long does statutory pay last?", chunks)
    assert messages[0]["role"] == "system" and "Source marker: [Web - Pay guide]" in messages[0]["content"]
    assert messages[1] == {"role": "user", "content": "How long does statutory pay last?"}


# ---------------- questions ----------------
def test_windows_are_reproducible_and_spread(points):
    ids = [str(p.id) for p in points["pay-guide"]]
    texts = {str(p.id): p.payload["text"] for p in points["pay-guide"]}
    a = pick_windows(ids, texts, 2, random.Random(1))
    assert [w.chunk_ids for w in a] == [w.chunk_ids for w in pick_windows(ids, texts, 2, random.Random(1))]
    assert pick_windows([], {}, 3, random.Random(1)) == []


def test_question_parsing_tolerates_fences_and_junk():
    assert parse_json_object('Sure!\n```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object("no json at all") is None and parse_json_object("{broken") is None

    class Junk(FakeTeacher):
        def complete(self, *a, **k):
            return '{"answerable": [{"question": "  "}, {"question": "Real one?", "facts": ["f", 3]}, "x"], "unanswerable": ["", "Off topic?"]}'
    ok, off = ask_questions(Junk(), pick_windows(["a"], {"a": "text"}, 1, random.Random(0))[0])
    assert ok == [{"question": "Real one?", "facts": ["f"]}] and off == ["Off topic?"]


# ---------------- example generation ----------------
def test_generated_examples_pass_the_validator_and_include_abstentions(points, docs):
    index = CorpusIndex([p for pts in points.values() for p in pts], FakeEmbedder().embed_query)
    examples = gen.examples_for_document(docs[0], index, [docs[1]], FakeTeacher(), random.Random(3), windows=3, multi_doc_rate=0.0)
    assert examples and {e.kind for e in examples} == {"answerable", "abstain"}
    assert all(validate_example(e) == [] for e in examples), [validate_example(e) for e in examples]
    assert all(e.split == "train" and e.doc_ids == ["pay-guide"] and e.teacher == "fake-teacher" for e in examples)


def test_questions_the_retriever_cannot_ground_are_skipped(points, docs):
    class OffTopic(FakeTeacher):
        def complete(self, messages, *a, **k):
            if messages[0]["content"].startswith("You write test questions"):
                return json.dumps({"answerable": [{"question": "qqq zzz xxx", "facts": []}], "unanswerable": ["www vvv uuu"]})
            raise AssertionError("the answer model must not be called when nothing was retrieved")
    index = CorpusIndex(points["pay-guide"], FakeEmbedder().embed_query)
    assert gen.examples_for_document(docs[0], index, [], OffTopic(), random.Random(1)) == []


def test_answerable_questions_whose_window_was_not_retrieved_are_dropped(tmp_path):
    # Six chunks that share no vocabulary; the question matches only chunk 2, so only the window holding chunk 2 may yield it.
    doc = make_doc("long-guide")
    (tmp_path / "long-guide.json").write_text(json.dumps(guide_json("Long guide", [f"topic{i}x detail{i}y " * 90 for i in range(6)])))
    pts = corpus.build_doc_points(doc, tmp_path, FakeEmbedder())
    assert len(pts) >= 6

    class AboutChunkTwo(FakeTeacher):
        def complete(self, messages, *a, **k):
            if messages[0]["content"].startswith("You write test questions"):
                return json.dumps({"answerable": [{"question": "topic2x detail2y", "facts": []}], "unanswerable": []})
            return super().complete(messages)

    index = CorpusIndex(pts, FakeEmbedder().embed_query)
    sid = corpus.source_id(doc)
    retrieved = {c["id"] for c in index.retrieve("topic2x detail2y", [sid])}
    ids = index.chunk_ids_in_order(sid)
    windows = [ids[i:i + 2] for i in range(0, len(ids), 2)]
    expected = [w for w in windows if retrieved & set(w)]
    assert 0 < len(expected) < len(windows)  # the question is grounded in some windows and not in others
    kept = gen.examples_for_document(doc, index, [], AboutChunkTwo(), random.Random(5), windows=len(windows), multi_doc_rate=0.0)
    assert len(kept) == len(expected)


def test_training_and_validation_documents_are_never_mixed(points, docs, tmp_path, monkeypatch):
    for d in docs:
        corpus.write_points(tmp_path / f"{d.id}.points.jsonl", points[d.id])
    monkeypatch.setattr("app.services.embedder.get_embedder", lambda: FakeEmbedder())
    manifest = Manifest(documents=docs)
    out = tmp_path / "ex.jsonl"
    count = gen.generate(manifest, tmp_path, FakeTeacher(), out, windows=2, multi_doc_rate=1.0)
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert count == len(rows) > 0
    split_of = {d.id: d.split for d in docs}
    assert all({split_of[i] for i in r["doc_ids"]} == {r["split"]} for r in rows)
    assert any(len(r["doc_ids"]) == 2 for r in rows)  # multi-document contexts do get built, within a split


def test_parallel_generation_gives_the_same_examples_as_serial(points, docs, tmp_path, monkeypatch):
    for d in docs:
        corpus.write_points(tmp_path / f"{d.id}.points.jsonl", points[d.id])
    monkeypatch.setattr("app.services.embedder.get_embedder", lambda: FakeEmbedder())
    manifest = Manifest(documents=docs)
    serial, parallel = tmp_path / "serial.jsonl", tmp_path / "parallel.jsonl"
    gen.generate(manifest, tmp_path, FakeTeacher(), serial, windows=2, multi_doc_rate=0.5, workers=1)
    gen.generate(manifest, tmp_path, FakeTeacher(), parallel, windows=2, multi_doc_rate=0.5, workers=4)
    # Documents are written as they finish, so only the order of the lines may differ.
    assert sorted(serial.read_text().splitlines()) == sorted(parallel.read_text().splitlines()) != []


class FlakyTeacher(FakeTeacher):
    """Writes questions fine but fails every answer call."""

    def complete(self, messages, max_tokens=700, temperature=0.2):
        if not messages[0]["content"].startswith("You write test questions"):
            raise RuntimeError("teacher failed after 3 attempts: HTTPStatusError (HTTP 503)")
        return super().complete(messages, max_tokens, temperature)


def _write_corpus(points, docs, tmp_path, monkeypatch):
    for d in docs:
        corpus.write_points(tmp_path / f"{d.id}.points.jsonl", points[d.id])
    monkeypatch.setattr("app.services.embedder.get_embedder", lambda: FakeEmbedder())
    return Manifest(documents=docs)


def test_a_failed_teacher_call_is_skipped_and_counted_not_fatal(points, docs):
    index = CorpusIndex([p for pts in points.values() for p in pts], FakeEmbedder().embed_query)
    errors = []
    out = gen.examples_for_document(docs[0], index, [], FlakyTeacher(), random.Random(1), windows=2,
                                    multi_doc_rate=0.0, on_error=errors.append)
    assert out == [] and errors  # nothing survived, and the failures were counted
    with pytest.raises(RuntimeError):  # without a handler the error still surfaces
        gen.examples_for_document(docs[0], index, [], FlakyTeacher(), random.Random(1), windows=2)


def test_a_failed_question_call_loses_only_that_window(points, docs):
    class NoQuestions(FakeTeacher):
        def complete(self, messages, *a, **k):
            raise RuntimeError("teacher failed after 3 attempts: HTTPStatusError (HTTP 504)")
    index = CorpusIndex([p for pts in points.values() for p in pts], FakeEmbedder().embed_query)
    errors = []
    assert gen.examples_for_document(docs[0], index, [], NoQuestions(), random.Random(1), windows=3,
                                     on_error=errors.append) == []
    assert errors  # the failure was counted and the run went on


def test_too_many_teacher_failures_fail_the_run(points, docs, tmp_path, monkeypatch):
    manifest = _write_corpus(points, docs, tmp_path, monkeypatch)
    with pytest.raises(RuntimeError, match="teacher calls failed"):
        gen.generate(manifest, tmp_path, FlakyTeacher(), tmp_path / "ex.jsonl", windows=2)


def test_resume_skips_documents_already_written(points, docs, tmp_path, monkeypatch):
    manifest = _write_corpus(points, docs, tmp_path, monkeypatch)
    out = tmp_path / "ex.jsonl"
    gen.generate(manifest, tmp_path, FakeTeacher(), out, windows=2, multi_doc_rate=0.0)
    first = out.read_text()
    assert gen.generate(manifest, tmp_path, FakeTeacher(), out, windows=2, multi_doc_rate=0.0, resume=True) == 0
    assert out.read_text() == first  # nothing re-generated, nothing duplicated


# ---------------- teacher client ----------------
def test_teacher_retries_transient_errors_and_not_client_errors(tmp_path):
    calls = []

    def handler(request):
        calls.append(request.headers.get("authorization"))
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})

    keyfile = tmp_path / "key"
    keyfile.write_text("sk-test-123\n")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    teacher = HttpTeacher("http://x/v1", "m", keyfile, client=client, backoff_s=0)
    assert teacher.complete([{"role": "user", "content": "q"}]) == "hi"
    assert calls == ["Bearer sk-test-123"] * 2

    bad = HttpTeacher("http://x/v1", "m", client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(400))), backoff_s=0)
    with pytest.raises(httpx.HTTPStatusError):
        bad.complete([{"role": "user", "content": "q"}])


# ---------------- fetching ----------------
def test_fetch_records_hashes_reuses_files_and_detects_tampering(tmp_path):
    manifest = Manifest(documents=[make_doc("pay-guide"), SourceDoc(
        id="paper-one", title="Paper one", kind="pdf", url="https://example.gov/p.pdf", licence="US government work",
        licence_url="https://example.gov/c", split="heldout")])
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, content=b"%PDF-1.4 fake" if request.url.path.endswith(".pdf") else json.dumps(guide_json("T", ["x"])).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    out, lock = tmp_path / "raw", tmp_path / "lock.json"
    result = fetch_sources.fetch(manifest, out, lock, client=client, pause_s=0)
    assert result["downloaded"] == 2 and seen[0] == "https://www.gov.uk/api/content/pay-guide"
    assert set(json.loads(lock.read_text())) == {"pay-guide", "paper-one"}
    assert fetch_sources.fetch(manifest, out, lock, client=client, pause_s=0)["reused"] == 2 and len(seen) == 2
    (out / "pay-guide.json").write_text("tampered")
    with pytest.raises(ValueError, match="does not match its recorded hash"):
        fetch_sources.fetch(manifest, out, lock, client=client, pause_s=0)


def test_a_non_pdf_download_for_a_pdf_source_is_rejected(tmp_path):
    manifest = Manifest(documents=[SourceDoc(id="paper-two", title="P", kind="pdf", url="https://example.gov/p.pdf",
                                             licence="US government work", licence_url="https://example.gov/c", split="train")])
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"<html>login</html>")))
    with pytest.raises(ValueError, match="did not return a PDF"):
        fetch_sources.fetch(manifest, tmp_path / "raw", tmp_path / "lock.json", client=client, pause_s=0)
    assert not (tmp_path / "raw" / "paper-two.pdf").exists()


def test_the_committed_manifest_if_present_is_valid_and_split_by_document():
    path = Path("finetune/manifest.json")
    if not path.exists():
        pytest.skip("manifest not built yet")
    manifest = fetch_sources.load_manifest(path)
    assert {"train", "validation", "heldout"} <= {d.split for d in manifest.documents}
    assert all(d.licence and d.licence_url for d in manifest.documents)
    assert all(d.note for d in manifest.by_split("excluded")), "an excluded document must say why"
    # one document, one split: no URL or id appears twice (Manifest already enforces this), and nothing is left unassigned
    assert {d.split for d in manifest.documents} <= {"train", "validation", "heldout", "excluded"}
