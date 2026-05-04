---
source_file: "tests/test_chat.py"
type: "rationale"
community: "generate_reply() / test_chat.py"
location: "L92"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/generate_reply()_/_test_chat.py
---

# generate_reply_stream must not yield tokens when delta.content is None.

## Connections
- [[test_generate_reply_stream_skips_none_delta()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/generate_reply()_/_test_chat.py