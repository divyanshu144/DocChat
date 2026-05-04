---
type: community
cohesion: 0.12
members: 57
---

# Document / DocumentStatus

**Cohesion:** 0.12 - loosely connected
**Members:** 57 nodes

## Members
- [[All complete messages pass through the filter unchanged.]] - rationale - tests/test_conversations_incomplete.py
- [[Base_1]] - code
- [[Base]] - code - app/core/database.py
- [[BaseModel]] - code
- [[CacheResult]] - code - scripts/benchmark.py
- [[ChatRequest]] - code - app/api/conversations.py
- [[ChatResponse]] - code - app/api/conversations.py
- [[Chunk]] - code - app/models/chunk.py
- [[Conversation]] - code - app/models/conversation.py
- [[ConversationCreate]] - code - app/api/conversations.py
- [[ConversationResponse]] - code - app/api/conversations.py
- [[ConversationResponse can be constructed with a filtered messages list.]] - rationale - tests/test_conversations_incomplete.py
- [[ConversationResponse with no complete messages returns an empty list (not an err]] - rationale - tests/test_conversations_incomplete.py
- [[ConversationSummary]] - code - app/api/conversations.py
- [[Create a synthetic PDF whose raw size is approximately target_bytes.     If incl]] - rationale - scripts/benchmark.py
- [[Create an in-memory Document ORM object pointing to the given file.]] - rationale - scripts/benchmark.py
- [[DeclarativeBase]] - code
- [[Document]] - code - app/models/document.py
- [[DocumentResponse]] - code - app/api/documents.py
- [[DocumentStatus]] - code - app/models/document.py
- [[Extract → chunk → late-chunk embed → persist; delete raw file on completion.]] - rationale - app/services/ingestion.py
- [[HyDE expansion → embed → retrieve → re-rank.  Returns (chunks, query_emb).]] - rationale - app/api/conversations.py
- [[If every message is incomplete, the result is an empty list.]] - rationale - tests/test_conversations_incomplete.py
- [[IngestionResult]] - code - scripts/benchmark.py
- [[List all conversations with their source document name and message count.]] - rationale - app/api/conversations.py
- [[Message]] - code - app/models/message.py
- [[MessageResponse]] - code - app/api/conversations.py
- [[MessageRole]] - code - app/models/message.py
- [[Mixed list only the complete ones survive the filter.]] - rationale - tests/test_conversations_incomplete.py
- [[RerankerResult]] - code - scripts/benchmark.py
- [[RetrievalResult]] - code - scripts/benchmark.py
- [[Return (history, summary) for the conversation.      history — userassistant me]] - rationale - app/api/conversations.py
- [[Return the largest-font span on a page if it looks like a heading (13pt).]] - rationale - app/services/ingestion.py
- [[ScaleResult]] - code - scripts/benchmark.py
- [[Sentence-aware split of each segment; metadata + char offsets are carried forwar]] - rationale - app/services/ingestion.py
- [[Serialize numpy scalars that stdlib json can't handle.]] - rationale - scripts/benchmark.py
- [[Tests for Bug 4 fix GET conversations{id} excludes is_complete=False message]] - rationale - tests/test_conversations_incomplete.py
- [[_load_history()]] - code - app/api/conversations.py
- [[_run_retrieval_pipeline()]] - code - app/api/conversations.py
- [[chunk.py]] - code - app/models/chunk.py
- [[conversation.py]] - code - app/models/conversation.py
- [[conversations.py]] - code - app/api/conversations.py
- [[create_conversation()]] - code - app/api/conversations.py
- [[document.py]] - code - app/models/document.py
- [[get_conversation()]] - code - app/api/conversations.py
- [[is_complete=False messages are excluded when filtering by is_complete.]] - rationale - tests/test_conversations_incomplete.py
- [[list_conversations()]] - code - app/api/conversations.py
- [[message.py]] - code - app/models/message.py
- [[send_message()]] - code - app/api/conversations.py
- [[send_message_stream()]] - code - app/api/conversations.py
- [[test_all_incomplete_messages_excluded()]] - code - tests/test_conversations_incomplete.py
- [[test_conversations_incomplete.py]] - code - tests/test_conversations_incomplete.py
- [[test_get_conversation_response_empty_messages()]] - code - tests/test_conversations_incomplete.py
- [[test_get_conversation_response_schema()]] - code - tests/test_conversations_incomplete.py
- [[test_incomplete_messages_filtered()]] - code - tests/test_conversations_incomplete.py
- [[test_mixed_messages_only_complete_returned()]] - code - tests/test_conversations_incomplete.py
- [[test_only_complete_messages_pass_filter()]] - code - tests/test_conversations_incomplete.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Document_/_DocumentStatus
SORT file.name ASC
```

## Connections to other communities
- 23 edges to [[_COMMUNITY_benchmark.py  ingest_document()]]
- 11 edges to [[_COMMUNITY_retrieval.py  retrieve_chunks()]]
- 9 edges to [[_COMMUNITY_LateChunkingEmbedder  .embed_query()]]
- 7 edges to [[_COMMUNITY_documents.py  FileTooLargeError]]
- 5 edges to [[_COMMUNITY__Segment  _chunk_segments()]]
- 3 edges to [[_COMMUNITY_generate_reply()  test_chat.py]]
- 2 edges to [[_COMMUNITY_SemanticCache  get_semantic_cache()]]
- 1 edge to [[_COMMUNITY_database.py  main.py]]

## Top bridge nodes
- [[Document]] - degree 34, connects to 5 communities
- [[send_message()]] - degree 11, connects to 5 communities
- [[DocumentStatus]] - degree 28, connects to 4 communities
- [[Chunk]] - degree 23, connects to 4 communities
- [[_run_retrieval_pipeline()]] - degree 8, connects to 4 communities