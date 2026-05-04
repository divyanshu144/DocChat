---
type: community
cohesion: 0.11
members: 25
---

# TestSseFraming / _sse_frame()

**Cohesion:** 0.11 - loosely connected
**Members:** 25 nodes

## Members
- [[.test_empty_token_produces_empty_data_line()]] - code - tests/test_sse_framing.py
- [[.test_frame_always_ends_with_double_newline()]] - code - tests/test_sse_framing.py
- [[.test_multiline_preserves_content()]] - code - tests/test_sse_framing.py
- [[.test_sentinel_done_unchanged()]] - code - tests/test_sse_framing.py
- [[.test_sentinel_error_unchanged()]] - code - tests/test_sse_framing.py
- [[.test_single_line_token_produces_standard_frame()]] - code - tests/test_sse_framing.py
- [[.test_three_line_token()]] - code - tests/test_sse_framing.py
- [[.test_token_with_only_newline()]] - code - tests/test_sse_framing.py
- [[.test_trailing_newline_in_token()]] - code - tests/test_sse_framing.py
- [[.test_two_line_token_produces_two_data_lines()]] - code - tests/test_sse_framing.py
- [[A token containing one newline must produce two data lines.]] - rationale - tests/test_sse_framing.py
- [[A token that is just a newline character.]] - rationale - tests/test_sse_framing.py
- [[A token with no newlines produces the classic 'data textnn' frame.]] - rationale - tests/test_sse_framing.py
- [[A token with two newlines produces three data lines.]] - rationale - tests/test_sse_framing.py
- [[A trailing newline in the token results in a trailing empty data line.]] - rationale - tests/test_sse_framing.py
- [[An empty token string produces a single empty data line.]] - rationale - tests/test_sse_framing.py
- [[Content on each line must be preserved intact.]] - rationale - tests/test_sse_framing.py
- [[Every frame must end with nn so SSE clients recognise the event boundary.]] - rationale - tests/test_sse_framing.py
- [[Replicate the fixed SSE framing logic from event_stream() in conversations.py.]] - rationale - tests/test_sse_framing.py
- [[TestSseFraming]] - code - tests/test_sse_framing.py
- [[Tests for Bug 2 — SSE framing multi-line tokens must produce one data line pe]] - rationale - tests/test_sse_framing.py
- [[DONE sentinel uses literal string — verify its format is correct.]] - rationale - tests/test_sse_framing.py
- [[ERROR sentinel uses literal string — verify its format is correct.]] - rationale - tests/test_sse_framing.py
- [[_sse_frame()]] - code - tests/test_sse_framing.py
- [[test_sse_framing.py]] - code - tests/test_sse_framing.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/TestSseFraming_/__sse_frame()
SORT file.name ASC
```
