---
type: community
cohesion: 0.07
members: 35
---

# RAG Pipeline Architecture (REA / DocChat Benchmarking Suite

**Cohesion:** 0.07 - loosely connected
**Members:** 35 nodes

## Members
- [[Architectural Gap Linear semantic cache scan O(n) per query]] - document - reports/docchat-audit.md
- [[Architectural Gap No index on messages.conversation_id (full table scan)]] - document - reports/docchat-audit.md
- [[Background Ingestion (BackgroundTasks or ARQ)]] - document - README.md
- [[Benchmark Ground Truth Query Set]] - code - scripts/benchmark.py
- [[Bug 1 (Critical) generate_reply returns None crashes DB write]] - document - reports/docchat-audit.md
- [[Bug 10 (Low) Health check status mismatch — API returns 'healthy', JS checks 'ok']] - document - reports/docchat-audit.md
- [[Bug 13 (Medium) History summarization injects a second system message]] - document - reports/docchat-audit.md
- [[Bug 14 (Medium) Conversation.messages order_by uses invalid SQLAlchemy 2.x string form]] - document - reports/docchat-audit.md
- [[Bug 2 (Critical) SSE newline-in-token silently drops content]] - document - reports/docchat-audit.md
- [[Bug 6 (Medium) Semantic cache checked after retrieval — defeats its purpose]] - document - reports/docchat-audit.md
- [[Bug 7 (Medium) ARQ Redis connection pool never closed]] - document - reports/docchat-audit.md
- [[Database Schema (documents→chunks, documents→conversations→messages)]] - document - README.md
- [[DocChat Benchmarking Suite]] - code - scripts/benchmark.py
- [[Document Lifecycle State Machine (pending→processing→readyerror)]] - document - README.md
- [[Document Scale Benchmark]] - code - scripts/benchmark.py
- [[Float16 Embedding Storage Design Decision]] - document - README.md
- [[HyDE (Hypothetical Document Embedding)]] - document - README.md
- [[Hybrid Retrieval (BM25 + Semantic + RRF)]] - document - README.md
- [[Ingestion Speed Benchmark]] - code - scripts/benchmark.py
- [[RAG Pipeline Architecture (README)]] - document - README.md
- [[Reranking Precision Benchmark (MRR  Hit@k)]] - code - scripts/benchmark.py
- [[Retrieval Latency Benchmark]] - code - scripts/benchmark.py
- [[Roadmap Feature Multi-Document Conversations]] - document - reports/docchat-audit.md
- [[Roadmap Feature Real-Time Ingestion Progress via SSE]] - document - reports/docchat-audit.md
- [[SPA Entry Point (index.html)]] - code - app/static/index.html
- [[SSE Token Streaming to Browser]] - document - README.md
- [[Semantic Cache Hit Rate Benchmark]] - code - scripts/benchmark.py
- [[Two-Layer Retrieval Cache (L1 LRU + L2 Redis)]] - document - README.md
- [[_generate_pdf (synthetic PDF factory)]] - code - scripts/benchmark.py
- [[fastembed =0.3.0 (ONNX BAAIbge-small-en-v1.5)]] - document - requirements.txt
- [[flashrank =0.2.0 (cross-encoder re-ranker)]] - document - requirements.txt
- [[langchain-text-splitters =0.2.0]] - document - requirements.txt
- [[nltk =3.8.0 (BM25 stemming)]] - document - requirements.txt
- [[pymupdf =1.24.0 (PDF extraction + fitz)]] - document - requirements.txt
- [[rank-bm25 0.2.2]] - document - requirements.txt

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/RAG_Pipeline_Architecture_(REA_/_DocChat_Benchmarking_Suite
SORT file.name ASC
```
