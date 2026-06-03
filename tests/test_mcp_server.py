import inspect
import pytest


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
