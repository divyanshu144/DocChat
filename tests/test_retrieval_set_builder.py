"""Label-quality gates for the larger retrieval eval set. No network, no LLM."""
from eval import build_retrieval_set_v2 as b


def test_the_quote_must_be_verbatim_and_long_enough():
    text = "The Euro was introduced to financial markets as an accounting currency on 1 January 1999."
    assert b.accept_question("When was the Euro introduced?", "accounting currency on 1 January 1999", text) is None
    assert b.accept_question("When?", "accounting currency on 1 January 1999", text) is None
    assert b.accept_question("When was it?", "introduced in 1998 as cash", text) == "quote not verbatim in chunk"
    assert b.accept_question("When was it?", "Euro", text) == "quote too short"
    assert b.accept_question("Tell me about it", "accounting currency on 1 January 1999", text) == "not a question"


def test_every_chunk_containing_the_quote_is_relevant():
    chunks = [{"id": "a", "text": "x shared overlap sentence here y"}, {"id": "b", "text": "shared overlap sentence here z"},
              {"id": "c", "text": "unrelated"}]
    assert b.relevant_chunks_for_quote("shared overlap sentence here", chunks) == ["a", "b"]


def test_lexical_overlap_measures_shared_content_words():
    chunk = "Marie Curie won the Nobel Prize in Physics in 1903."
    assert b.content_overlap("Who won the Nobel Prize in Physics in 1903?", chunk) == 1.0
    assert b.content_overlap("Which scientist received a famous award?", chunk) == 0.0
    assert b.content_overlap("the of and", chunk) == 0.0


def test_json_is_pulled_out_of_chatty_replies():
    assert b._parse_json('Sure! {"question": "Q?", "quote": "q"} Hope that helps') == {"question": "Q?", "quote": "q"}
    assert b._parse_json("no json here") is None
    assert b._parse_json("{broken") is None
    assert b._parse_json("[1, 2]") is None


def test_both_strata_have_a_prompt():
    for stratum in b.STRATA:
        messages = b._prompt(stratum, "passage text")
        assert "passage text" in messages[1]["content"] and "JSON" in messages[0]["content"]


def test_a_boilerplate_quote_is_not_accepted_as_evidence():
    assert b.MAX_RELEVANT_CHUNKS == 3
    many = [{"id": str(i), "text": "see the Marine Park Authority website"} for i in range(5)]
    assert len(b.relevant_chunks_for_quote("Marine Park Authority", many)) > b.MAX_RELEVANT_CHUNKS
