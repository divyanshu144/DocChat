---
source_file: "tests/test_conversations_incomplete.py"
type: "rationale"
community: "Document / DocumentStatus"
location: "L13"
tags:
  - graphify/rationale
  - graphify/INFERRED
  - community/Document_/_DocumentStatus
---

# is_complete=False messages are excluded when filtering by is_complete.

## Connections
- [[ConversationResponse]] - `uses` [INFERRED]
- [[MessageResponse]] - `uses` [INFERRED]
- [[MessageRole]] - `uses` [INFERRED]
- [[test_incomplete_messages_filtered()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/INFERRED #community/Document_/_DocumentStatus