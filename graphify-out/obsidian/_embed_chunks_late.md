---
source_file: "app/services/ingestion.py"
type: "code"
community: "retrieve_chunks / ingest_document"
location: "line 175"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/retrieve_chunks_/_ingest_document
---

# _embed_chunks_late

## Connections
- [[LateChunkingEmbedder.embed_independently]] - `calls` [EXTRACTED]
- [[LateChunkingEmbedder.embed_late]] - `calls` [EXTRACTED]
- [[ingest_document]] - `calls` [EXTRACTED]
- [[retrieve_chunks]] - `shares_data_with` [INFERRED]

#graphify/code #graphify/EXTRACTED #community/retrieve_chunks_/_ingest_document