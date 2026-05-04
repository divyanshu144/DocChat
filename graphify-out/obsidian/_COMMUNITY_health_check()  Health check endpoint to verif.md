---
type: community
cohesion: 0.67
members: 3
---

# health_check() / Health check endpoint to verif

**Cohesion:** 0.67 - moderately connected
**Members:** 3 nodes

## Members
- [[Health check endpoint to verify that the API is running.]] - rationale - app/api/health.py
- [[health.py]] - code - app/api/health.py
- [[health_check()]] - code - app/api/health.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/health_check()_/_Health_check_endpoint_to_verif
SORT file.name ASC
```
