---
source_file: "app/services/embedder.py"
type: "rationale"
community: "benchmark.py / ingest_document()"
location: "L32"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/benchmark.py_/_ingest_document()
---

# Lazy-init singleton; returns None if ONNX/tokenizers unavailable.

## Connections
- [[get_embedder()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/benchmark.py_/_ingest_document()