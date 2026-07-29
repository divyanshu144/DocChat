import inspect
import json
import pytest
from unittest.mock import MagicMock, patch
from qdrant_client.http.exceptions import UnexpectedResponse


def test_mcp_server_imports_without_stdout(capsys):
    """Importing mcp_server must not write to stdout — it would corrupt the stdio JSON-RPC channel."""
    import app.mcp_server  # noqa: F401
    captured = capsys.readouterr()
    assert captured.out == "", f"unexpected stdout on import: {captured.out!r}"


def test_all_three_tools_are_async_callables():
    from app.mcp_server import query_documents, ingest_document, list_documents
    assert inspect.iscoroutinefunction(query_documents), "query_documents must be async"
    assert inspect.iscoroutinefunction(ingest_document), "ingest_document must be async"
    assert inspect.iscoroutinefunction(list_documents), "list_documents must be async"


@pytest.mark.asyncio
async def test_list_documents_returns_empty_json_array_when_collections_missing():
    """list_documents must return '[]' (valid JSON array) when all collections return 404."""
    mock_client = MagicMock()
    mock_client.scroll.side_effect = UnexpectedResponse(
        status_code=404, reason_phrase="Not Found", content=b"", headers={}
    )

    with patch("app.core.qdrant.get_qdrant_client", return_value=mock_client):
        from app.mcp_server import list_documents
        result = await list_documents()

    parsed = json.loads(result)
    assert parsed == [], f"expected empty list, got {parsed!r}"
