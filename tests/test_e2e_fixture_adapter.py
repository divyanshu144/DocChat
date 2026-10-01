

def test_e2e_fixture_adapter_matches_normalized_source_filter():
    from eval.e2e_pipeline import _fixture_search
    from app.agent.nodes.retriever import _retrieval_filter

    hits = _fixture_search("Compare PDF YouTube web ingestion", 24, _retrieval_filter(["web"], []))
    assert hits
    assert all(hit["payload"]["source_type"] == "web" for hit in hits)
