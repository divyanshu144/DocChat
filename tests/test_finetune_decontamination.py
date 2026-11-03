"""The leakage check must fail loudly when training data shares text with the evaluation data."""
import json

import pytest

from finetune.decontaminate import (
    LeakageError, build_reference_index, check_examples, check_texts, ngram_hashes, overlap, record_hashes)
from tests.test_finetune_validation import GOOD, M1, example, system

EVAL_CHUNK = ("Employers must keep records showing that the working time limits have been respected for every "
              "worker and must keep those records for at least two years from the date they were made")


@pytest.fixture
def index(tmp_path):
    pack = tmp_path / "pack.jsonl"
    pack.write_text(json.dumps({"case_id": "x", "short": "too short", "evidence": [EVAL_CHUNK]}) + "\n")
    workload = tmp_path / "workload.json"
    workload.write_text(json.dumps({"cases": [{"messages": [{"role": "user", "content": "A fresh unrelated question text that is long enough to count."}]}]}))
    return build_reference_index([pack, workload])


def test_ngrams_are_case_and_punctuation_insensitive():
    assert ngram_hashes("One, two! THREE four five six seven eight nine") == ngram_hashes("one two three four five six seven eight nine")
    assert ngram_hashes("too short to make an eight gram") == set()


def test_clean_examples_pass(index):
    check_examples([example(GOOD)], index)


def test_a_planted_leak_in_the_context_is_caught(index):
    leaked = example(GOOD, sys_prompt=system(body=EVAL_CHUNK))
    with pytest.raises(LeakageError, match="overlap evaluation data"):
        check_examples([example(GOOD), leaked], index)


def test_a_leak_in_the_answer_or_question_is_caught(index):
    with pytest.raises(LeakageError):
        check_examples([example(f"{EVAL_CHUNK}.\n\nSources:\n\n{M1}")], index)
    with pytest.raises(LeakageError):
        check_examples([example(GOOD, question=EVAL_CHUNK)], index)


def test_the_shared_serving_prompt_is_not_counted_as_a_leak(index, tmp_path):
    from finetune.validate_examples import SERVING_PREFIX
    prompt_ref = tmp_path / "prompt.json"
    prompt_ref.write_text(json.dumps({"p": SERVING_PREFIX}))
    check_examples([example(GOOD)], build_reference_index([prompt_ref]))


def test_a_partial_overlap_counts_and_max_shared_can_allow_a_little(index):
    short_overlap = " ".join(EVAL_CHUNK.split()[:9])  # exactly two shared 8-grams
    ex = example(f"{short_overlap}.\n\nSources:\n\n{M1}")
    with pytest.raises(LeakageError):
        check_examples([ex], index)
    check_examples([ex], index, max_shared=5)


def test_document_level_check(index):
    check_texts({"fine": "Nothing in common with the evaluation material at all, just words."}, index)
    with pytest.raises(LeakageError, match="1 document"):
        check_texts({"bad": EVAL_CHUNK, "fine": "Different text entirely, nothing shared here."}, index)


def test_missing_reference_file_is_an_error_not_a_skip(tmp_path):
    with pytest.raises(FileNotFoundError, match="missing"):
        build_reference_index([tmp_path / "nope.jsonl"])


def test_overlap_reports_which_file(index):
    assert list(overlap(EVAL_CHUNK, index)) == [name for name in index if "pack" in name]


def test_hashes_are_recorded_and_change_with_content(tmp_path):
    f = tmp_path / "train.jsonl"
    f.write_text("a")
    first = record_hashes([f])
    f.write_text("b")
    assert first != record_hashes([f]) and len(next(iter(first.values()))) == 64


def test_heldout_documents_must_not_appear_in_training_documents():
    from finetune.decontaminate import check_documents_disjoint
    shared = " ".join(f"word{i}" for i in range(200))
    train = {"t1": "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu " * 20}
    fractions = check_documents_disjoint(train, {"h1": "completely different content " * 40})
    assert fractions["h1"] == 0.0
    with pytest.raises(LeakageError, match="held-out document"):
        check_documents_disjoint({"t2": shared + " extra"}, {"h2": shared})


def test_a_few_stock_sentences_in_common_are_tolerated_but_wholesale_copying_is_not():
    from finetune.decontaminate import check_documents_disjoint
    stock = "you can get free impartial advice from your local citizens advice bureau about this"
    heldout = {"h": " ".join(f"unique{i}" for i in range(600)) + " " + stock}
    train = {"t": stock + " " + " ".join(f"other{i}" for i in range(600))}
    assert check_documents_disjoint(train, heldout)["h"] < 0.02


def test_stock_text_in_many_training_documents_is_ignored_but_a_single_near_copy_is_not():
    from finetune.decontaminate import check_documents_disjoint, overlapping_training_docs, stock_ngrams
    stock = "this publication has been developed by the institute in accordance with its statutory responsibilities under law"
    specific = " ".join(f"specificterm{i}" for i in range(120))
    train = {f"t{i}": stock + " " + " ".join(f"filler{i}x{j}" for j in range(200)) for i in range(3)}
    train["copy"] = specific + " " + " ".join(f"pad{j}" for j in range(200))
    heldout = {"h": stock + " " + specific + " " + " ".join(f"own{j}" for j in range(200))}
    ignored = stock_ngrams(train)
    assert ignored and overlapping_training_docs(train, heldout, ignored)[0][:2] == ("copy", "h")
    with pytest.raises(LeakageError):
        check_documents_disjoint(train, heldout, stock=ignored)  # the copied passage still counts
    del train["copy"]
    assert check_documents_disjoint(train, heldout, stock=stock_ngrams(train))["h"] < 0.02
    assert overlapping_training_docs(train, heldout, stock_ngrams(train)) == []


def test_the_document_report_refuses_a_training_document_that_copies_a_heldout_one(tmp_path):
    from finetune import corpus
    from finetune.check_documents import run
    from finetune.schema import Manifest
    from tests.test_finetune_generation import FakeEmbedder, guide_json, make_doc
    docs = [make_doc("train-doc"), make_doc("held-doc", "heldout")]
    shared = [" ".join(f"specificterm{i}" for i in range(150))]
    for d, extra in ((docs[0], "alpha"), (docs[1], "omega")):
        (tmp_path / f"{d.id}.json").write_text(json.dumps(guide_json(d.title, shared + [f"{extra} text " * 100])))
        corpus.write_points(tmp_path / f"{d.id}.points.jsonl", corpus.build_doc_points(d, tmp_path, FakeEmbedder()))
    ref = tmp_path / "ref.json"
    ref.write_text(json.dumps({"x": "nothing in common with these documents at all, just some other words here"}))
    lock = tmp_path / "lock.json"
    lock.write_text("{}")
    with pytest.raises(LeakageError, match="excluded"):
        run(Manifest(documents=docs), tmp_path, [ref], lock)
    docs[0] = docs[0].model_copy(update={"split": "excluded", "note": "copy"})
    report = run(Manifest(documents=docs), tmp_path, [ref], lock)
    assert report["excluded"] == {"train-doc": "copy"}


def test_excluded_documents_still_count_as_evidence_of_stock_text(tmp_path):
    from finetune import corpus
    from finetune.check_documents import run
    from finetune.schema import Manifest
    from tests.test_finetune_generation import FakeEmbedder, guide_json, make_doc
    stock = "this page was last updated by the department and the contact line is open monday to friday between eight and six"
    docs = [make_doc("train-a"), make_doc("train-b"), make_doc("dropped", "excluded"), make_doc("held-doc", "heldout")]
    docs[2] = docs[2].model_copy(update={"note": "dropped for another reason"})
    for index, d in enumerate(docs):
        (tmp_path / f"{d.id}.json").write_text(json.dumps(guide_json(d.title, [stock, " ".join(f"unique{index}w{j}" for j in range(300))])))
        corpus.write_points(tmp_path / f"{d.id}.points.jsonl", corpus.build_doc_points(d, tmp_path, FakeEmbedder()))
    ref = tmp_path / "ref.json"
    ref.write_text(json.dumps({"x": "nothing in common with these documents at all, just some other words here"}))
    lock = tmp_path / "lock.json"
    lock.write_text("{}")
    # Two training documents plus the excluded one all carry the stock sentence, so it is stock and the held-out doc passes.
    assert run(Manifest(documents=docs), tmp_path, [ref], lock)["stock_ngrams_ignored"] > 0
    # Without the excluded document only two documents carry it, so it is no longer stock and the held-out doc is flagged.
    with pytest.raises(LeakageError):
        run(Manifest(documents=[d for d in docs if d.id != "dropped"]), tmp_path, [ref], lock)


def test_the_shared_prompt_scaffolding_alone_is_not_a_leak(tmp_path):
    """Every evaluation prompt carries the history header, 'Context:' and 'Source marker:' labels. Found on the real
    data: all examples were flagged for those eight-word runs and nothing else."""
    reference = tmp_path / "pack.jsonl"
    other = system(body="Railway timetables change twice a year and platform alterations are announced on the day itself.")
    reference.write_text(json.dumps({"messages": [{"role": "system", "content": other}]}) + "\n")
    index = build_reference_index([reference])
    check_examples([example(GOOD)], index)  # must pass: only the scaffolding is shared
    shared_content = system(body="Railway timetables change twice a year and platform alterations are announced on the day itself.")
    with pytest.raises(LeakageError):  # the same prompt shape with real shared content is still caught
        check_examples([example(GOOD, sys_prompt=shared_content)], index)


def test_stock_text_is_ignored_but_other_shared_text_still_fails(tmp_path):
    from finetune.decontaminate import stock_ngrams, without_stock
    boiler = "this guide is also available in welsh cymraeg and you can ask for another format"
    docs = {f"doc{i}": f"{boiler} plus words unique to document number {i} about something else entirely here" for i in range(3)}
    stock = stock_ngrams(docs)
    reference = tmp_path / "held.json"
    reference.write_text(json.dumps({"held": f"{boiler} and then a long unrelated sentence about held out material only"}))
    index = build_reference_index([reference])
    with pytest.raises(LeakageError):  # without the stock rule the shared boilerplate is flagged
        check_examples([example(GOOD, sys_prompt=system(body=boiler))], index)
    check_examples([example(GOOD, sys_prompt=system(body=boiler))], without_stock(index, stock))
    with pytest.raises(LeakageError):  # real shared content still fails once stock is removed
        leaked = system(body="a long unrelated sentence about held out material only that appears in the reference")
        check_examples([example(GOOD, sys_prompt=leaked)], without_stock(index, stock))


def test_held_out_documents_are_held_to_a_fraction_not_to_zero(tmp_path):
    from finetune.decontaminate import examples_vs_heldout_documents
    shared = "the allowance is paid monthly in arrears directly into the bank account of the person named on the claim form"
    own = " ".join(f"word{i}" for i in range(200))
    held = {"held": f"{shared} {own}"}
    small = examples_vs_heldout_documents([example(GOOD, sys_prompt=system(body=shared))], held, stock=set(), max_fraction=0.5)
    assert 0 < small["held"] < 0.2  # a shared passage is measured and reported
    with pytest.raises(LeakageError, match="above 2%"):  # the default cap is 2%; this passage is about 5% of the document
        examples_vs_heldout_documents([example(GOOD, sys_prompt=system(body=shared))], held, stock=set())
    stock = {h for h in ngram_hashes(shared)}
    assert examples_vs_heldout_documents([example(GOOD, sys_prompt=system(body=shared))], held, stock=stock)["held"] == 0.0


def test_leaking_examples_can_be_split_out_and_the_rest_pass(index):
    from finetune.decontaminate import split_leaking
    clean_one = example(GOOD, question="A different question altogether?")
    leaked = example(GOOD, sys_prompt=system(body=EVAL_CHUNK), question="Another question again?")
    clean, leaks = split_leaking([clean_one, leaked], index)
    assert clean == [clean_one] and [i for i, _, _ in leaks] == [leaked.id]
    check_examples(clean, index)  # what is kept passes the strict check
