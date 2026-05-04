---
type: community
cohesion: 1.00
members: 2
---

# ingestion_chunks (Counter) / ingestion_duration (Histogram)

**Cohesion:** 1.00 - tightly connected
**Members:** 2 nodes

## Members
- [[ingestion_chunks (Counter)]] - code - app/core/metrics.py
- [[ingestion_duration (Histogram)]] - code - app/core/metrics.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/ingestion_chunks_(Counter)_/_ingestion_duration_(Histogram)
SORT file.name ASC
```
