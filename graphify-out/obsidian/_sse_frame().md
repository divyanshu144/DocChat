---
source_file: "tests/test_sse_framing.py"
type: "code"
community: "TestSseFraming / _sse_frame()"
location: "L5"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/TestSseFraming_/__sse_frame()
---

# _sse_frame()

## Connections
- [[.test_empty_token_produces_empty_data_line()]] - `calls` [EXTRACTED]
- [[.test_frame_always_ends_with_double_newline()]] - `calls` [EXTRACTED]
- [[.test_multiline_preserves_content()]] - `calls` [EXTRACTED]
- [[.test_single_line_token_produces_standard_frame()]] - `calls` [EXTRACTED]
- [[.test_three_line_token()]] - `calls` [EXTRACTED]
- [[.test_token_with_only_newline()]] - `calls` [EXTRACTED]
- [[.test_trailing_newline_in_token()]] - `calls` [EXTRACTED]
- [[.test_two_line_token_produces_two_data_lines()]] - `calls` [EXTRACTED]
- [[Replicate the fixed SSE framing logic from event_stream() in conversations.py.]] - `rationale_for` [EXTRACTED]
- [[test_sse_framing.py]] - `contains` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/TestSseFraming_/__sse_frame()