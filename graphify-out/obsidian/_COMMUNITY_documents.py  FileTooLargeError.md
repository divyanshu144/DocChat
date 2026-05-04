---
type: community
cohesion: 0.15
members: 18
---

# documents.py / FileTooLargeError

**Cohesion:** 0.15 - loosely connected
**Members:** 18 nodes

## Members
- [[Extract and validate file extension — only allow simple alphanum suffixes.]] - rationale - app/services/storage.py
- [[FileTooLargeError]] - code - app/services/storage.py
- [[Raised when an upload exceeds max_upload_bytes during streaming.]] - rationale - app/services/storage.py
- [[Remove a file from local disk or S3, ignoring errors if it doesn't exist.]] - rationale - app/services/storage.py
- [[Run ingestion in a background task (non-ARQ path).]] - rationale - app/api/documents.py
- [[Save an uploaded file and return its path (local path or s3bucketkey).]] - rationale - app/services/storage.py
- [[Strip path components and limit to safe characters.]] - rationale - app/api/documents.py
- [[_enqueue_ingestion()]] - code - app/api/documents.py
- [[_run_ingestion_bg()]] - code - app/api/documents.py
- [[_safe_extension()]] - code - app/services/storage.py
- [[_sanitize_filename()]] - code - app/api/documents.py
- [[delete_file()]] - code - app/services/storage.py
- [[documents.py]] - code - app/api/documents.py
- [[get_document()]] - code - app/api/documents.py
- [[list_documents()]] - code - app/api/documents.py
- [[save_upload()]] - code - app/services/storage.py
- [[storage.py]] - code - app/services/storage.py
- [[upload_document()]] - code - app/api/documents.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/documents.py_/_FileTooLargeError
SORT file.name ASC
```

## Connections to other communities
- 7 edges to [[_COMMUNITY_Document  DocumentStatus]]
- 6 edges to [[_COMMUNITY_benchmark.py  ingest_document()]]
- 1 edge to [[_COMMUNITY_retrieval.py  retrieve_chunks()]]

## Top bridge nodes
- [[FileTooLargeError]] - degree 7, connects to 2 communities
- [[_run_ingestion_bg()]] - degree 4, connects to 2 communities
- [[documents.py]] - degree 7, connects to 1 community
- [[save_upload()]] - degree 6, connects to 1 community
- [[upload_document()]] - degree 5, connects to 1 community