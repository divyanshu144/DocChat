---
source_file: "app/services/chat.py"
type: "code"
community: "generate_reply() / test_chat.py"
location: "L39"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/generate_reply()_/_test_chat.py
---

# generate_reply()

## Connections
- [[Call Groq LLM with retrieved context and conversation history.]] - `rationale_for` [EXTRACTED]
- [[_build_messages()]] - `calls` [EXTRACTED]
- [[_get_client()]] - `calls` [EXTRACTED]
- [[chat.py]] - `contains` [EXTRACTED]
- [[send_message()]] - `calls` [INFERRED]
- [[test_generate_reply_returns_content_when_present()]] - `calls` [INFERRED]
- [[test_generate_reply_returns_empty_string_when_content_is_empty_string()]] - `calls` [INFERRED]
- [[test_generate_reply_returns_empty_string_when_content_is_none()]] - `calls` [INFERRED]

#graphify/code #graphify/EXTRACTED #community/generate_reply()_/_test_chat.py