---
source_file: "app/api/conversations.py"
type: "rationale"
community: "Document / DocumentStatus"
location: "L142"
tags:
  - graphify/rationale
  - graphify/INFERRED
  - community/Document_/_DocumentStatus
---

# HyDE expansion → embed → retrieve → re-rank.  Returns (chunks, query_emb).

## Connections
- [[Conversation]] - `uses` [INFERRED]
- [[Document]] - `uses` [INFERRED]
- [[DocumentStatus]] - `uses` [INFERRED]
- [[Message]] - `uses` [INFERRED]
- [[MessageRole]] - `uses` [INFERRED]
- [[_run_retrieval_pipeline()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/INFERRED #community/Document_/_DocumentStatus