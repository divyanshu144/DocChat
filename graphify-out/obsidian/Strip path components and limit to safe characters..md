---
source_file: "app/api/documents.py"
type: "rationale"
community: "documents.py / FileTooLargeError"
location: "L49"
tags:
  - graphify/rationale
  - graphify/INFERRED
  - community/documents.py_/_FileTooLargeError
---

# Strip path components and limit to safe characters.

## Connections
- [[Document]] - `uses` [INFERRED]
- [[DocumentStatus]] - `uses` [INFERRED]
- [[FileTooLargeError]] - `uses` [INFERRED]
- [[_sanitize_filename()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/INFERRED #community/documents.py_/_FileTooLargeError