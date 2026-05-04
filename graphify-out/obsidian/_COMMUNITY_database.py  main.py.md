---
type: community
cohesion: 0.20
members: 11
---

# database.py / main.py

**Cohesion:** 0.20 - loosely connected
**Members:** 11 nodes

## Members
- [[Add missing columns to existing tables (safe to call on every startup).]] - rationale - app/core/database.py
- [[Prometheus metrics endpoint — protected by API key.]] - rationale - app/main.py
- [[_run_migrations()]] - code - app/core/database.py
- [[_set_wal_mode()]] - code - app/core/database.py
- [[create_all_tables()]] - code - app/core/database.py
- [[database.py]] - code - app/core/database.py
- [[get_db()]] - code - app/core/database.py
- [[lifespan()]] - code - app/main.py
- [[main.py]] - code - app/main.py
- [[metrics()]] - code - app/main.py
- [[root()]] - code - app/main.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/database.py_/_main.py
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_benchmark.py  ingest_document()]]
- 1 edge to [[_COMMUNITY_Document  DocumentStatus]]

## Top bridge nodes
- [[database.py]] - degree 5, connects to 1 community
- [[main.py]] - degree 4, connects to 1 community
- [[_set_wal_mode()]] - degree 2, connects to 1 community