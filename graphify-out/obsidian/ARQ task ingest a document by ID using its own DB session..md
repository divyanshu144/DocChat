---
source_file: "app/workers/tasks.py"
type: "rationale"
community: "retrieval.py / retrieve_chunks()"
location: "L15"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/retrieval.py_/_retrieve_chunks()
---

# ARQ task: ingest a document by ID using its own DB session.

## Connections
- [[Document]] - `uses` [INFERRED]
- [[ingest_document_task()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/retrieval.py_/_retrieve_chunks()