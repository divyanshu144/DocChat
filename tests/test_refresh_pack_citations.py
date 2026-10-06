import json

from eval.citations import CITATION_MARKER
from eval.refresh_pack_citations import refresh


def test_marker_matches_sources_not_plain_brackets():
    text = "see [PDF - a.pdf p.1], [Web - x], [YouTube — L @1s] and [26 weeks] or [edit]"
    assert CITATION_MARKER.findall(text) == ["[PDF - a.pdf p.1]", "[Web - x]", "[YouTube — L @1s]"]


def test_refresh_changes_only_false_positives_and_keeps_ids(tmp_path):
    rows = [{"blind_id": "a", "answer": "x [26 weeks]", "emitted_citations": ["[26 weeks]"]},
            {"blind_id": "b", "answer": "y [PDF - a.pdf p.1] [PDF - a.pdf p.1]", "emitted_citations": ["[PDF - a.pdf p.1]"]}]
    before = json.dumps(rows)
    fixed, changed = refresh(rows)
    assert json.dumps(rows) == before
    assert [r["blind_id"] for r in fixed] == ["a", "b"] and fixed[0]["emitted_citations"] == []
    assert fixed[1]["emitted_citations"] == ["[PDF - a.pdf p.1]"]
    assert [c["blind_id"] for c in changed] == ["a"]
