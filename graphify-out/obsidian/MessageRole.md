---
source_file: "app/models/message.py"
type: "code"
community: "Document / DocumentStatus"
location: "L11"
tags:
  - graphify/code
  - graphify/INFERRED
  - community/Document_/_DocumentStatus
---

# MessageRole

## Connections
- [[All complete messages pass through the filter unchanged.]] - `uses` [INFERRED]
- [[Base]] - `uses` [INFERRED]
- [[ChatRequest]] - `uses` [INFERRED]
- [[ChatResponse]] - `uses` [INFERRED]
- [[ConversationCreate]] - `uses` [INFERRED]
- [[ConversationResponse]] - `uses` [INFERRED]
- [[ConversationResponse can be constructed with a filtered messages list.]] - `uses` [INFERRED]
- [[ConversationResponse with no complete messages returns an empty list (not an err]] - `uses` [INFERRED]
- [[ConversationSummary]] - `uses` [INFERRED]
- [[HyDE expansion → embed → retrieve → re-rank.  Returns (chunks, query_emb).]] - `uses` [INFERRED]
- [[If every message is incomplete, the result is an empty list.]] - `uses` [INFERRED]
- [[List all conversations with their source document name and message count.]] - `uses` [INFERRED]
- [[MessageResponse]] - `uses` [INFERRED]
- [[Mixed list only the complete ones survive the filter.]] - `uses` [INFERRED]
- [[Return (history, summary) for the conversation.      history — userassistant me]] - `uses` [INFERRED]
- [[Tests for Bug 4 fix GET conversations{id} excludes is_complete=False message]] - `uses` [INFERRED]
- [[is_complete=False messages are excluded when filtering by is_complete.]] - `uses` [INFERRED]
- [[message.py]] - `contains` [EXTRACTED]
- [[str]] - `inherits` [EXTRACTED]

#graphify/code #graphify/INFERRED #community/Document_/_DocumentStatus