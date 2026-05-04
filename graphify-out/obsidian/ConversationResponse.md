---
source_file: "app/api/conversations.py"
type: "code"
community: "Document / DocumentStatus"
location: "L46"
tags:
  - graphify/code
  - graphify/INFERRED
  - community/Document_/_DocumentStatus
---

# ConversationResponse

## Connections
- [[All complete messages pass through the filter unchanged.]] - `uses` [INFERRED]
- [[BaseModel]] - `inherits` [EXTRACTED]
- [[Conversation]] - `uses` [INFERRED]
- [[ConversationResponse can be constructed with a filtered messages list.]] - `uses` [INFERRED]
- [[ConversationResponse with no complete messages returns an empty list (not an err]] - `uses` [INFERRED]
- [[Document]] - `uses` [INFERRED]
- [[DocumentStatus]] - `uses` [INFERRED]
- [[If every message is incomplete, the result is an empty list.]] - `uses` [INFERRED]
- [[Message]] - `uses` [INFERRED]
- [[MessageRole]] - `uses` [INFERRED]
- [[Mixed list only the complete ones survive the filter.]] - `uses` [INFERRED]
- [[Tests for Bug 4 fix GET conversations{id} excludes is_complete=False message]] - `uses` [INFERRED]
- [[conversations.py]] - `contains` [EXTRACTED]
- [[get_conversation()]] - `calls` [EXTRACTED]
- [[is_complete=False messages are excluded when filtering by is_complete.]] - `uses` [INFERRED]
- [[test_get_conversation_response_empty_messages()]] - `calls` [INFERRED]
- [[test_get_conversation_response_schema()]] - `calls` [INFERRED]

#graphify/code #graphify/INFERRED #community/Document_/_DocumentStatus