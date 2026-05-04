---
type: community
cohesion: 0.16
members: 20
---

# LateChunkingEmbedder / .embed_query()

**Cohesion:** 0.16 - loosely connected
**Members:** 20 nodes

## Members
- [[.__init__()_1]] - code - app/services/embedder.py
- [[._run()]] - code - app/services/embedder.py
- [[.embed_independently()]] - code - app/services/embedder.py
- [[.embed_late()]] - code - app/services/embedder.py
- [[.embed_query()]] - code - app/services/embedder.py
- [[Attention-mask-weighted mean pooling (batch, seq, dim) → (batch, dim).]] - rationale - app/services/embedder.py
- [[Embed each text in isolation — standard fallback, no late chunking.]] - rationale - app/services/embedder.py
- [[Group chunks by their source segment and embed each group with late chunking.]] - rationale - app/services/ingestion.py
- [[Late chunking embed the full segment_text at token level, then         extract]] - rationale - app/services/embedder.py
- [[Late-chunking ONNX embedder.  Standard fastembed pools the entire chunk independ]] - rationale - app/services/embedder.py
- [[LateChunkingEmbedder]] - code - app/services/embedder.py
- [[ONNX-based embedder with late-chunking support for document ingestion.]] - rationale - app/services/embedder.py
- [[Run ONNX session; returns last_hidden_state (batch, seq, dim).]] - rationale - app/services/embedder.py
- [[Set FASTEMBED_CACHE_PATH to a persistent directory if not already set.      fast]] - rationale - app/services/embedder.py
- [[Standard mean-pooled embedding for a single query string.]] - rationale - app/services/embedder.py
- [[_embed_chunks_late()]] - code - app/services/ingestion.py
- [[_mean_pool()]] - code - app/services/embedder.py
- [[_normalize()]] - code - app/services/embedder.py
- [[_pin_cache()]] - code - app/services/embedder.py
- [[embedder.py]] - code - app/services/embedder.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/LateChunkingEmbedder_/_.embed_query()
SORT file.name ASC
```

## Connections to other communities
- 9 edges to [[_COMMUNITY_Document  DocumentStatus]]
- 4 edges to [[_COMMUNITY_benchmark.py  ingest_document()]]
- 2 edges to [[_COMMUNITY__Segment  _chunk_segments()]]
- 1 edge to [[_COMMUNITY_retrieval.py  retrieve_chunks()]]

## Top bridge nodes
- [[LateChunkingEmbedder]] - degree 13, connects to 3 communities
- [[_embed_chunks_late()]] - degree 5, connects to 2 communities
- [[.embed_query()]] - degree 8, connects to 1 community
- [[.embed_late()]] - degree 7, connects to 1 community
- [[embedder.py]] - degree 6, connects to 1 community