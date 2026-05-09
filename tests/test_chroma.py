from unittest.mock import MagicMock, patch
from app.core.chroma import get_chroma_client, get_collection


def test_get_chroma_client_returns_singleton():
    with patch("app.core.chroma.chromadb.HttpClient") as mock_cls:
        mock_cls.return_value = MagicMock()
        get_chroma_client.cache_clear()
        c1 = get_chroma_client()
        c2 = get_chroma_client()
        assert c1 is c2
        assert mock_cls.call_count == 1
        get_chroma_client.cache_clear()


def test_get_collection_uses_cosine_space():
    mock_collection = MagicMock()
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection

    with patch("app.core.chroma.get_chroma_client", return_value=mock_client):
        result = get_collection("pdf_chunks")

    mock_client.get_or_create_collection.assert_called_once_with(
        name="pdf_chunks",
        metadata={"hnsw:space": "cosine"},
    )
    assert result is mock_collection
