---
type: community
cohesion: 0.12
members: 28
---

# retrieval.py / retrieve_chunks()

**Cohesion:** 0.12 - loosely connected
**Members:** 28 nodes

## Members
- [[.get()]] - code - app/services/semantic_cache.py
- [[ARQ task ingest a document by ID using its own DB session.]] - rationale - app/workers/tasks.py
- [[ARQ worker tasks for background document ingestion.  Start the worker with]] - rationale - app/workers/tasks.py
- [[CachedChunk]] - code - app/services/retrieval.py
- [[Embed a single query string; returns None if the embedder is unavailable.]] - rationale - app/services/retrieval.py
- [[Prefix chunk text with page  section metadata for LLM grounding.]] - rationale - app/services/retrieval.py
- [[Return a cached answer if one exists within cosine threshold, else None.]] - rationale - app/services/semantic_cache.py
- [[Return top-k chunk texts (with metadata prefix) using hybrid BM25 + semantic RRF]] - rationale - app/services/retrieval.py
- [[Returns the LateChunkingEmbedder singleton, or None if unavailable.]] - rationale - app/services/retrieval.py
- [[WorkerSettings]] - code - app/workers/tasks.py
- [[_build_cache_entry()]] - code - app/services/retrieval.py
- [[_cosine_similarities()]] - code - app/services/retrieval.py
- [[_deserialize_from_redis()]] - code - app/services/retrieval.py
- [[_format_chunk()]] - code - app/services/retrieval.py
- [[_get_embedder()]] - code - app/services/retrieval.py
- [[_get_redis_client()]] - code - app/services/retrieval.py
- [[_load_embedding_blob()]] - code - app/services/retrieval.py
- [[_redis_cache_delete()]] - code - app/services/retrieval.py
- [[_redis_cache_get()]] - code - app/services/retrieval.py
- [[_redis_cache_set()]] - code - app/services/retrieval.py
- [[_rrf()]] - code - app/services/retrieval.py
- [[_serialize_for_redis()]] - code - app/services/retrieval.py
- [[_tokenize()]] - code - app/services/retrieval.py
- [[embed_query()]] - code - app/services/retrieval.py
- [[ingest_document_task()]] - code - app/workers/tasks.py
- [[retrieval.py]] - code - app/services/retrieval.py
- [[retrieve_chunks()]] - code - app/services/retrieval.py
- [[tasks.py]] - code - app/workers/tasks.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/retrieval.py_/_retrieve_chunks()
SORT file.name ASC
```

## Connections to other communities
- 13 edges to [[_COMMUNITY_benchmark.py  ingest_document()]]
- 11 edges to [[_COMMUNITY_Document  DocumentStatus]]
- 2 edges to [[_COMMUNITY__Segment  _chunk_segments()]]
- 2 edges to [[_COMMUNITY_SemanticCache  get_semantic_cache()]]
- 1 edge to [[_COMMUNITY_documents.py  FileTooLargeError]]
- 1 edge to [[_COMMUNITY_LateChunkingEmbedder  .embed_query()]]

## Top bridge nodes
- [[.get()]] - degree 15, connects to 6 communities
- [[retrieve_chunks()]] - degree 15, connects to 2 communities
- [[retrieval.py]] - degree 17, connects to 1 community
- [[_redis_cache_get()]] - degree 6, connects to 1 community
- [[_get_embedder()]] - degree 5, connects to 1 community