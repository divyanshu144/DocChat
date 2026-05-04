---
source_file: "app/services/retrieval.py"
type: "code"
community: "retrieve_chunks / ingest_document"
location: "line 264"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/retrieve_chunks_/_ingest_document
---

# embed_query

## Connections
- [[LateChunkingEmbedder class]] - `semantically_similar_to` [INFERRED]
- [[LateChunkingEmbedder.embed_query]] - `calls` [EXTRACTED]
- [[_run_retrieval_pipeline]] - `calls` [EXTRACTED]
- [[get_embedder singleton]] - `calls` [EXTRACTED]
- [[send_message endpoint]] - `calls` [EXTRACTED]
- [[send_message_stream endpoint]] - `calls` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/retrieve_chunks_/_ingest_document