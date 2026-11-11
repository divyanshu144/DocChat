"""Mapping production retriever output (text only) back to point ids for scoring."""
from eval import live_retrieval_ab as ab


def test_texts_map_back_to_point_ids_in_order():
    ids = {"alpha": ["a"], "beta": ["b"]}
    assert ab.ids_for_chunks([{"text": "beta"}, {"text": "alpha"}], ids, {"a"}) == ["b", "a"]


def test_a_text_shared_by_several_points_resolves_to_the_relevant_one():
    ids = {"boiler": ["x", "y"]}
    assert ab.ids_for_chunks([{"text": "boiler"}], ids, {"y"}) == ["y"]
    assert ab.ids_for_chunks([{"text": "boiler"}], ids, {"z"}) == ["x"]


def test_unmapped_text_never_matches_a_relevant_id():
    ranked = ab.ids_for_chunks([{"text": "unknown"}], {}, {"a"})
    assert ranked == ["unmapped:0"] and ab.ranking_row(ranked, ["a"])["recall@5"] == 0.0


def test_ranking_row_scores_rank_and_recall():
    row = ab.ranking_row(["n", "a", "m"], ["a", "q"])
    assert row["reciprocal_rank"] == 0.5 and row["recall@1"] == 0.0 and row["recall@3"] == 0.5
