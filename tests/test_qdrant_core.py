from unittest.mock import MagicMock, patch
from qdrant_client.models import VectorParams, Distance


def test_get_qdrant_client_returns_singleton():
    with patch("app.core.qdrant.QdrantClient") as mock_cls:
        mock_cls.return_value = MagicMock()
        from app.core.qdrant import get_qdrant_client
        get_qdrant_client.cache_clear()
        c1 = get_qdrant_client()
        c2 = get_qdrant_client()
        assert c1 is c2
        assert mock_cls.call_count == 1
        get_qdrant_client.cache_clear()


def test_get_qdrant_collection_creates_if_missing():
    mock_client = MagicMock()
    mock_client.get_collection.side_effect = Exception("not found")

    with patch("app.core.qdrant.get_qdrant_client", return_value=mock_client):
        from app.core.qdrant import get_qdrant_collection
        get_qdrant_collection("pdf_chunks")

    mock_client.create_collection.assert_called_once_with(
        collection_name="pdf_chunks",
        vectors_config=VectorParams(size=384, distance=Distance.COSINE),
    )


def test_get_qdrant_collection_skips_create_if_exists():
    mock_client = MagicMock()
    mock_client.get_collection.return_value = MagicMock()

    with patch("app.core.qdrant.get_qdrant_client", return_value=mock_client):
        from app.core.qdrant import get_qdrant_collection
        get_qdrant_collection("pdf_chunks")

    mock_client.create_collection.assert_not_called()
