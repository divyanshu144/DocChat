---
type: community
cohesion: 0.06
members: 48
---

# retrieve_chunks / ingest_document

**Cohesion:** 0.06 - loosely connected
**Members:** 48 nodes

## Members
- [[LRU retrieval cache (L1)]] - code - app/services/retrieval.py
- [[LateChunkingEmbedder class]] - code - app/services/embedder.py
- [[LateChunkingEmbedder.embed_independently]] - code - app/services/embedder.py
- [[LateChunkingEmbedder.embed_late]] - code - app/services/embedder.py
- [[LateChunkingEmbedder.embed_query]] - code - app/services/embedder.py
- [[Redis retrieval cache (L2)]] - code - app/services/retrieval.py
- [[SemanticCache class]] - code - app/services/semantic_cache.py
- [[_build_cache_entry]] - code - app/services/retrieval.py
- [[_build_messages]] - code - app/services/chat.py
- [[_chunk_segments]] - code - app/services/ingestion.py
- [[_cosine_similarities]] - code - app/services/retrieval.py
- [[_detect_pdf_heading]] - code - app/services/ingestion.py
- [[_embed_chunks_late]] - code - app/services/ingestion.py
- [[_extract_docx_segments]] - code - app/services/ingestion.py
- [[_extract_pdf_segments]] - code - app/services/ingestion.py
- [[_extract_segments]] - code - app/services/ingestion.py
- [[_format_chunk metadata prefix]] - code - app/services/retrieval.py
- [[_get_client Groq singleton]] - code - app/services/chat.py
- [[_get_ranker singleton]] - code - app/services/reranker.py
- [[_get_splitter]] - code - app/services/ingestion.py
- [[_load_embedding_blob float16float32 auto-detect]] - code - app/services/retrieval.py
- [[_load_history]] - code - app/api/conversations.py
- [[_mean_pool attention-mask pooling]] - code - app/services/embedder.py
- [[_normalize L2 normalization]] - code - app/services/embedder.py
- [[_pin_cache fastembed cache path]] - code - app/services/embedder.py
- [[_rrf Reciprocal Rank Fusion]] - code - app/services/retrieval.py
- [[_run_retrieval_pipeline]] - code - app/api/conversations.py
- [[_tokenize NLTK stemmer]] - code - app/services/retrieval.py
- [[delete_file]] - code - app/services/storage.py
- [[download_for_processing]] - code - app/services/storage.py
- [[embed_query]] - code - app/services/retrieval.py
- [[event_stream SSE generator]] - code - app/api/conversations.py
- [[expand_query_hyde]] - code - app/services/chat.py
- [[generate_reply]] - code - app/services/chat.py
- [[generate_reply_stream]] - code - app/services/chat.py
- [[get_embedder singleton]] - code - app/services/embedder.py
- [[get_semantic_cache singleton]] - code - app/services/semantic_cache.py
- [[ingest_document]] - code - app/services/ingestion.py
- [[ingest_document_task ARQ task]] - code - app/workers/tasks.py
- [[invalidate_bm25]] - code - app/services/retrieval.py
- [[invalidate_semantic_cache]] - code - app/services/semantic_cache.py
- [[rerank]] - code - app/services/reranker.py
- [[retrieve_chunks]] - code - app/services/retrieval.py
- [[send_message endpoint]] - code - app/api/conversations.py
- [[send_message_stream endpoint]] - code - app/api/conversations.py
- [[summarize_history]] - code - app/services/chat.py
- [[test_chat.py_1]] - code - tests/test_chat.py
- [[test_sse_framing.py_1]] - code - tests/test_sse_framing.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/retrieve_chunks_/_ingest_document
SORT file.name ASC
```
