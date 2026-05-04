---
source_file: "README.md"
type: "document"
community: "RAG Pipeline Architecture (REA / DocChat Benchmarking Suite"
location: "line 9"
tags:
  - graphify/document
  - graphify/EXTRACTED
  - community/RAG_Pipeline_Architecture_(REA_/_DocChat_Benchmarking_Suite
---

# RAG Pipeline Architecture (README)

## Connections
- [[Background Ingestion (BackgroundTasks or ARQ)]] - `documents` [EXTRACTED]
- [[Database Schema (documents→chunks, documents→conversations→messages)]] - `references` [EXTRACTED]
- [[Document Lifecycle State Machine (pending→processing→readyerror)]] - `references` [EXTRACTED]
- [[Float16 Embedding Storage Design Decision]] - `references` [EXTRACTED]
- [[HyDE (Hypothetical Document Embedding)]] - `documents` [EXTRACTED]
- [[Hybrid Retrieval (BM25 + Semantic + RRF)]] - `documents` [EXTRACTED]
- [[SSE Token Streaming to Browser]] - `documents` [EXTRACTED]
- [[Two-Layer Retrieval Cache (L1 LRU + L2 Redis)]] - `documents` [EXTRACTED]

#graphify/document #graphify/EXTRACTED #community/RAG_Pipeline_Architecture_(REA_/_DocChat_Benchmarking_Suite