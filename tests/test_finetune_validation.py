"""Format, citation and duplicate rules for generated training examples (finetune/validate_examples.py)."""
import pytest
from pydantic import ValidationError

from finetune.citations import body_markers, cited_markers, context_markers, split_answer
from finetune.schema import Manifest, SourceDoc, TrainingExample
from finetune.validate_examples import (
    SERVING_PREFIX, abstention_rate, check_abstention_rate, dedupe, summarize, validate_example)

M1 = "[Web - Maternity pay]"
M2 = "[PDF - guide.pdf p.3]"


def system(markers=(M1, M2), body="Statutory pay lasts 39 weeks."):
    context = "\n\n---\n\n".join(f"Source marker: {m}\n{body}" for m in markers)
    return SERVING_PREFIX + "Conversation history (oldest to newest, last 10 messages):\nnone\n\nContext:\n" + context + "\n"


def example(answer, *, kind="answerable", question="How long does statutory pay last?", sys_prompt=None, doc="a"):
    messages = [{"role": "system", "content": sys_prompt or system()}, {"role": "user", "content": question},
                {"role": "assistant", "content": answer}]
    return TrainingExample(id=TrainingExample.make_id(messages), split="train", kind=kind, doc_ids=[doc],
                           messages=messages, teacher="test-teacher")


GOOD = f"Statutory pay lasts 39 weeks.\n\nSources:\n\n{M1}"
ABSTAIN = "The context does not contain the requested information about overtime rates."


def test_a_well_formed_answer_passes():
    assert validate_example(example(GOOD)) == []


def test_a_well_formed_abstention_passes():
    assert validate_example(example(ABSTAIN, kind="abstain")) == []


def test_citation_helpers():
    assert context_markers(system()) == [M1, M2]
    assert split_answer(GOOD) == ("Statutory pay lasts 39 weeks.", M1)
    assert split_answer("no section here") == ("no section here", None)
    assert cited_markers(GOOD) == [M1]
    assert body_markers(f"See {M1} for this.\n\nSources:\n{M1}") == [M1]


@pytest.mark.parametrize("answer, expected", [
    ("Statutory pay lasts 39 weeks.\n\nSources:\n\n[Web - Something never supplied]", "not in the context"),
    ("Statutory pay lasts 39 weeks.", "no cited sources"),
    (f"Statutory pay lasts 39 weeks.\n\nSources:\n\n{M1}\n{M1}", "more than once"),
    (f"Statutory pay lasts 39 weeks {M1}.\n\nSources:\n\n{M1}", "body instead of the Sources"),
    (f"**Summary**\n\nPay lasts 39 weeks.\n\nSources:\n\n{M1}", "Markdown"),
    (f"## Summary\n\nPay lasts 39 weeks.\n\nSources:\n\n{M1}", "Markdown"),
    ("", "empty"),
])
def test_bad_answerable_examples_are_rejected(answer, expected):
    assert any(expected in p for p in validate_example(example(answer))), validate_example(example(answer))


def test_abstention_must_not_cite_and_must_say_the_context_lacks_it():
    assert any("cites sources" in p for p in validate_example(example(f"{ABSTAIN}\n\nSources:\n\n{M1}", kind="abstain")))
    assert any("does not say" in p for p in validate_example(example("Overtime is 1.5x.", kind="abstain")))


def test_a_changed_serving_prompt_is_caught():
    stale = system().replace(SERVING_PREFIX, "You are an assistant.\n", 1)
    assert any("serving prompt" in p for p in validate_example(example(GOOD, sys_prompt=stale)))


def test_wrong_message_roles_are_rejected():
    bad = example(GOOD).model_copy(update={"messages": example(GOOD).messages[:2]})
    assert "system, user, assistant" in validate_example(bad)[0]


def test_dedupe_drops_exact_and_near_duplicates_but_keeps_different_documents():
    long_answer = " ".join(f"Statutory pay is paid for week {i} of the leave period." for i in range(1, 9))
    answer = f"{long_answer}\n\nSources:\n\n{M1}"
    a = example(answer)
    near = example(answer.replace("week 3", "week three"), question="How long does statutory pay last for?")
    other_doc = example(answer, doc="b", question="For how many weeks is statutory pay paid?")
    different = example(f"Leave can start 11 weeks before the due date.\n\nSources:\n\n{M1}", question="When can leave start?")
    kept, dropped = dedupe([a, a, near, other_doc, different])
    assert dropped == 2 and [e.doc_ids for e in kept] == [["a"], ["b"], ["a"]]


def test_abstention_rate_bounds():
    ex = [example(GOOD)] * 9 + [example(ABSTAIN, kind="abstain")]
    assert abstention_rate(ex) == 0.1 and check_abstention_rate(ex) == 0.1
    with pytest.raises(ValueError, match="outside"):
        check_abstention_rate([example(GOOD)] * 10)
    with pytest.raises(ValueError, match="outside"):
        check_abstention_rate([example(ABSTAIN, kind="abstain")] * 5 + [example(GOOD)] * 5)
    assert summarize(ex)["by_kind"] == {"answerable": 9, "abstain": 1}


# ---------------- manifest ----------------
def doc(**kw):
    base = dict(id="maternity-pay", title="Maternity pay", kind="govuk_guide", url="https://www.gov.uk/maternity-pay-leave",
                licence="Open Government Licence", licence_url="https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
                split="train")
    return SourceDoc(**{**base, **kw})


def test_manifest_rejects_duplicate_ids_and_urls():
    with pytest.raises(ValidationError, match="unique"):
        Manifest(documents=[doc(), doc(url="https://www.gov.uk/other")])
    with pytest.raises(ValidationError, match="one document cannot sit in two splits"):
        Manifest(documents=[doc(), doc(id="other-id", split="heldout")])


def test_manifest_refuses_the_evaluation_documents():
    with pytest.raises(ValidationError, match="evaluation evidence"):
        doc(url="https://en.wikipedia.org/wiki/Retrieval-augmented_generation")
    with pytest.raises(ValidationError, match="evaluation evidence"):
        doc(title="Maximum weekly working hours")


def test_source_urls_cannot_carry_credentials():
    with pytest.raises(ValidationError):
        doc(url="https://user:pw@example.com/x")
