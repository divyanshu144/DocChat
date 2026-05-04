---
source_file: "tests/test_sse_framing.py"
type: "rationale"
community: "TestSseFraming / _sse_frame()"
location: "L13"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/TestSseFraming_/__sse_frame()
---

# A token with no newlines produces the classic 'data: <text>\\n\\n' frame.

## Connections
- [[.test_single_line_token_produces_standard_frame()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/TestSseFraming_/__sse_frame()