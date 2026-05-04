---
source_file: "tests/test_sse_framing.py"
type: "rationale"
community: "TestSseFraming / _sse_frame()"
location: "L38"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/TestSseFraming_/__sse_frame()
---

# Every frame must end with \\n\\n so SSE clients recognise the event boundary.

## Connections
- [[.test_frame_always_ends_with_double_newline()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/TestSseFraming_/__sse_frame()