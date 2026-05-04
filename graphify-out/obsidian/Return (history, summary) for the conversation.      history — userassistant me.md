---
source_file: "app/api/conversations.py"
type: "rationale"
community: "Document / DocumentStatus"
location: "L80"
tags:
  - graphify/rationale
  - graphify/INFERRED
  - community/Document_/_DocumentStatus
---

# Return (history, summary) for the conversation.      history — user/assistant me

## Connections
- [[Conversation]] - `uses` [INFERRED]
- [[Document]] - `uses` [INFERRED]
- [[DocumentStatus]] - `uses` [INFERRED]
- [[Message]] - `uses` [INFERRED]
- [[MessageRole]] - `uses` [INFERRED]
- [[_load_history()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/INFERRED #community/Document_/_DocumentStatus