from eval.prepare_quality_workload import _extra_cases


def test_quality_workload_additions_cover_tasks_and_abstention_controls():
    pdf, web = "pdf-source", "web-source"
    chunks = [
        {"id": f"{pdf}-{index}", "payload": {"source_id": pdf}}
        for index in range(3)
    ] + [
        {"id": f"{web}-{index}", "payload": {"source_id": web}}
        for index in range(4)
    ]

    cases = _extra_cases({"pdf": pdf, "web": web}, [pdf, web], chunks)
    assert len(cases) == 16
    assert {case["category"] for case in cases} == {
        "document_qa", "summarisation", "long_context", "multi_document", "negative_control"
    }
    negatives = [case for case in cases if case["category"] == "negative_control"]
    assert len(negatives) == 3
    assert all(case["expected_evidence"] == [] for case in negatives)
    assert all(case["source_ids"] == [pdf, web] for case in negatives)
    assert all(case["split"] == "held_out" for case in cases)
    assert sum(case["category"] == "document_qa" for case in cases) == 6
    assert next(case for case in cases if case["id"] == "multi-document-overview")["expected_evidence"] == [
        "pdf-source-0", "pdf-source-1", "pdf-source-2",
        "web-source-0", "web-source-1", "web-source-2", "web-source-3",
    ]
