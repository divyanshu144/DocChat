# Graph Report - .  (2026-05-13)

## Corpus Check
- Corpus is ~33,015 words - fits in a single context window. You may not need a graph.

## Summary
- 440 nodes · 631 edges · 53 communities detected
- Extraction: 79% EXTRACTED · 20% INFERRED · 0% AMBIGUOUS · INFERRED: 129 edges (avg confidence: 0.73)
- Token cost: 12,800 input · 3,200 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Chat & Folder API|Chat & Folder API]]
- [[_COMMUNITY_Chat Service & LLM|Chat Service & LLM]]
- [[_COMMUNITY_Frontend App|Frontend App]]
- [[_COMMUNITY_Audit Findings|Audit Findings]]
- [[_COMMUNITY_Core Infrastructure|Core Infrastructure]]
- [[_COMMUNITY_LangGraph Agent Nodes|LangGraph Agent Nodes]]
- [[_COMMUNITY_Retrieval & Embedding|Retrieval & Embedding]]
- [[_COMMUNITY_Ingest API & ChromaDB|Ingest API & ChromaDB]]
- [[_COMMUNITY_YouTube Ingestion|YouTube Ingestion]]
- [[_COMMUNITY_App Startup & Middleware|App Startup & Middleware]]
- [[_COMMUNITY_PDF & DOCX Ingestion|PDF & DOCX Ingestion]]
- [[_COMMUNITY_Chunk Ingestion Tests|Chunk Ingestion Tests]]
- [[_COMMUNITY_App Configuration|App Configuration]]
- [[_COMMUNITY_LangGraph Graph Builder|LangGraph Graph Builder]]
- [[_COMMUNITY_Async Task Queue|Async Task Queue]]
- [[_COMMUNITY_Health Check|Health Check]]
- [[_COMMUNITY_Database Dependencies|Database Dependencies]]
- [[_COMMUNITY_Dev Workflow Conventions|Dev Workflow Conventions]]
- [[_COMMUNITY_Ingestion Metrics|Ingestion Metrics]]
- [[_COMMUNITY_Semantic Cache Metrics|Semantic Cache Metrics]]
- [[_COMMUNITY_Conversation Detail|Conversation Detail]]
- [[_COMMUNITY_Data Dataclasses|Data Dataclasses]]
- [[_COMMUNITY_Web Framework|Web Framework]]
- [[_COMMUNITY_Message Lifecycle Bugs|Message Lifecycle Bugs]]
- [[_COMMUNITY_Deletion Roadmap|Deletion Roadmap]]
- [[_COMMUNITY_Auth Roadmap|Auth Roadmap]]
- [[_COMMUNITY_Uploaded Documents|Uploaded Documents]]
- [[_COMMUNITY_HTTP Logging Middleware|HTTP Logging Middleware]]
- [[_COMMUNITY_Static File Serving|Static File Serving]]
- [[_COMMUNITY_Retrieval Metrics|Retrieval Metrics]]
- [[_COMMUNITY_Rerank Metrics|Rerank Metrics]]
- [[_COMMUNITY_LLM Latency Metrics|LLM Latency Metrics]]
- [[_COMMUNITY_LLM Stream Metrics|LLM Stream Metrics]]
- [[_COMMUNITY_HyDE Metrics|HyDE Metrics]]
- [[_COMMUNITY_Conversations Router|Conversations Router]]
- [[_COMMUNITY_Create Conversation|Create Conversation]]
- [[_COMMUNITY_List Conversations|List Conversations]]
- [[_COMMUNITY_ARQ Worker Config|ARQ Worker Config]]
- [[_COMMUNITY_File Storage|File Storage]]
- [[_COMMUNITY_Python Dependencies|Python Dependencies]]
- [[_COMMUNITY_Groq SDK|Groq SDK]]
- [[_COMMUNITY_NumPy|NumPy]]
- [[_COMMUNITY_OCR Dependency|OCR Dependency]]
- [[_COMMUNITY_Prometheus Client|Prometheus Client]]
- [[_COMMUNITY_LRU Cache Library|LRU Cache Library]]
- [[_COMMUNITY_Rate Limiting|Rate Limiting]]
- [[_COMMUNITY_S3 Async Client|S3 Async Client]]
- [[_COMMUNITY_File Size Bug|File Size Bug]]
- [[_COMMUNITY_Cache Eviction Bug|Cache Eviction Bug]]
- [[_COMMUNITY_Type Annotation Bug|Type Annotation Bug]]
- [[_COMMUNITY_Hardcoded Token Limit|Hardcoded Token Limit]]
- [[_COMMUNITY_Citation Roadmap|Citation Roadmap]]
- [[_COMMUNITY_Test Upload Content|Test Upload Content]]

## God Nodes (most connected - your core abstractions)
1. `Conversation` - 18 edges
2. `Base` - 14 edges
3. `main()` - 13 edges
4. `apiFetch()` - 12 edges
5. `get_embedder()` - 12 edges
6. `init()` - 10 edges
7. `ingest_youtube()` - 10 edges
8. `get_collection()` - 9 edges
9. `esc()` - 9 edges
10. `sendMessage()` - 9 edges

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

### Community 0 - "Chat & Folder API"
Cohesion: 0.07
Nodes (48): AgentState, chat(), ChatRequest, ConversationMove, create_folder(), FolderCreate, FolderRename, UrlRequest (+40 more)

### Community 1 - "Chat Service & LLM"
Cohesion: 0.06
Nodes (46): _build_messages, expand_query_hyde, generate_reply, generate_reply_stream, _get_client Groq singleton, summarize_history, event_stream SSE generator, _load_history (+38 more)

### Community 2 - "Frontend App"
Cohesion: 0.1
Nodes (39): apiFetch(), appendStoredMessage(), appendToken(), appendUserMessage(), checkHealth(), closeConvMenu(), convItemHtml(), deleteSource() (+31 more)

### Community 3 - "Audit Findings"
Cohesion: 0.07
Nodes (35): Architectural Gap: Linear semantic cache scan O(n) per query, Architectural Gap: No index on messages.conversation_id (full table scan), Bug #10 (Low): Health check status mismatch — API returns 'healthy', JS checks 'ok', Bug #13 (Medium): History summarization injects a second system message, Bug #14 (Medium): Conversation.messages order_by uses invalid SQLAlchemy 2.x string form, Bug #1 (Critical): generate_reply returns None crashes DB write, Bug #2 (Critical): SSE newline-in-token silently drops content, Bug #6 (Medium): Semantic cache checked after retrieval — defeats its purpose (+27 more)

### Community 4 - "Core Infrastructure"
Cohesion: 0.1
Nodes (30): get_settings() — lru_cache factory, Settings (pydantic-settings singleton), AsyncSessionLocal (session factory), Base (DeclarativeBase), create_all_tables(), async SQLAlchemy engine, get_db() — async session dependency, _run_migrations() — idempotent column migrations (+22 more)

### Community 5 - "LangGraph Agent Nodes"
Cohesion: 0.13
Nodes (19): critic_node(), planner_node(), _format_chunks(), synthesizer_node(), chat_complete(), chat_stream(), _get_client(), _base_state() (+11 more)

### Community 6 - "Retrieval & Embedding"
Cohesion: 0.12
Nodes (17): _embed_chunks_late(), retriever_node(), _Embedder, get_embedder(), Embedding service using fastembed (BAAI/bge-small-en-v1.5, 384-dim).  Provides a, Lazy-init singleton. Returns None if fastembed fails to load., Thin fastembed wrapper with a stable public API., Embed a single string. Returns float32 ndarray shape (dim,). (+9 more)

### Community 7 - "Ingest API & ChromaDB"
Cohesion: 0.11
Nodes (19): delete_source(), ingest_pdf_endpoint(), ingest_web_endpoint(), ingest_youtube_endpoint(), IngestResponse, list_sources(), get_chroma_client(), get_collection() (+11 more)

### Community 8 - "YouTube Ingestion"
Cohesion: 0.24
Nodes (8): _chunk_transcript(), _extract_video_id(), ingest_youtube(), Fetch YouTube transcript, chunk, embed, and store in ChromaDB. Returns source_id, test_chunk_transcript_groups_by_duration(), test_extract_video_id_from_short_url(), test_extract_video_id_from_watch_url(), test_ingest_youtube_stores_chunks()

### Community 9 - "App Startup & Middleware"
Cohesion: 0.22
Nodes (3): lifespan(), log_requests(), create_all_tables()

### Community 10 - "PDF & DOCX Ingestion"
Cohesion: 0.5
Nodes (7): _chunk_segments(), _detect_pdf_heading(), _extract_docx_segments(), _extract_pdf_segments(), _extract_segments(), _get_splitter(), _Segment

### Community 11 - "Chunk Ingestion Tests"
Cohesion: 0.25
Nodes (8): Bug #3 (High): _chunk_segments blocks event loop, test_chunk_segments_basic, test_chunk_segments_chunk_dict_keys, test_chunk_segments_empty_input, test_chunk_segments_no_empty_text, test_chunk_segments_preserves_metadata, test_chunk_segments_whitespace_only_skipped, Ingestion Test Suite

### Community 15 - "App Configuration"
Cohesion: 0.67
Nodes (3): BaseSettings, get_settings(), Settings

### Community 16 - "LangGraph Graph Builder"
Cohesion: 0.67
Nodes (2): build_graph(), _configure_langsmith()

### Community 18 - "Async Task Queue"
Cohesion: 0.5
Nodes (4): Bug #8 (Medium): redis[asyncio] missing from requirements.txt, arq >=0.25.0 (Redis task queue), redis[asyncio] >=5.0.0, Horizontal Scaling Architecture

### Community 19 - "Health Check"
Cohesion: 0.67
Nodes (2): health_check(), Health check endpoint to verify that the API is running.

### Community 21 - "Database Dependencies"
Cohesion: 0.67
Nodes (3): Bug #11 (Low): debug=True default echoes all SQL in production, aiosqlite 0.19.0, SQLAlchemy[asyncio] 2.0.46

### Community 22 - "Dev Workflow Conventions"
Cohesion: 0.67
Nodes (3): Project Conventions and Workflow Rules (CLAUDE.md), Plan Mode Default Convention, Task Management Workflow (todo.md + lessons.md)

### Community 25 - "Ingestion Metrics"
Cohesion: 1.0
Nodes (2): ingestion_chunks (Counter), ingestion_duration (Histogram)

### Community 26 - "Semantic Cache Metrics"
Cohesion: 1.0
Nodes (2): semantic_cache_hits (Counter), semantic_cache_misses (Counter)

### Community 27 - "Conversation Detail"
Cohesion: 1.0
Nodes (1): get_conversation endpoint

### Community 28 - "Data Dataclasses"
Cohesion: 1.0
Nodes (2): _Segment dataclass, CachedChunk dataclass

### Community 29 - "Web Framework"
Cohesion: 1.0
Nodes (2): FastAPI 0.104.1, uvicorn[standard] 0.24.0

### Community 30 - "Message Lifecycle Bugs"
Cohesion: 1.0
Nodes (2): Architectural Gap: Orphaned incomplete messages never cleaned up on restart, Bug #4 (High): get_conversation exposes is_complete=False messages

### Community 31 - "Deletion Roadmap"
Cohesion: 1.0
Nodes (2): Architectural Gap: No DELETE endpoints for documents/conversations, Roadmap Feature: Document and Conversation Deletion

### Community 32 - "Auth Roadmap"
Cohesion: 1.0
Nodes (2): Architectural Gap: No Authentication — all endpoints public, Roadmap Feature: API Key Authentication

### Community 33 - "Uploaded Documents"
Cohesion: 1.0
Nodes (2): Uploaded Document: Hello World Test File, Uploaded Document: Python Language Introduction

### Community 43 - "HTTP Logging Middleware"
Cohesion: 1.0
Nodes (1): log_requests (HTTP middleware)

### Community 44 - "Static File Serving"
Cohesion: 1.0
Nodes (1): root() — serves index.html

### Community 45 - "Retrieval Metrics"
Cohesion: 1.0
Nodes (1): retrieval_duration (Histogram)

### Community 46 - "Rerank Metrics"
Cohesion: 1.0
Nodes (1): rerank_duration (Histogram)

### Community 47 - "LLM Latency Metrics"
Cohesion: 1.0
Nodes (1): llm_duration (Histogram)

### Community 48 - "LLM Stream Metrics"
Cohesion: 1.0
Nodes (1): llm_stream_duration (Histogram)

### Community 49 - "HyDE Metrics"
Cohesion: 1.0
Nodes (1): hyde_expansions (Counter)

### Community 50 - "Conversations Router"
Cohesion: 1.0
Nodes (1): Conversations API Router

### Community 51 - "Create Conversation"
Cohesion: 1.0
Nodes (1): create_conversation endpoint

### Community 52 - "List Conversations"
Cohesion: 1.0
Nodes (1): list_conversations endpoint

### Community 53 - "ARQ Worker Config"
Cohesion: 1.0
Nodes (1): WorkerSettings ARQ config

### Community 54 - "File Storage"
Cohesion: 1.0
Nodes (1): save_upload

### Community 55 - "Python Dependencies"
Cohesion: 1.0
Nodes (1): Python Dependency Manifest (requirements.txt)

### Community 56 - "Groq SDK"
Cohesion: 1.0
Nodes (1): groq SDK >=0.9.0

### Community 57 - "NumPy"
Cohesion: 1.0
Nodes (1): numpy >=1.26.0

### Community 58 - "OCR Dependency"
Cohesion: 1.0
Nodes (1): pytesseract >=0.3.10 (OCR fallback)

### Community 59 - "Prometheus Client"
Cohesion: 1.0
Nodes (1): prometheus-client >=0.20.0

### Community 60 - "LRU Cache Library"
Cohesion: 1.0
Nodes (1): cachetools >=5.3.0 (LRU cache)

### Community 61 - "Rate Limiting"
Cohesion: 1.0
Nodes (1): slowapi >=0.1.9 (rate limiting)

### Community 62 - "S3 Async Client"
Cohesion: 1.0
Nodes (1): aioboto3 >=12.0.0 (S3 async client)

### Community 63 - "File Size Bug"
Cohesion: 1.0
Nodes (1): Bug #5 (Medium): File fully written before size limit check; orphaned file on OSError

### Community 64 - "Cache Eviction Bug"
Cohesion: 1.0
Nodes (1): Bug #9 (Low): Semantic cache FIFO eviction is actually random (hkeys unordered)

### Community 65 - "Type Annotation Bug"
Cohesion: 1.0
Nodes (1): Bug #12 (Low): np.ndarray annotation without module-level numpy import

### Community 66 - "Hardcoded Token Limit"
Cohesion: 1.0
Nodes (1): Architectural Gap: max_tokens=1024 hardcoded in chat service

### Community 67 - "Citation Roadmap"
Cohesion: 1.0
Nodes (1): Roadmap Feature: Source Citations in Answers

### Community 68 - "Test Upload Content"
Cohesion: 1.0
Nodes (1): Uploaded Document: Smoke Test Content

## Ambiguous Edges - Review These
- `Bug #13 (Medium): History summarization injects a second system message` → `HyDE (Hypothetical Document Embedding)`  [AMBIGUOUS]
  reports/docchat-audit.md · relation: semantically_similar_to
- `Uploaded Document: Python Language Introduction` → `Uploaded Document: Hello World Test File`  [AMBIGUOUS]
  uploads/92ffe249-ed99-4c98-a04c-63b444b1a57d.txt · relation: semantically_similar_to

## Knowledge Gaps
- **101 isolated node(s):** `Health check endpoint to verify that the API is running.`, `Embedding service using fastembed (BAAI/bge-small-en-v1.5, 384-dim).  Provides a`, `Lazy-init singleton. Returns None if fastembed fails to load.`, `Thin fastembed wrapper with a stable public API.`, `Embed a single string. Returns float32 ndarray shape (dim,).` (+96 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `LangGraph Graph Builder`** (4 nodes): `build_graph()`, `_configure_langsmith()`, `_route_critic()`, `graph.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Health Check`** (3 nodes): `health_check()`, `Health check endpoint to verify that the API is running.`, `health.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Ingestion Metrics`** (2 nodes): `ingestion_chunks (Counter)`, `ingestion_duration (Histogram)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Semantic Cache Metrics`** (2 nodes): `semantic_cache_hits (Counter)`, `semantic_cache_misses (Counter)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Conversation Detail`** (2 nodes): `get_conversation endpoint`, `test_conversations_incomplete.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Data Dataclasses`** (2 nodes): `_Segment dataclass`, `CachedChunk dataclass`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Web Framework`** (2 nodes): `FastAPI 0.104.1`, `uvicorn[standard] 0.24.0`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Message Lifecycle Bugs`** (2 nodes): `Architectural Gap: Orphaned incomplete messages never cleaned up on restart`, `Bug #4 (High): get_conversation exposes is_complete=False messages`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Deletion Roadmap`** (2 nodes): `Architectural Gap: No DELETE endpoints for documents/conversations`, `Roadmap Feature: Document and Conversation Deletion`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Auth Roadmap`** (2 nodes): `Architectural Gap: No Authentication — all endpoints public`, `Roadmap Feature: API Key Authentication`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Uploaded Documents`** (2 nodes): `Uploaded Document: Hello World Test File`, `Uploaded Document: Python Language Introduction`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `HTTP Logging Middleware`** (1 nodes): `log_requests (HTTP middleware)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Static File Serving`** (1 nodes): `root() — serves index.html`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Retrieval Metrics`** (1 nodes): `retrieval_duration (Histogram)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Rerank Metrics`** (1 nodes): `rerank_duration (Histogram)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `LLM Latency Metrics`** (1 nodes): `llm_duration (Histogram)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `LLM Stream Metrics`** (1 nodes): `llm_stream_duration (Histogram)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `HyDE Metrics`** (1 nodes): `hyde_expansions (Counter)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Conversations Router`** (1 nodes): `Conversations API Router`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Create Conversation`** (1 nodes): `create_conversation endpoint`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `List Conversations`** (1 nodes): `list_conversations endpoint`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `ARQ Worker Config`** (1 nodes): `WorkerSettings ARQ config`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `File Storage`** (1 nodes): `save_upload`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Python Dependencies`** (1 nodes): `Python Dependency Manifest (requirements.txt)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Groq SDK`** (1 nodes): `groq SDK >=0.9.0`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `NumPy`** (1 nodes): `numpy >=1.26.0`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `OCR Dependency`** (1 nodes): `pytesseract >=0.3.10 (OCR fallback)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Prometheus Client`** (1 nodes): `prometheus-client >=0.20.0`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `LRU Cache Library`** (1 nodes): `cachetools >=5.3.0 (LRU cache)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Rate Limiting`** (1 nodes): `slowapi >=0.1.9 (rate limiting)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `S3 Async Client`** (1 nodes): `aioboto3 >=12.0.0 (S3 async client)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `File Size Bug`** (1 nodes): `Bug #5 (Medium): File fully written before size limit check; orphaned file on OSError`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Cache Eviction Bug`** (1 nodes): `Bug #9 (Low): Semantic cache FIFO eviction is actually random (hkeys unordered)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Type Annotation Bug`** (1 nodes): `Bug #12 (Low): np.ndarray annotation without module-level numpy import`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Hardcoded Token Limit`** (1 nodes): `Architectural Gap: max_tokens=1024 hardcoded in chat service`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Citation Roadmap`** (1 nodes): `Roadmap Feature: Source Citations in Answers`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Test Upload Content`** (1 nodes): `Uploaded Document: Smoke Test Content`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `Bug #13 (Medium): History summarization injects a second system message` and `HyDE (Hypothetical Document Embedding)`?**
  _Edge tagged AMBIGUOUS (relation: semantically_similar_to) - confidence is low._
- **What is the exact relationship between `Uploaded Document: Python Language Introduction` and `Uploaded Document: Hello World Test File`?**
  _Edge tagged AMBIGUOUS (relation: semantically_similar_to) - confidence is low._
- **Why does `get_embedder()` connect `Retrieval & Embedding` to `YouTube Ingestion`, `Chat & Folder API`, `Ingest API & ChromaDB`?**
  _High betweenness centrality (0.026) - this node is a cross-community bridge._
- **Why does `ingest_youtube()` connect `YouTube Ingestion` to `Chat & Folder API`, `Retrieval & Embedding`, `Ingest API & ChromaDB`?**
  _High betweenness centrality (0.020) - this node is a cross-community bridge._
- **Are the 16 inferred relationships involving `Conversation` (e.g. with `Base` and `ChatRequest`) actually correct?**
  _`Conversation` has 16 INFERRED edges - model-reasoned connections that need verification._
- **Are the 15 inferred relationships involving `str` (e.g. with `log_requests()` and `ingest_youtube_endpoint()`) actually correct?**
  _`str` has 15 INFERRED edges - model-reasoned connections that need verification._
- **Are the 12 inferred relationships involving `Base` (e.g. with `MessageRole` and `Folder`) actually correct?**
  _`Base` has 12 INFERRED edges - model-reasoned connections that need verification._