---
type: community
cohesion: 1.00
members: 2
---

# semantic_cache_hits (Counter) / semantic_cache_misses (Counter

**Cohesion:** 1.00 - tightly connected
**Members:** 2 nodes

## Members
- [[semantic_cache_hits (Counter)]] - code - app/core/metrics.py
- [[semantic_cache_misses (Counter)]] - code - app/core/metrics.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/semantic_cache_hits_(Counter)_/_semantic_cache_misses_(Counter
SORT file.name ASC
```
