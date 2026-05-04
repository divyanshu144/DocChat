---
source_file: "tests/test_conversations_incomplete.py"
type: "rationale"
community: "Document / DocumentStatus"
location: "L35"
tags:
  - graphify/rationale
  - graphify/INFERRED
  - community/Document_/_DocumentStatus
---

# If every message is incomplete, the result is an empty list.

## Connections
- [[ConversationResponse]] - `uses` [INFERRED]
- [[MessageResponse]] - `uses` [INFERRED]
- [[MessageRole]] - `uses` [INFERRED]
- [[test_all_incomplete_messages_excluded()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/INFERRED #community/Document_/_DocumentStatus