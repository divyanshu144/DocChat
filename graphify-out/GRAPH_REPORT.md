# Graph Report - .  (2026-05-01)

## Corpus Check
- Corpus is ~22,184 words - fits in a single context window. You may not need a graph.

## Summary
- 481 nodes · 854 edges · 57 communities detected
- Extraction: 66% EXTRACTED · 34% INFERRED · 0% AMBIGUOUS · INFERRED: 291 edges (avg confidence: 0.64)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Document  DocumentStatus|Document / DocumentStatus]]
- [[_COMMUNITY_retrieve_chunks  ingest_document|retrieve_chunks / ingest_document]]
- [[_COMMUNITY_benchmark.py  ingest_document()|benchmark.py / ingest_document()]]
- [[_COMMUNITY_RAG Pipeline Architecture (README)  DocChat Benchmarking Suite|RAG Pipeline Architecture (README) / DocChat Benchmarking Suite]]
- [[_COMMUNITY_Settings (pydantic-settings singleton)  create_all_tables()|Settings (pydantic-settings singleton) / create_all_tables()]]
- [[_COMMUNITY_retrieval.py  retrieve_chunks()|retrieval.py / retrieve_chunks()]]
- [[_COMMUNITY_generate_reply()  test_chat.py|generate_reply() / test_chat.py]]
- [[_COMMUNITY_TestSseFraming  _sse_frame()|TestSseFraming / _sse_frame()]]
- [[_COMMUNITY_app.js  api()|app.js / api()]]
- [[_COMMUNITY__Segment  _chunk_segments()|_Segment / _chunk_segments()]]
- [[_COMMUNITY_LateChunkingEmbedder  .embed_query()|LateChunkingEmbedder / .embed_query()]]
- [[_COMMUNITY_documents.py  FileTooLargeError|documents.py / FileTooLargeError]]
- [[_COMMUNITY_database.py  main.py|database.py / main.py]]
- [[_COMMUNITY_SemanticCache  get_semantic_cache()|SemanticCache / get_semantic_cache()]]
- [[_COMMUNITY_Ingestion Test Suite  Bug 3 (High) _chunk_segments blocks ev|Ingestion Test Suite / Bug #3 (High): _chunk_segments blocks ev]]
- [[_COMMUNITY_Settings  config.py|Settings / config.py]]
- [[_COMMUNITY_arq =0.25.0 (Redis task queue)  redisasyncio =5.0.0|arq >=0.25.0 (Redis task queue) / redis[asyncio] >=5.0.0]]
- [[_COMMUNITY_require_api_key()  security.py|require_api_key() / security.py]]
- [[_COMMUNITY_health_check()  Health check endpoint to verify that the|health_check() / Health check endpoint to verify that the]]
- [[_COMMUNITY_SQLAlchemyasyncio 2.0.46  Bug 11 (Low) debug=True default echoes|SQLAlchemy[asyncio] 2.0.46 / Bug #11 (Low): debug=True default echoes]]
- [[_COMMUNITY_Project Conventions and Workflow Rules (  Plan Mode Default Convention|Project Conventions and Workflow Rules ( / Plan Mode Default Convention]]
- [[_COMMUNITY_metrics.py  Prometheus metrics for DocChat.  Exposes|metrics.py / Prometheus metrics for DocChat.  Exposes]]
- [[_COMMUNITY_ingestion_chunks (Counter)  ingestion_duration (Histogram)|ingestion_chunks (Counter) / ingestion_duration (Histogram)]]
- [[_COMMUNITY_semantic_cache_hits (Counter)  semantic_cache_misses (Counter)|semantic_cache_hits (Counter) / semantic_cache_misses (Counter)]]
- [[_COMMUNITY__Segment dataclass  CachedChunk dataclass|_Segment dataclass / CachedChunk dataclass]]
- [[_COMMUNITY_get_conversation endpoint  test_conversations_incomplete.py|get_conversation endpoint / test_conversations_incomplete.py]]
- [[_COMMUNITY_FastAPI 0.104.1  uvicornstandard 0.24.0|FastAPI 0.104.1 / uvicorn[standard] 0.24.0]]
- [[_COMMUNITY_Architectural Gap Orphaned incomplete m  Bug 4 (High) get_conversation exposes|Architectural Gap: Orphaned incomplete m / Bug #4 (High): get_conversation exposes ]]
- [[_COMMUNITY_Architectural Gap No DELETE endpoints f  Roadmap Feature Document and Conversati|Architectural Gap: No DELETE endpoints f / Roadmap Feature: Document and Conversati]]
- [[_COMMUNITY_Architectural Gap No Authentication — a  Roadmap Feature API Key Authentication|Architectural Gap: No Authentication — a / Roadmap Feature: API Key Authentication]]
- [[_COMMUNITY_Uploaded Document Hello World Test File  Uploaded Document Python Language Intro|Uploaded Document: Hello World Test File / Uploaded Document: Python Language Intro]]
- [[_COMMUNITY_log_requests (HTTP middleware)|log_requests (HTTP middleware)]]
- [[_COMMUNITY_root() — serves index.html|root() — serves index.html]]
- [[_COMMUNITY_retrieval_duration (Histogram)|retrieval_duration (Histogram)]]
- [[_COMMUNITY_rerank_duration (Histogram)|rerank_duration (Histogram)]]
- [[_COMMUNITY_llm_duration (Histogram)|llm_duration (Histogram)]]
- [[_COMMUNITY_llm_stream_duration (Histogram)|llm_stream_duration (Histogram)]]
- [[_COMMUNITY_hyde_expansions (Counter)|hyde_expansions (Counter)]]
- [[_COMMUNITY_Conversations API Router|Conversations API Router]]
- [[_COMMUNITY_create_conversation endpoint|create_conversation endpoint]]
- [[_COMMUNITY_list_conversations endpoint|list_conversations endpoint]]
- [[_COMMUNITY_WorkerSettings ARQ config|WorkerSettings ARQ config]]
- [[_COMMUNITY_save_upload|save_upload]]
- [[_COMMUNITY_Python Dependency Manifest (requirements|Python Dependency Manifest (requirements]]
- [[_COMMUNITY_groq SDK =0.9.0|groq SDK >=0.9.0]]
- [[_COMMUNITY_numpy =1.26.0|numpy >=1.26.0]]
- [[_COMMUNITY_pytesseract =0.3.10 (OCR fallback)|pytesseract >=0.3.10 (OCR fallback)]]
- [[_COMMUNITY_prometheus-client =0.20.0|prometheus-client >=0.20.0]]
- [[_COMMUNITY_cachetools =5.3.0 (LRU cache)|cachetools >=5.3.0 (LRU cache)]]
- [[_COMMUNITY_slowapi =0.1.9 (rate limiting)|slowapi >=0.1.9 (rate limiting)]]
- [[_COMMUNITY_aioboto3 =12.0.0 (S3 async client)|aioboto3 >=12.0.0 (S3 async client)]]
- [[_COMMUNITY_Bug 5 (Medium) File fully written befo|Bug #5 (Medium): File fully written befo]]
- [[_COMMUNITY_Bug 9 (Low) Semantic cache FIFO evicti|Bug #9 (Low): Semantic cache FIFO evicti]]
- [[_COMMUNITY_Bug 12 (Low) np.ndarray annotation wit|Bug #12 (Low): np.ndarray annotation wit]]
- [[_COMMUNITY_Architectural Gap max_tokens=1024 hardc|Architectural Gap: max_tokens=1024 hardc]]
- [[_COMMUNITY_Roadmap Feature Source Citations in Ans|Roadmap Feature: Source Citations in Ans]]
- [[_COMMUNITY_Uploaded Document Smoke Test Content|Uploaded Document: Smoke Test Content]]

## God Nodes (most connected - your core abstractions)
1. `Document` - 34 edges
2. `DocumentStatus` - 28 edges
3. `Chunk` - 23 edges
4. `Message` - 22 edges
5. `Conversation` - 21 edges
6. `MessageRole` - 19 edges
7. `ConversationResponse` - 17 edges
8. `ingest_document()` - 17 edges
9. `Base` - 16 edges
10. `MessageResponse` - 16 edges

## Surprising Connections (you probably didn't know these)
- `langchain-text-splitters >=0.2.0` --semantically_similar_to--> `Hybrid Retrieval (BM25 + Semantic + RRF)`  [INFERRED] [semantically similar]
  requirements.txt → README.md
- `Bug #13 (Medium): History summarization injects a second system message` --semantically_similar_to--> `HyDE (Hypothetical Document Embedding)`  [AMBIGUOUS] [semantically similar]
  reports/docchat-audit.md → README.md
- `Bug #3 (High): _chunk_segments blocks event loop` --references--> `Ingestion Test Suite`  [EXTRACTED]
  reports/docchat-audit.md → tests/test_ingestion.py
- `DocChat Benchmarking Suite` --references--> `fastembed >=0.3.0 (ONNX BAAI/bge-small-en-v1.5)`  [EXTRACTED]
  scripts/benchmark.py → requirements.txt
- `Ingestion Speed Benchmark` --benchmarks--> `Background Ingestion (BackgroundTasks or ARQ)`  [INFERRED]
  scripts/benchmark.py → README.md

## Hyperedges (group relationships)
- **App Startup Initialization Flow** — main_lifespan, database_createalltables, database_runmigrations [EXTRACTED 1.00]
- **Document Upload and Ingestion Pipeline** — documents_uploaddocument, documents_enqueueingest, documents_runingestionbg [EXTRACTED 1.00]
- **SQLAlchemy ORM Model Hierarchy (Document → Chunk + Conversation → Message)** — models_document, models_chunk, models_conversation [EXTRACTED 1.00]
- **Full RAG Pipeline: ingestion → retrieval → rerank → chat** — ingestion_ingest_document, retrieval_retrieve_chunks, reranker_rerank, chat_generate_reply [EXTRACTED 1.00]
- **Semantic Cache Integration: embed_query → cache lookup → retrieval bypass** — retrieval_embed_query, semantic_cache_semantic_cache, conversations_send_message [EXTRACTED 1.00]
- **Background Ingest: ARQ worker vs BackgroundTasks path both call ingest_document** — tasks_ingest_document_task, ingestion_ingest_document, retrieval_invalidate_bm25 [EXTRACTED 0.95]
- **RAG Retrieval Pipeline: Hybrid BM25 + Semantic + RRF + FlashRank** — concept_hybrid_retrieval, dep_rank_bm25, dep_fastembed, dep_flashrank, dep_nltk [EXTRACTED 1.00]
- **Benchmark Suite: Five Performance Dimensions Measured** — benchmark_ingestion_speed, benchmark_retrieval_latency, benchmark_reranking_precision, benchmark_semantic_cache, benchmark_document_scale [EXTRACTED 1.00]
- **Critical Bugs: SSE Newline Drop + None Content + Event Loop Block** — audit_bug1_none_content, audit_bug2_sse_newline, audit_bug3_chunk_segments_blocking [EXTRACTED 1.00]

## Communities

### Community 0 - "Document / DocumentStatus"
Cohesion: 0.12
Nodes (51): ChatRequest, ChatResponse, ConversationCreate, ConversationResponse, ConversationSummary, create_conversation(), get_conversation(), list_conversations() (+43 more)

### Community 1 - "retrieve_chunks / ingest_document"
Cohesion: 0.06
Nodes (46): _build_messages, expand_query_hyde, generate_reply, generate_reply_stream, _get_client Groq singleton, summarize_history, event_stream SSE generator, _load_history (+38 more)

### Community 2 - "benchmark.py / ingest_document()"
Cohesion: 0.11
Nodes (35): log_requests(), Exception, _create_doc_record(), _fmt_bytes(), _fmt_ms(), _generate_pdf(), _hr(), _json_default() (+27 more)

### Community 3 - "RAG Pipeline Architecture (README) / DocChat Benchmarking Suite"
Cohesion: 0.07
Nodes (35): Architectural Gap: Linear semantic cache scan O(n) per query, Architectural Gap: No index on messages.conversation_id (full table scan), Bug #10 (Low): Health check status mismatch — API returns 'healthy', JS checks 'ok', Bug #13 (Medium): History summarization injects a second system message, Bug #14 (Medium): Conversation.messages order_by uses invalid SQLAlchemy 2.x string form, Bug #1 (Critical): generate_reply returns None crashes DB write, Bug #2 (Critical): SSE newline-in-token silently drops content, Bug #6 (Medium): Semantic cache checked after retrieval — defeats its purpose (+27 more)

### Community 4 - "Settings (pydantic-settings singleton) / create_all_tables()"
Cohesion: 0.1
Nodes (30): get_settings() — lru_cache factory, Settings (pydantic-settings singleton), AsyncSessionLocal (session factory), Base (DeclarativeBase), create_all_tables(), async SQLAlchemy engine, get_db() — async session dependency, _run_migrations() — idempotent column migrations (+22 more)

### Community 5 - "retrieval.py / retrieve_chunks()"
Cohesion: 0.12
Nodes (25): _build_cache_entry(), CachedChunk, _cosine_similarities(), _deserialize_from_redis(), embed_query(), _format_chunk(), _get_embedder(), _get_redis_client() (+17 more)

### Community 6 - "generate_reply() / test_chat.py"
Cohesion: 0.11
Nodes (25): _build_messages(), expand_query_hyde(), generate_reply(), generate_reply_stream(), _get_client(), Call Groq LLM with retrieved context and conversation history., Stream Groq LLM tokens as an async generator., Generate a hypothetical document passage to improve semantic retrieval (HyDE). (+17 more)

### Community 7 - "TestSseFraming / _sse_frame()"
Cohesion: 0.11
Nodes (14): Tests for Bug #2 — SSE framing: multi-line tokens must produce one data: line pe, A token with no newlines produces the classic 'data: <text>\\n\\n' frame., A token containing one newline must produce two data: lines., A token with two newlines produces three data: lines., A trailing newline in the token results in a trailing empty data: line., An empty token string produces a single empty data: line., Every frame must end with \\n\\n so SSE clients recognise the event boundary., [DONE] sentinel uses literal string — verify its format is correct. (+6 more)

### Community 8 - "app.js / api()"
Cohesion: 0.16
Nodes (19): api(), checkHealth(), docIcon(), downloadChat(), esc(), formatDate(), handleUpload(), msgBubble() (+11 more)

### Community 9 - "_Segment / _chunk_segments()"
Cohesion: 0.16
Nodes (20): _chunk_segments(), _detect_pdf_heading(), _extract_docx_segments(), _extract_pdf_segments(), _extract_segments(), _get_splitter(), _Segment, Tests for Bug #3 fix: _chunk_segments runs safely off the event loop.  _chunk_se (+12 more)

### Community 10 - "LateChunkingEmbedder / .embed_query()"
Cohesion: 0.16
Nodes (14): LateChunkingEmbedder, _mean_pool(), _normalize(), _pin_cache(), Late-chunking ONNX embedder.  Standard fastembed pools the entire chunk independ, Standard mean-pooled embedding for a single query string., Embed each text in isolation — standard fallback, no late chunking., Late chunking: embed the full segment_text at token level, then         extract (+6 more)

### Community 11 - "documents.py / FileTooLargeError"
Cohesion: 0.15
Nodes (14): _enqueue_ingestion(), Strip path components and limit to safe characters., Run ingestion in a background task (non-ARQ path)., _run_ingestion_bg(), _sanitize_filename(), upload_document(), delete_file(), FileTooLargeError (+6 more)

### Community 12 - "database.py / main.py"
Cohesion: 0.2
Nodes (7): lifespan(), metrics(), Prometheus metrics endpoint — protected by API key., create_all_tables(), Add missing columns to existing tables (safe to call on every startup)., _run_migrations(), _set_wal_mode()

### Community 13 - "SemanticCache / get_semantic_cache()"
Cohesion: 0.29
Nodes (7): get_semantic_cache(), invalidate_semantic_cache(), _key(), Redis-backed semantic cache for RAG answers.  Stores (query_embedding, answer) p, Delete all cached answers for a document (call after re-ingestion)., Module-level helper — evicts cached answers for a document from Redis., SemanticCache

### Community 14 - "Ingestion Test Suite / Bug #3 (High): _chunk_segments blocks ev"
Cohesion: 0.25
Nodes (8): Bug #3 (High): _chunk_segments blocks event loop, test_chunk_segments_basic, test_chunk_segments_chunk_dict_keys, test_chunk_segments_empty_input, test_chunk_segments_no_empty_text, test_chunk_segments_preserves_metadata, test_chunk_segments_whitespace_only_skipped, Ingestion Test Suite

### Community 15 - "Settings / config.py"
Cohesion: 0.33
Nodes (5): BaseSettings, get_settings(), Application configuration settings loaded from environment variables or .env fil, Get the application settings, cached for performance., Settings

### Community 16 - "arq >=0.25.0 (Redis task queue) / redis[asyncio] >=5.0.0"
Cohesion: 0.5
Nodes (4): Bug #8 (Medium): redis[asyncio] missing from requirements.txt, arq >=0.25.0 (Redis task queue), redis[asyncio] >=5.0.0, Horizontal Scaling Architecture

### Community 17 - "require_api_key() / security.py"
Cohesion: 0.67
Nodes (2): FastAPI dependency that enforces API key auth when API_KEY is configured.      W, require_api_key()

### Community 18 - "health_check() / Health check endpoint to verify that the"
Cohesion: 0.67
Nodes (2): health_check(), Health check endpoint to verify that the API is running.

### Community 19 - "SQLAlchemy[asyncio] 2.0.46 / Bug #11 (Low): debug=True default echoes"
Cohesion: 0.67
Nodes (3): Bug #11 (Low): debug=True default echoes all SQL in production, aiosqlite 0.19.0, SQLAlchemy[asyncio] 2.0.46

### Community 20 - "Project Conventions and Workflow Rules ( / Plan Mode Default Convention"
Cohesion: 0.67
Nodes (3): Project Conventions and Workflow Rules (CLAUDE.md), Plan Mode Default Convention, Task Management Workflow (todo.md + lessons.md)

### Community 21 - "metrics.py / Prometheus metrics for DocChat.  Exposes"
Cohesion: 1.0
Nodes (1): Prometheus metrics for DocChat.  Exposes counters and histograms for the key pip

### Community 22 - "ingestion_chunks (Counter) / ingestion_duration (Histogram)"
Cohesion: 1.0
Nodes (2): ingestion_chunks (Counter), ingestion_duration (Histogram)

### Community 23 - "semantic_cache_hits (Counter) / semantic_cache_misses (Counter)"
Cohesion: 1.0
Nodes (2): semantic_cache_hits (Counter), semantic_cache_misses (Counter)

### Community 24 - "_Segment dataclass / CachedChunk dataclass"
Cohesion: 1.0
Nodes (2): _Segment dataclass, CachedChunk dataclass

### Community 25 - "get_conversation endpoint / test_conversations_incomplete.py"
Cohesion: 1.0
Nodes (1): get_conversation endpoint

### Community 26 - "FastAPI 0.104.1 / uvicorn[standard] 0.24.0"
Cohesion: 1.0
Nodes (2): FastAPI 0.104.1, uvicorn[standard] 0.24.0

### Community 27 - "Architectural Gap: Orphaned incomplete m / Bug #4 (High): get_conversation exposes "
Cohesion: 1.0
Nodes (2): Architectural Gap: Orphaned incomplete messages never cleaned up on restart, Bug #4 (High): get_conversation exposes is_complete=False messages

### Community 28 - "Architectural Gap: No DELETE endpoints f / Roadmap Feature: Document and Conversati"
Cohesion: 1.0
Nodes (2): Architectural Gap: No DELETE endpoints for documents/conversations, Roadmap Feature: Document and Conversation Deletion

### Community 29 - "Architectural Gap: No Authentication — a / Roadmap Feature: API Key Authentication"
Cohesion: 1.0
Nodes (2): Architectural Gap: No Authentication — all endpoints public, Roadmap Feature: API Key Authentication

### Community 30 - "Uploaded Document: Hello World Test File / Uploaded Document: Python Language Intro"
Cohesion: 1.0
Nodes (2): Uploaded Document: Hello World Test File, Uploaded Document: Python Language Introduction

### Community 39 - "log_requests (HTTP middleware)"
Cohesion: 1.0
Nodes (1): log_requests (HTTP middleware)

### Community 40 - "root() — serves index.html"
Cohesion: 1.0
Nodes (1): root() — serves index.html

### Community 41 - "retrieval_duration (Histogram)"
Cohesion: 1.0
Nodes (1): retrieval_duration (Histogram)

### Community 42 - "rerank_duration (Histogram)"
Cohesion: 1.0
Nodes (1): rerank_duration (Histogram)

### Community 43 - "llm_duration (Histogram)"
Cohesion: 1.0
Nodes (1): llm_duration (Histogram)

### Community 44 - "llm_stream_duration (Histogram)"
Cohesion: 1.0
Nodes (1): llm_stream_duration (Histogram)

### Community 45 - "hyde_expansions (Counter)"
Cohesion: 1.0
Nodes (1): hyde_expansions (Counter)

### Community 46 - "Conversations API Router"
Cohesion: 1.0
Nodes (1): Conversations API Router

### Community 47 - "create_conversation endpoint"
Cohesion: 1.0
Nodes (1): create_conversation endpoint

### Community 48 - "list_conversations endpoint"
Cohesion: 1.0
Nodes (1): list_conversations endpoint

### Community 49 - "WorkerSettings ARQ config"
Cohesion: 1.0
Nodes (1): WorkerSettings ARQ config

### Community 50 - "save_upload"
Cohesion: 1.0
Nodes (1): save_upload

### Community 51 - "Python Dependency Manifest (requirements"
Cohesion: 1.0
Nodes (1): Python Dependency Manifest (requirements.txt)

### Community 52 - "groq SDK >=0.9.0"
Cohesion: 1.0
Nodes (1): groq SDK >=0.9.0

### Community 53 - "numpy >=1.26.0"
Cohesion: 1.0
Nodes (1): numpy >=1.26.0

### Community 54 - "pytesseract >=0.3.10 (OCR fallback)"
Cohesion: 1.0
Nodes (1): pytesseract >=0.3.10 (OCR fallback)

### Community 55 - "prometheus-client >=0.20.0"
Cohesion: 1.0
Nodes (1): prometheus-client >=0.20.0

### Community 56 - "cachetools >=5.3.0 (LRU cache)"
Cohesion: 1.0
Nodes (1): cachetools >=5.3.0 (LRU cache)

### Community 57 - "slowapi >=0.1.9 (rate limiting)"
Cohesion: 1.0
Nodes (1): slowapi >=0.1.9 (rate limiting)

### Community 58 - "aioboto3 >=12.0.0 (S3 async client)"
Cohesion: 1.0
Nodes (1): aioboto3 >=12.0.0 (S3 async client)

### Community 59 - "Bug #5 (Medium): File fully written befo"
Cohesion: 1.0
Nodes (1): Bug #5 (Medium): File fully written before size limit check; orphaned file on OSError

### Community 60 - "Bug #9 (Low): Semantic cache FIFO evicti"
Cohesion: 1.0
Nodes (1): Bug #9 (Low): Semantic cache FIFO eviction is actually random (hkeys unordered)

### Community 61 - "Bug #12 (Low): np.ndarray annotation wit"
Cohesion: 1.0
Nodes (1): Bug #12 (Low): np.ndarray annotation without module-level numpy import

### Community 62 - "Architectural Gap: max_tokens=1024 hardc"
Cohesion: 1.0
Nodes (1): Architectural Gap: max_tokens=1024 hardcoded in chat service

### Community 63 - "Roadmap Feature: Source Citations in Ans"
Cohesion: 1.0
Nodes (1): Roadmap Feature: Source Citations in Answers

### Community 64 - "Uploaded Document: Smoke Test Content"
Cohesion: 1.0
Nodes (1): Uploaded Document: Smoke Test Content

## Ambiguous Edges - Review These
- `Bug #13 (Medium): History summarization injects a second system message` → `HyDE (Hypothetical Document Embedding)`  [AMBIGUOUS]
  reports/docchat-audit.md · relation: semantically_similar_to
- `Uploaded Document: Python Language Introduction` → `Uploaded Document: Hello World Test File`  [AMBIGUOUS]
  uploads/92ffe249-ed99-4c98-a04c-63b444b1a57d.txt · relation: semantically_similar_to

## Knowledge Gaps
- **150 isolated node(s):** `Prometheus metrics endpoint — protected by API key.`, `Prometheus metrics for DocChat.  Exposes counters and histograms for the key pip`, `Application configuration settings loaded from environment variables or .env fil`, `Get the application settings, cached for performance.`, `Add missing columns to existing tables (safe to call on every startup).` (+145 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `require_api_key() / security.py`** (3 nodes): `security.py`, `FastAPI dependency that enforces API key auth when API_KEY is configured.      W`, `require_api_key()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `health_check() / Health check endpoint to verify that the`** (3 nodes): `health_check()`, `Health check endpoint to verify that the API is running.`, `health.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `metrics.py / Prometheus metrics for DocChat.  Exposes`** (2 nodes): `metrics.py`, `Prometheus metrics for DocChat.  Exposes counters and histograms for the key pip`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `ingestion_chunks (Counter) / ingestion_duration (Histogram)`** (2 nodes): `ingestion_chunks (Counter)`, `ingestion_duration (Histogram)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `semantic_cache_hits (Counter) / semantic_cache_misses (Counter)`** (2 nodes): `semantic_cache_hits (Counter)`, `semantic_cache_misses (Counter)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `_Segment dataclass / CachedChunk dataclass`** (2 nodes): `_Segment dataclass`, `CachedChunk dataclass`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `get_conversation endpoint / test_conversations_incomplete.py`** (2 nodes): `get_conversation endpoint`, `test_conversations_incomplete.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `FastAPI 0.104.1 / uvicorn[standard] 0.24.0`** (2 nodes): `FastAPI 0.104.1`, `uvicorn[standard] 0.24.0`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Architectural Gap: Orphaned incomplete m / Bug #4 (High): get_conversation exposes `** (2 nodes): `Architectural Gap: Orphaned incomplete messages never cleaned up on restart`, `Bug #4 (High): get_conversation exposes is_complete=False messages`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Architectural Gap: No DELETE endpoints f / Roadmap Feature: Document and Conversati`** (2 nodes): `Architectural Gap: No DELETE endpoints for documents/conversations`, `Roadmap Feature: Document and Conversation Deletion`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Architectural Gap: No Authentication — a / Roadmap Feature: API Key Authentication`** (2 nodes): `Architectural Gap: No Authentication — all endpoints public`, `Roadmap Feature: API Key Authentication`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Uploaded Document: Hello World Test File / Uploaded Document: Python Language Intro`** (2 nodes): `Uploaded Document: Hello World Test File`, `Uploaded Document: Python Language Introduction`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `log_requests (HTTP middleware)`** (1 nodes): `log_requests (HTTP middleware)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `root() — serves index.html`** (1 nodes): `root() — serves index.html`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `retrieval_duration (Histogram)`** (1 nodes): `retrieval_duration (Histogram)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `rerank_duration (Histogram)`** (1 nodes): `rerank_duration (Histogram)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `llm_duration (Histogram)`** (1 nodes): `llm_duration (Histogram)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `llm_stream_duration (Histogram)`** (1 nodes): `llm_stream_duration (Histogram)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `hyde_expansions (Counter)`** (1 nodes): `hyde_expansions (Counter)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Conversations API Router`** (1 nodes): `Conversations API Router`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `create_conversation endpoint`** (1 nodes): `create_conversation endpoint`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `list_conversations endpoint`** (1 nodes): `list_conversations endpoint`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `WorkerSettings ARQ config`** (1 nodes): `WorkerSettings ARQ config`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `save_upload`** (1 nodes): `save_upload`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Python Dependency Manifest (requirements`** (1 nodes): `Python Dependency Manifest (requirements.txt)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `groq SDK >=0.9.0`** (1 nodes): `groq SDK >=0.9.0`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `numpy >=1.26.0`** (1 nodes): `numpy >=1.26.0`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `pytesseract >=0.3.10 (OCR fallback)`** (1 nodes): `pytesseract >=0.3.10 (OCR fallback)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `prometheus-client >=0.20.0`** (1 nodes): `prometheus-client >=0.20.0`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `cachetools >=5.3.0 (LRU cache)`** (1 nodes): `cachetools >=5.3.0 (LRU cache)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `slowapi >=0.1.9 (rate limiting)`** (1 nodes): `slowapi >=0.1.9 (rate limiting)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `aioboto3 >=12.0.0 (S3 async client)`** (1 nodes): `aioboto3 >=12.0.0 (S3 async client)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Bug #5 (Medium): File fully written befo`** (1 nodes): `Bug #5 (Medium): File fully written before size limit check; orphaned file on OSError`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Bug #9 (Low): Semantic cache FIFO evicti`** (1 nodes): `Bug #9 (Low): Semantic cache FIFO eviction is actually random (hkeys unordered)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Bug #12 (Low): np.ndarray annotation wit`** (1 nodes): `Bug #12 (Low): np.ndarray annotation without module-level numpy import`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Architectural Gap: max_tokens=1024 hardc`** (1 nodes): `Architectural Gap: max_tokens=1024 hardcoded in chat service`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Roadmap Feature: Source Citations in Ans`** (1 nodes): `Roadmap Feature: Source Citations in Answers`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Uploaded Document: Smoke Test Content`** (1 nodes): `Uploaded Document: Smoke Test Content`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `Bug #13 (Medium): History summarization injects a second system message` and `HyDE (Hypothetical Document Embedding)`?**
  _Edge tagged AMBIGUOUS (relation: semantically_similar_to) - confidence is low._
- **What is the exact relationship between `Uploaded Document: Python Language Introduction` and `Uploaded Document: Hello World Test File`?**
  _Edge tagged AMBIGUOUS (relation: semantically_similar_to) - confidence is low._
- **Why does `send_message()` connect `Document / DocumentStatus` to `benchmark.py / ingest_document()`, `retrieval.py / retrieve_chunks()`, `generate_reply() / test_chat.py`, `LateChunkingEmbedder / .embed_query()`, `SemanticCache / get_semantic_cache()`?**
  _High betweenness centrality (0.047) - this node is a cross-community bridge._
- **Why does `generate_reply()` connect `generate_reply() / test_chat.py` to `Document / DocumentStatus`?**
  _High betweenness centrality (0.037) - this node is a cross-community bridge._
- **Why does `Document` connect `Document / DocumentStatus` to `benchmark.py / ingest_document()`, `retrieval.py / retrieve_chunks()`, `_Segment / _chunk_segments()`, `LateChunkingEmbedder / .embed_query()`, `documents.py / FileTooLargeError`?**
  _High betweenness centrality (0.030) - this node is a cross-community bridge._
- **Are the 32 inferred relationships involving `Document` (e.g. with `Base` and `DocumentResponse`) actually correct?**
  _`Document` has 32 INFERRED edges - model-reasoned connections that need verification._
- **Are the 26 inferred relationships involving `DocumentStatus` (e.g. with `Base` and `DocumentResponse`) actually correct?**
  _`DocumentStatus` has 26 INFERRED edges - model-reasoned connections that need verification._
- **Are the 21 inferred relationships involving `Chunk` (e.g. with `Base` and `_Segment`) actually correct?**
  _`Chunk` has 21 INFERRED edges - model-reasoned connections that need verification._