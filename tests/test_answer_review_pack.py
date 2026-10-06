import json

from eval.build_answer_review_pack import build_pack
from eval.workloads import Message, WorkloadCase, Workloads


def test_review_pack_blinds_model_and_pairs_answer_with_exact_context(tmp_path):
    workload_path = tmp_path / "workload.json"
    workload = Workloads(corpus_sha256="a" * 64, cases=[WorkloadCase(
        id="qa-1", category="document_qa", query="Question?", source_ids=["source"],
        messages=[Message(role="system", content="Context:\nSource marker: [PDF — p.1]\nEvidence")],
        expected_facts=["48 hours"], expected_evidence=["chunk-1"],
    )])
    workload_path.write_text(workload.model_dump_json())
    answers_path = tmp_path / "answers.jsonl"
    answers_path.write_text(json.dumps({"case_id": "qa-1", "model": "private-model-name",
                                       "status": "ok", "answer": "48 hours.\nSources:\n[PDF — p.1]"}) + "\n")

    pack, key = build_pack(workload_path, [answers_path])

    assert len(pack) == len(key) == 1
    assert pack[0]["context"].endswith("Evidence")
    assert pack[0]["expected_facts"] == [{"id": "fact-01", "text": "48 hours"}]
    assert pack[0]["source_markers_in_context"] == ["[PDF — p.1]"]
    assert "private-model-name" not in json.dumps(pack[0])
    assert key[0]["model"] == "private-model-name"
