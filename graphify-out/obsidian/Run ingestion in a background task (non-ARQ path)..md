---
source_file: "app/api/documents.py"
type: "rationale"
community: "documents.py / FileTooLargeError"
location: "L56"
tags:
  - graphify/rationale
  - graphify/INFERRED
  - community/documents.py_/_FileTooLargeError
---

# Run ingestion in a background task (non-ARQ path).

## Connections
- [[Document]] - `uses` [INFERRED]
- [[DocumentStatus]] - `uses` [INFERRED]
- [[FileTooLargeError]] - `uses` [INFERRED]
- [[_run_ingestion_bg()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/INFERRED #community/documents.py_/_FileTooLargeError