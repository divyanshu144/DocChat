---
type: community
cohesion: 0.33
members: 7
---

# Settings / config.py

**Cohesion:** 0.33 - loosely connected
**Members:** 7 nodes

## Members
- [[Application configuration settings loaded from environment variables or .env fil]] - rationale - app/core/config.py
- [[BaseSettings]] - code
- [[Get the application settings, cached for performance.]] - rationale - app/core/config.py
- [[Settings]] - code - app/core/config.py
- [[config.py]] - code - app/core/config.py
- [[get_settings()]] - code - app/core/config.py
- [[use_s3()]] - code - app/core/config.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Settings_/_config.py
SORT file.name ASC
```
