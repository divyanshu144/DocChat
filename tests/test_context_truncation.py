import pytest
from app.core.config import settings


@pytest.mark.parametrize("node_name,formatter", [("synthesizer", "_format_chunks"), ("grounding", "_format_context")])
def test_partial_chunk_retains_space_free_body(node_name, formatter, monkeypatch):
    from importlib import import_module

    node = import_module(f"app.agent.nodes.{node_name}")
    monkeypatch.setattr(settings, "context_max_chars", 600)
    result = getattr(node, formatter)([{
        "text": "b" * 1000, "source_type": "pdf", "metadata": {"filename": "doc.pdf"}
    }])
    assert "b" * 500 in result
    assert "doc.pdf" in result
    assert len(result) <= 600
