---
source_file: "app/models/document.py"
type: "code"
community: "Document / DocumentStatus"
location: "L18"
tags:
  - graphify/code
  - graphify/INFERRED
  - community/Document_/_DocumentStatus
---

# Document

## Connections
- [[ARQ task ingest a document by ID using its own DB session.]] - `uses` [INFERRED]
- [[ARQ worker tasks for background document ingestion.  Start the worker with]] - `uses` [INFERRED]
- [[Base_1]] - `inherits` [EXTRACTED]
- [[Base]] - `uses` [INFERRED]
- [[CacheResult]] - `uses` [INFERRED]
- [[ChatRequest]] - `uses` [INFERRED]
- [[ChatResponse]] - `uses` [INFERRED]
- [[ConversationCreate]] - `uses` [INFERRED]
- [[ConversationResponse]] - `uses` [INFERRED]
- [[ConversationSummary]] - `uses` [INFERRED]
- [[Create a synthetic PDF whose raw size is approximately target_bytes.     If incl]] - `uses` [INFERRED]
- [[Create an in-memory Document ORM object pointing to the given file.]] - `uses` [INFERRED]
- [[DocumentResponse]] - `uses` [INFERRED]
- [[Extract → chunk → late-chunk embed → persist; delete raw file on completion.]] - `uses` [INFERRED]
- [[Group chunks by their source segment and embed each group with late chunking.]] - `uses` [INFERRED]
- [[HyDE expansion → embed → retrieve → re-rank.  Returns (chunks, query_emb).]] - `uses` [INFERRED]
- [[IngestionResult]] - `uses` [INFERRED]
- [[List all conversations with their source document name and message count.]] - `uses` [INFERRED]
- [[MessageResponse]] - `uses` [INFERRED]
- [[RerankerResult]] - `uses` [INFERRED]
- [[RetrievalResult]] - `uses` [INFERRED]
- [[Return (history, summary) for the conversation.      history — userassistant me]] - `uses` [INFERRED]
- [[Return the largest-font span on a page if it looks like a heading (13pt).]] - `uses` [INFERRED]
- [[Run ingestion in a background task (non-ARQ path).]] - `uses` [INFERRED]
- [[ScaleResult]] - `uses` [INFERRED]
- [[Sentence-aware split of each segment; metadata + char offsets are carried forwar]] - `uses` [INFERRED]
- [[Serialize numpy scalars that stdlib json can't handle.]] - `uses` [INFERRED]
- [[Strip path components and limit to safe characters.]] - `uses` [INFERRED]
- [[WorkerSettings]] - `uses` [INFERRED]
- [[_Segment]] - `uses` [INFERRED]
- [[_create_doc_record()]] - `calls` [INFERRED]
- [[document.py]] - `contains` [EXTRACTED]
- [[main()]] - `calls` [INFERRED]
- [[upload_document()]] - `calls` [INFERRED]

#graphify/code #graphify/INFERRED #community/Document_/_DocumentStatus