import warnings
from functools import lru_cache
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, Modifier, SparseVectorParams, VectorParams
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
        # https=False is explicit on purpose: qdrant-client otherwise turns HTTPS on whenever an api_key is
        # given, and the server only speaks plain HTTP, so every call failed with [SSL: WRONG_VERSION_NUMBER]
        # (ingestion on the first real AWS deploy). The raw-HTTP callers (retriever, health) already use http://.
        return QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port,
                            api_key=settings.qdrant_api_key or None, https=False)


# Name of the sparse (BM25) vector next to the unnamed dense vector. Existing collections keep their unnamed
# dense vector, so dense-only code and data written before hybrid retrieval stay valid.
SPARSE_VECTOR_NAME = "bm25"


def get_qdrant_collection(name: str, *, sparse: bool = False) -> None:
    """Ensure collection exists with cosine HNSW index.

    ``sparse=True`` also creates it with the BM25 sparse vector field. IDF is applied by Qdrant at query time
    (``Modifier.IDF``) over the whole collection, so ingesting more sources never requires re-weighting old points.
    An existing collection is left as it is: Qdrant cannot add a sparse field afterwards, see
    ``scripts/migrate_to_hybrid_collection.py``.
    """
    client = get_qdrant_client()
    try:
        client.get_collection(name)
    except Exception:
        kwargs = {}
        if sparse:
            kwargs["sparse_vectors_config"] = {SPARSE_VECTOR_NAME: SparseVectorParams(modifier=Modifier.IDF)}
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=settings.embedding_dim, distance=Distance.COSINE),
            **kwargs,
        )


def collection_has_sparse(name: str) -> bool:
    """True when the collection has the BM25 field, so a point may carry a sparse vector."""
    sparse = get_qdrant_client().get_collection(name).config.params.sparse_vectors or {}
    return SPARSE_VECTOR_NAME in sparse
