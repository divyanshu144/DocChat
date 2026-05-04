---
source_file: "app/services/ingestion.py"
type: "rationale"
community: "Document / DocumentStatus"
location: "L57"
tags:
  - graphify/rationale
  - graphify/INFERRED
  - community/Document_/_DocumentStatus
---

# Return the largest-font span on a page if it looks like a heading (>13pt).

## Connections
- [[Chunk]] - `uses` [INFERRED]
- [[Document]] - `uses` [INFERRED]
- [[DocumentStatus]] - `uses` [INFERRED]
- [[LateChunkingEmbedder]] - `uses` [INFERRED]
- [[_detect_pdf_heading()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/INFERRED #community/Document_/_DocumentStatus