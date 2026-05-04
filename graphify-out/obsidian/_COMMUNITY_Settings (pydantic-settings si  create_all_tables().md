---
type: community
cohesion: 0.10
members: 30
---

# Settings (pydantic-settings si / create_all_tables()

**Cohesion:** 0.10 - loosely connected
**Members:** 30 nodes

## Members
- [[AsyncSessionLocal (session factory)]] - code - app/core/database.py
- [[Base (DeclarativeBase)]] - code - app/core/database.py
- [[Chunk (SQLAlchemy model)]] - code - app/models/chunk.py
- [[Conversation (SQLAlchemy model)]] - code - app/models/conversation.py
- [[Document (SQLAlchemy model)]] - code - app/models/document.py
- [[DocumentResponse (Pydantic response model)]] - code - app/api/documents.py
- [[DocumentStatus (enum pendingprocessingreadyerror)]] - code - app/models/document.py
- [[FastAPI App Instance]] - code - app/main.py
- [[Message (SQLAlchemy model)]] - code - app/models/message.py
- [[MessageRole (enum userassistant)]] - code - app/models/message.py
- [[Settings (pydantic-settings singleton)]] - code - app/core/config.py
- [[_enqueue_ingestion() — ARQ or BackgroundTasks dispatch]] - code - app/api/documents.py
- [[_run_ingestion_bg() — background task wrapper]] - code - app/api/documents.py
- [[_run_migrations() — idempotent column migrations]] - code - app/core/database.py
- [[_sanitize_filename() — path traversal + char filter]] - code - app/api/documents.py
- [[_set_wal_mode() — SQLite WAL pragma listener]] - code - app/core/database.py
- [[async SQLAlchemy engine]] - code - app/core/database.py
- [[create_all_tables()_1]] - code - app/core/database.py
- [[documents APIRouter]] - code - app/api/documents.py
- [[get_db() — async session dependency]] - code - app/core/database.py
- [[get_document() — GET documents{document_id}]] - code - app/api/documents.py
- [[get_settings() — lru_cache factory]] - code - app/core/config.py
- [[health APIRouter]] - code - app/api/health.py
- [[health_check() — GET health]] - code - app/api/health.py
- [[lifespan (startup handler)]] - code - app/main.py
- [[limiter (SlowAPI Limiter singleton)]] - code - app/core/limiter.py
- [[list_documents() — GET documents]] - code - app/api/documents.py
- [[metrics() — Prometheus endpoint]] - code - app/main.py
- [[require_api_key() — FastAPI dependency]] - code - app/core/security.py
- [[upload_document() — POST documents]] - code - app/api/documents.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Settings_(pydantic-settings_si_/_create_all_tables()
SORT file.name ASC
```
