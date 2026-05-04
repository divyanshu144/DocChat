---
type: community
cohesion: 0.29
members: 10
---

# SemanticCache / get_semantic_cache()

**Cohesion:** 0.29 - loosely connected
**Members:** 10 nodes

## Members
- [[.__init__()]] - code - app/services/semantic_cache.py
- [[.invalidate()]] - code - app/services/semantic_cache.py
- [[Delete all cached answers for a document (call after re-ingestion).]] - rationale - app/services/semantic_cache.py
- [[Module-level helper — evicts cached answers for a document from Redis.]] - rationale - app/services/semantic_cache.py
- [[Redis-backed semantic cache for RAG answers.  Stores (query_embedding, answer) p]] - rationale - app/services/semantic_cache.py
- [[SemanticCache]] - code - app/services/semantic_cache.py
- [[_key()]] - code - app/services/semantic_cache.py
- [[get_semantic_cache()]] - code - app/services/semantic_cache.py
- [[invalidate_semantic_cache()]] - code - app/services/semantic_cache.py
- [[semantic_cache.py]] - code - app/services/semantic_cache.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/SemanticCache_/_get_semantic_cache()
SORT file.name ASC
```

## Connections to other communities
- 5 edges to [[_COMMUNITY_benchmark.py  ingest_document()]]
- 2 edges to [[_COMMUNITY_Document  DocumentStatus]]
- 2 edges to [[_COMMUNITY_retrieval.py  retrieve_chunks()]]

## Top bridge nodes
- [[SemanticCache]] - degree 7, connects to 2 communities
- [[get_semantic_cache()]] - degree 6, connects to 2 communities
- [[_key()]] - degree 4, connects to 2 communities
- [[invalidate_semantic_cache()]] - degree 5, connects to 1 community