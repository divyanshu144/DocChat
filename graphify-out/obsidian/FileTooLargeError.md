---
source_file: "app/services/storage.py"
type: "code"
community: "documents.py / FileTooLargeError"
location: "L13"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/documents.py_/_FileTooLargeError
---

# FileTooLargeError

## Connections
- [[DocumentResponse]] - `uses` [INFERRED]
- [[Exception]] - `inherits` [EXTRACTED]
- [[Raised when an upload exceeds max_upload_bytes during streaming.]] - `rationale_for` [EXTRACTED]
- [[Run ingestion in a background task (non-ARQ path).]] - `uses` [INFERRED]
- [[Strip path components and limit to safe characters.]] - `uses` [INFERRED]
- [[save_upload()]] - `calls` [EXTRACTED]
- [[storage.py]] - `contains` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/documents.py_/_FileTooLargeError