---
source_file: "tests/test_conversations_incomplete.py"
type: "rationale"
community: "Document / DocumentStatus"
location: "L87"
tags:
  - graphify/rationale
  - graphify/INFERRED
  - community/Document_/_DocumentStatus
---

# ConversationResponse with no complete messages returns an empty list (not an err

## Connections
- [[ConversationResponse]] - `uses` [INFERRED]
- [[MessageResponse]] - `uses` [INFERRED]
- [[MessageRole]] - `uses` [INFERRED]
- [[test_get_conversation_response_empty_messages()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/INFERRED #community/Document_/_DocumentStatus