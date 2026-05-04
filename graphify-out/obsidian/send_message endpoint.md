---
source_file: "app/api/conversations.py"
type: "code"
community: "retrieve_chunks / ingest_document"
location: "line 253"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/retrieve_chunks_/_ingest_document
---

# send_message endpoint

## Connections
- [[_load_history]] - `calls` [EXTRACTED]
- [[_run_retrieval_pipeline]] - `calls` [EXTRACTED]
- [[embed_query]] - `calls` [EXTRACTED]
- [[generate_reply]] - `calls` [EXTRACTED]
- [[get_semantic_cache singleton]] - `calls` [EXTRACTED]
- [[ingest_document_task ARQ task]] - `semantically_similar_to` [INFERRED]

#graphify/code #graphify/EXTRACTED #community/retrieve_chunks_/_ingest_document