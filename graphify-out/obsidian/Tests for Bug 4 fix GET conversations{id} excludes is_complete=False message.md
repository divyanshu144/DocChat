---
source_file: "tests/test_conversations_incomplete.py"
type: "rationale"
community: "Document / DocumentStatus"
location: "L1"
tags:
  - graphify/rationale
  - graphify/INFERRED
  - community/Document_/_DocumentStatus
---

# Tests for Bug #4 fix: GET /conversations/{id} excludes is_complete=False message

## Connections
- [[ConversationResponse]] - `uses` [INFERRED]
- [[MessageResponse]] - `uses` [INFERRED]
- [[MessageRole]] - `uses` [INFERRED]
- [[test_conversations_incomplete.py]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/INFERRED #community/Document_/_DocumentStatus