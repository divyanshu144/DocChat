from eval.rag_harness import CASES, CORPUS, _format_context, _score


def test_rag_harness_scores_required_terms_and_source_recall():
    case = CASES[0]
    answer = "DocChat uses BAAI/bge-small-en-v1.5 and produces 384-dimensional vectors."

    missing, forbidden, source_recall, passed = _score(case, answer, [CORPUS[0]])

    assert missing == []
    assert forbidden == []
    assert source_recall == 1.0
    assert passed is True


def test_rag_harness_fails_for_missing_terms_and_forbidden_hits():
    case = CASES[0]
    answer = "DocChat uses OpenAI embeddings with 768 dimensions."

    missing, forbidden, source_recall, passed = _score(case, answer, [])

    assert missing
    assert "768" in forbidden
    assert source_recall == 0.0
    assert passed is False


def test_rag_harness_context_contains_source_ids():
    context = _format_context([CORPUS[0]])

    assert "Source ID: architecture-pdf" in context
    assert "Source type: pdf" in context
