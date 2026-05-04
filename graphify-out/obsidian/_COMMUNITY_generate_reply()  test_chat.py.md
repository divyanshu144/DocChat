---
type: community
cohesion: 0.11
members: 27
---

# generate_reply() / test_chat.py

**Cohesion:** 0.11 - loosely connected
**Members:** 27 nodes

## Members
- [[Build a minimal mock response mirroring groq ChatCompletion structure.]] - rationale - tests/test_chat.py
- [[Build a minimal mock streaming chunk.]] - rationale - tests/test_chat.py
- [[Call Groq LLM with retrieved context and conversation history.]] - rationale - app/services/chat.py
- [[Condense a list of past messages into a short paragraph.      Used when conversa]] - rationale - app/services/chat.py
- [[Generate a hypothetical document passage to improve semantic retrieval (HyDE).]] - rationale - app/services/chat.py
- [[Stream Groq LLM tokens as an async generator.]] - rationale - app/services/chat.py
- [[Tests for appserviceschat.py — Bug 1 guard None content from Groq.]] - rationale - tests/test_chat.py
- [[_build_messages()]] - code - app/services/chat.py
- [[_get_client()]] - code - app/services/chat.py
- [[_make_completion()]] - code - tests/test_chat.py
- [[_make_stream_chunk()]] - code - tests/test_chat.py
- [[chat.py]] - code - app/services/chat.py
- [[expand_query_hyde()]] - code - app/services/chat.py
- [[generate_reply must pass through non-None content unchanged.]] - rationale - tests/test_chat.py
- [[generate_reply must return '' instead of None when Groq returns None content.]] - rationale - tests/test_chat.py
- [[generate_reply must return '' when Groq returns an empty string.]] - rationale - tests/test_chat.py
- [[generate_reply()]] - code - app/services/chat.py
- [[generate_reply_stream must not yield empty string tokens (falsy guard).]] - rationale - tests/test_chat.py
- [[generate_reply_stream must not yield tokens when delta.content is None.]] - rationale - tests/test_chat.py
- [[generate_reply_stream()]] - code - app/services/chat.py
- [[summarize_history()]] - code - app/services/chat.py
- [[test_chat.py]] - code - tests/test_chat.py
- [[test_generate_reply_returns_content_when_present()]] - code - tests/test_chat.py
- [[test_generate_reply_returns_empty_string_when_content_is_empty_string()]] - code - tests/test_chat.py
- [[test_generate_reply_returns_empty_string_when_content_is_none()]] - code - tests/test_chat.py
- [[test_generate_reply_stream_skips_empty_string_delta()]] - code - tests/test_chat.py
- [[test_generate_reply_stream_skips_none_delta()]] - code - tests/test_chat.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/generate_reply()_/_test_chat.py
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_Document  DocumentStatus]]

## Top bridge nodes
- [[generate_reply()]] - degree 8, connects to 1 community
- [[expand_query_hyde()]] - degree 4, connects to 1 community
- [[summarize_history()]] - degree 4, connects to 1 community