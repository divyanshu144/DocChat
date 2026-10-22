import warnings
from functools import lru_cache
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams
from app.core.config import settings


def qdrant_headers() -> dict[str, str]:
    """Headers for the code that calls Qdrant over raw HTTP (retriever search, health probe)."""
    return {"api-key": settings.qdrant_api_key} if settings.qdrant_api_key else {}


@lru_cache()
def get_qdrant_client() -> QdrantClient:
    with warnings.catch_warnings():
        # The key travels over plain HTTP inside private subnets by design (docs/aws/security.md); the
        # client's per-process "insecure connection" warning would only add noise.
        warnings.filterwarnings("ignore", message="Api key is used with an insecure connection")
        return QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port,
                            api_key=settings.qdrant_api_key or None)


def get_qdrant_collection(name: str) -> None:
    """Ensure collection exists with cosine HNSW index."""
    client = get_qdrant_client()
    try:
        client.get_collection(name)
    except Exception:
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=settings.embedding_dim, distance=Distance.COSINE),
        )
