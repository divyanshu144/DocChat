---
source_file: "app/api/conversations.py"
type: "code"
community: "Document / DocumentStatus"
location: "L135"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Document_/_DocumentStatus
---

# _run_retrieval_pipeline()

## Connections
- [[.embed_query()]] - `calls` [INFERRED]
- [[HyDE expansion → embed → retrieve → re-rank.  Returns (chunks, query_emb).]] - `rationale_for` [EXTRACTED]
- [[conversations.py]] - `contains` [EXTRACTED]
- [[expand_query_hyde()]] - `calls` [INFERRED]
- [[rerank()]] - `calls` [INFERRED]
- [[retrieve_chunks()]] - `calls` [INFERRED]
- [[send_message()]] - `calls` [EXTRACTED]
- [[send_message_stream()]] - `calls` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Document_/_DocumentStatus