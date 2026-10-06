import json

import pytest

from eval.score_answer_review_pack import score_review_pack


def test_review_pack_scoring_splits_heldout_from_development(tmp_path):
    rows = [{
        "blind_id": f"blind-{split}", "split": split, "expected_abstention": False,
        "expected_facts": [{"id": "fact-01", "text": "A fact"}],
        "source_markers_in_context": ["[PDF — p.1]"], "emitted_citations": ["[PDF — p.1]"],
        "review": {"abstained": False, "claims": [{"id": "c1", "text": "A fact",
                    "supported": True, "fact_ids": ["fact-01"], "citation_ids": ["[PDF — p.1]"]}]},
    } for split in ("development", "held_out")]
    rows.append({"blind_id": "blind-error", "split": "held_out", "answer_status": "error",
                 "expected_abstention": False, "review": None})
    path = tmp_path / "review.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows))

    report = score_review_pack(path)

    assert report["records"] == 3
    assert report["scored_records"] == 2
    assert report["failed_answers"] == 1
    assert set(report["by_split"]) == {"development", "held_out"}
    assert report["by_split"]["held_out"]["summary"]["unsupported_claim_rate"] == 0


def test_review_pack_refuses_unreviewed_abstention(tmp_path):
    path = tmp_path / "review.jsonl"
    path.write_text(json.dumps({"blind_id": "blind-1", "review": {"abstained": None}}))
    with pytest.raises(ValueError, match="abstained"):
        score_review_pack(path)
