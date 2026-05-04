---
source_file: "app/api/documents.py"
type: "code"
community: "Settings (pydantic-settings si / create_all_tables()"
location: "line 79"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Settings_(pydantic-settings_si_/_create_all_tables()
---

# upload_document() — POST /documents

## Connections
- [[Document (SQLAlchemy model)]] - `references` [EXTRACTED]
- [[Settings (pydantic-settings singleton)]] - `references` [EXTRACTED]
- [[_enqueue_ingestion() — ARQ or BackgroundTasks dispatch]] - `calls` [EXTRACTED]
- [[_sanitize_filename() — path traversal + char filter]] - `calls` [EXTRACTED]
- [[documents APIRouter]] - `references` [EXTRACTED]
- [[get_db() — async session dependency]] - `references` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Settings_(pydantic-settings_si_/_create_all_tables()