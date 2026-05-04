---
source_file: "app/services/ingestion.py"
type: "rationale"
community: "Document / DocumentStatus"
location: "L219"
tags:
  - graphify/rationale
  - graphify/INFERRED
  - community/Document_/_DocumentStatus
---

# Extract → chunk → late-chunk embed → persist; delete raw file on completion.

## Connections
- [[Chunk]] - `uses` [INFERRED]
- [[Document]] - `uses` [INFERRED]
- [[DocumentStatus]] - `uses` [INFERRED]
- [[LateChunkingEmbedder]] - `uses` [INFERRED]
- [[ingest_document()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/INFERRED #community/Document_/_DocumentStatus