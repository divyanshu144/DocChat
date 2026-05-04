---
type: community
cohesion: 1.00
members: 2
---

# _Segment dataclass / CachedChunk dataclass

**Cohesion:** 1.00 - tightly connected
**Members:** 2 nodes

## Members
- [[CachedChunk dataclass]] - code - app/services/retrieval.py
- [[_Segment dataclass]] - code - app/services/ingestion.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/_Segment_dataclass_/_CachedChunk_dataclass
SORT file.name ASC
```
