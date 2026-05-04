---
source_file: "app/services/retrieval.py"
type: "code"
community: "retrieve_chunks / ingest_document"
location: "line 273"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/retrieve_chunks_/_ingest_document
---

# retrieve_chunks

## Connections
- [[LRU retrieval cache (L1)]] - `shares_data_with` [EXTRACTED]
- [[Redis retrieval cache (L2)]] - `shares_data_with` [EXTRACTED]
- [[_build_cache_entry]] - `calls` [EXTRACTED]
- [[_cosine_similarities]] - `calls` [EXTRACTED]
- [[_embed_chunks_late]] - `shares_data_with` [INFERRED]
- [[_format_chunk metadata prefix]] - `calls` [EXTRACTED]
- [[_rrf Reciprocal Rank Fusion]] - `calls` [EXTRACTED]
- [[_run_retrieval_pipeline]] - `calls` [EXTRACTED]
- [[_tokenize NLTK stemmer]] - `calls` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/retrieve_chunks_/_ingest_document