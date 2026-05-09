import numpy as np
from unittest.mock import MagicMock, patch
from app.services.embedder import get_embedder


def test_get_embedder_returns_singleton():
    import app.services.embedder as emb_mod
    emb_mod._embedder_instance = None

    mock_fe = MagicMock()
    mock_fe.embed.return_value = iter([np.array([0.1] * 384, dtype="float32")])

    with patch("app.services.embedder.TextEmbedding", return_value=mock_fe):
        e1 = get_embedder()
        e2 = get_embedder()

    assert e1 is e2
    emb_mod._embedder_instance = None


def test_embed_query_returns_ndarray():
    import app.services.embedder as emb_mod
    emb_mod._embedder_instance = None

    mock_fe = MagicMock()
    mock_fe.embed.return_value = iter([np.array([0.1] * 384, dtype="float32")])

    with patch("app.services.embedder.TextEmbedding", return_value=mock_fe):
        embedder = get_embedder()

    mock_fe.embed.return_value = iter([np.array([0.2] * 384, dtype="float32")])
    result = embedder.embed_query("hello world")
    assert isinstance(result, np.ndarray)
    assert result.shape == (384,)
    emb_mod._embedder_instance = None


def test_get_embedder_returns_none_on_import_error():
    import app.services.embedder as emb_mod
    emb_mod._embedder_instance = None

    with patch("app.services.embedder.TextEmbedding", side_effect=ImportError("no fastembed")):
        result = get_embedder()

    assert result is None
    emb_mod._embedder_instance = None
