---
source_file: "app/services/ingestion.py"
type: "rationale"
community: "LateChunkingEmbedder / .embed_query()"
location: "L180"
tags:
  - graphify/rationale
  - graphify/INFERRED
  - community/LateChunkingEmbedder_/_.embed_query()
---

# Group chunks by their source segment and embed each group with late chunking.

## Connections
- [[Chunk]] - `uses` [INFERRED]
- [[Document]] - `uses` [INFERRED]
- [[DocumentStatus]] - `uses` [INFERRED]
- [[LateChunkingEmbedder]] - `uses` [INFERRED]
- [[_embed_chunks_late()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/INFERRED #community/LateChunkingEmbedder_/_.embed_query()