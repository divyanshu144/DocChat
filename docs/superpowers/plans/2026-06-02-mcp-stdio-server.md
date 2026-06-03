# MCP stdio Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an MCP stdio server (`app/mcp_server.py`) that exposes three tools — `query_documents`, `ingest_document`, `list_documents` — so Claude Desktop can call the DocChat pipeline directly.

**Architecture:** Single new file using FastMCP decorator API; tools call existing ingestion services and the LangGraph `agent_graph` without touching `app/main.py` or any pipeline internals. Two pre-conditions are fixed first: `print()` calls in `retriever.py` that would corrupt the stdio JSON-RPC channel, and `mcp` package added to requirements.

**Tech Stack:** `mcp>=1.27.0` (FastMCP), `qdrant-client` (sync `QdrantClient.scroll`), `langgraph` (`agent_graph.ainvoke`), `pydantic` (`Field`, `Annotated`)

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `app/agent/nodes/retriever.py` | Modify lines 48, 57, 68 | Replace `print()` with `logger.debug()` — required before stdio transport is safe |
| `requirements.txt` | Modify | Add `mcp>=1.27.0` |
| `app/mcp_server.py` | Create | FastMCP server: three tools + `mcp.run(transport="stdio")` entrypoint |
| `tests/test_mcp_server.py` | Create | Stdout-safety test + tool registration smoke tests |
| `~/Library/Application Support/Claude/claude_desktop_config.json` | Modify | Register docchat MCP server for Claude Desktop |

---

## Task 1: Fix print() → logger.debug() in retriever.py

**Files:**
- Modify: `app/agent/nodes/retriever.py:48,57,68`
- Test: `tests/test_agent_retriever.py` (add one new test at the bottom)

**Why this comes first:** FastMCP's `transport="stdio"` owns stdout entirely. Any bytes written to stdout outside the JSON-RPC framing (including `print()`) corrupt the channel silently. This fix must land before the server is used.

- [ ] **Step 1: Add a stdout-safety test to the existing retriever test file**

Open `tests/test_agent_retriever.py` and add at the bottom:

```python
@pytest.mark.asyncio
async def test_retriever_does_not_write_to_stdout(capsys):
    """No print() calls should survive in retriever_node — they corrupt the MCP stdio channel."""
    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = np.array([0.1] * 384, dtype="float32")

    with (
        patch("app.agent.nodes.retriever._search", new=AsyncMock(return_value=[])),
        patch("app.agent.nodes.retriever.get_embedder", return_value=mock_embedder),
    ):
        await retriever_node(_base_state())

    captured = capsys.readouterr()
    assert captured.out == "", f"unexpected stdout from retriever_node: {captured.out!r}"
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
cd "/Users/divyanshu/Desktop/All Projects/docchat" && \
  venv/bin/pytest tests/test_agent_retriever.py::test_retriever_does_not_write_to_stdout -v
```

Expected: FAIL — `AssertionError: unexpected stdout from retriever_node: '[RETRIEVER] ...'`

- [ ] **Step 3: Fix the three print() calls in retriever.py**

Open `app/agent/nodes/retriever.py`. Replace line 48:

```python
# Before:
print(f"[RETRIEVER] query={state['query']!r} sources={state['sources_to_use']} source_ids={source_ids}")
# After:
logger.debug("[RETRIEVER] query=%r sources=%s source_ids=%s", state["query"], state["sources_to_use"], source_ids)
```

Replace line 57 (inside the for-loop, after `hits = await _search(...)`):

```python
# Before:
print(f"[RETRIEVER] {collection_name} → {len(hits)} hits")
# After:
logger.debug("[RETRIEVER] %s → %d hits", collection_name, len(hits))
```

Replace lines 67-68 (the except block):

```python
# Before:
        except Exception as exc:
            import traceback
            print(f"[RETRIEVER ERROR] collection={collection_name} error={exc}")
            traceback.print_exc()
# After:
        except Exception as exc:
            logger.exception("[RETRIEVER ERROR] collection=%s error=%s", collection_name, exc)
```

> Note: `logger.exception()` logs at ERROR level and appends the traceback to stderr automatically — equivalent to the original `print_exc()` but goes to stderr not stdout.

- [ ] **Step 4: Run the test to confirm it passes**

```bash
cd "/Users/divyanshu/Desktop/All Projects/docchat" && \
  venv/bin/pytest tests/test_agent_retriever.py::test_retriever_does_not_write_to_stdout -v
```

Expected: PASS

- [ ] **Step 5: Run the full retriever test suite to confirm no regressions**

```bash
cd "/Users/divyanshu/Desktop/All Projects/docchat" && \
  venv/bin/pytest tests/test_agent_retriever.py -v
```

Expected: all tests PASS

---

## Task 2: Add mcp to requirements.txt and install

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add mcp to requirements.txt**

Open `requirements.txt` and append at the end:

```
mcp>=1.27.0
```

- [ ] **Step 2: Install the package**

```bash
cd "/Users/divyanshu/Desktop/All Projects/docchat" && \
  venv/bin/pip install "mcp>=1.27.0"
```

Expected output ends with: `Successfully installed mcp-...`

- [ ] **Step 3: Verify FastMCP is importable**

```bash
cd "/Users/divyanshu/Desktop/All Projects/docchat" && \
  venv/bin/python -c "from mcp.server.fastmcp import FastMCP; print('ok')"
```

Expected: `ok`

---

## Task 3: Create app/mcp_server.py

**Files:**
- Create: `app/mcp_server.py`
- Create: `tests/test_mcp_server.py`

- [ ] **Step 1: Write the failing import test**

Create `tests/test_mcp_server.py`:

```python
import inspect
import pytest


def test_mcp_server_imports_without_stdout(capsys):
    """Importing mcp_server must not write to stdout — it would corrupt the stdio JSON-RPC channel."""
    import app.mcp_server  # noqa: F401
    captured = capsys.readouterr()
    assert captured.out == "", f"unexpected stdout on import: {captured.out!r}"


def test_all_three_tools_are_async_callables():
    from app.mcp_server import query_documents, ingest_document, list_documents
    assert inspect.iscoroutinefunction(query_documents), "query_documents must be async"
    assert inspect.iscoroutinefunction(ingest_document), "ingest_document must be async"
    assert inspect.iscoroutinefunction(list_documents), "list_documents must be async"
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
cd "/Users/divyanshu/Desktop/All Projects/docchat" && \
  venv/bin/pytest tests/test_mcp_server.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.mcp_server'`

- [ ] **Step 3: Create app/mcp_server.py with the full implementation**

Create `app/mcp_server.py`:

```python
import json
import logging
import sys
from pathlib import Path
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("docchat")


@mcp.tool()
async def query_documents(
    query: Annotated[str, Field(description="Natural language question to ask the knowledge base")],
    source_ids: Annotated[
        list[str] | None,
        Field(description="Restrict retrieval to specific source IDs. Omit to search all."),
    ] = None,
) -> str:
    """Run the DocChat pipeline and return an answer with inline citations."""
    from app.agent.graph import agent_graph
    from app.agent.state import AgentState

    state: AgentState = {
        "query": query,
        "conversation_id": "",
        "sources_to_use": ["pdf", "youtube", "web"],
        "source_ids": source_ids or [],
        "retrieved_chunks": [],
        "answer": "",
        "critic_feedback": "",
        "needs_replan": False,
        "grounding_passed": False,
        "iteration": 0,
    }
    result = await agent_graph.ainvoke(state)
    return result["answer"]


@mcp.tool()
async def ingest_document(
    source_type: Annotated[
        Literal["pdf", "youtube", "web"],
        Field(description="Type of source: pdf, youtube, or web"),
    ],
    location: Annotated[
        str,
        Field(description="File path for pdf, YouTube URL for youtube, web URL for web"),
    ],
    name: Annotated[
        str | None,
        Field(description="Human-readable label. Defaults: pdf → file basename, youtube/web → URL"),
    ] = None,
) -> str:
    """Ingest a document into the knowledge base. Returns JSON: {source_id, source_type, name}."""
    if source_type == "pdf":
        from app.services.ingestion.pdf import ingest_pdf
        resolved_name = name or Path(location).name
        ext = Path(location).suffix.lower()
        content_type = {
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".txt": "text/plain",
        }.get(ext, "application/pdf")
        source_id = await ingest_pdf(
            file_path=location, filename=resolved_name, content_type=content_type
        )

    elif source_type == "youtube":
        from app.services.ingestion.youtube import ingest_youtube
        resolved_name = name or location
        source_id = await ingest_youtube(url=location)

    elif source_type == "web":
        from app.services.ingestion.web import ingest_web
        resolved_name = name or location
        source_id = await ingest_web(url=location)

    else:
        raise ValueError(f"Unknown source_type: {source_type!r}")

    return json.dumps({"source_id": source_id, "source_type": source_type, "name": resolved_name})


@mcp.tool()
async def list_documents() -> str:
    """List all ingested documents across all source types.

    Returns JSON array: [{"source_id": "...", "type": "pdf|youtube|web", "name": "..."}, ...]
    Name field per type: pdf → filename payload field, youtube/web → title payload field.
    """
    from app.core.qdrant import get_qdrant_client
    from qdrant_client.http.exceptions import UnexpectedResponse

    _COLLECTIONS = {
        "pdf_chunks": ("pdf", "filename"),
        "youtube_chunks": ("youtube", "title"),
        "web_chunks": ("web", "title"),
    }

    client = get_qdrant_client()
    seen: dict[str, dict] = {}

    for collection_name, (source_type, name_field) in _COLLECTIONS.items():
        offset = None
        try:
            while True:
                results, next_offset = client.scroll(
                    collection_name=collection_name,
                    limit=100,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                for point in results:
                    payload = point.payload or {}
                    source_id = payload.get("source_id")
                    if source_id and source_id not in seen:
                        seen[source_id] = {
                            "source_id": source_id,
                            "type": source_type,
                            "name": payload.get(name_field, ""),
                        }
                if next_offset is None:
                    break
                offset = next_offset
        except UnexpectedResponse:
            logger.debug("Collection %s does not exist yet, skipping", collection_name)

    return json.dumps(list(seen.values()))


if __name__ == "__main__":
    mcp.run(transport="stdio")
```

- [ ] **Step 4: Run the tests to confirm they pass**

```bash
cd "/Users/divyanshu/Desktop/All Projects/docchat" && \
  venv/bin/pytest tests/test_mcp_server.py -v
```

Expected: both tests PASS

- [ ] **Step 5: Smoke-test the server starts without crashing**

```bash
cd "/Users/divyanshu/Desktop/All Projects/docchat" && \
  echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"0"}}}' | \
  venv/bin/python app/mcp_server.py 2>/dev/null | head -1
```

Expected: a JSON line starting with `{"jsonrpc":"2.0"` containing `"result"`. If you see `{"jsonrpc":"2.0","id":1,"result":{...}}` the server is functional.

---

## Task 4: Configure Claude Desktop

**Files:**
- Modify: `~/Library/Application Support/Claude/claude_desktop_config.json`

- [ ] **Step 1: Open (or create) the Claude Desktop config**

```bash
cat "$HOME/Library/Application Support/Claude/claude_desktop_config.json" 2>/dev/null || echo "{}"
```

Note the current contents.

- [ ] **Step 2: Write the updated config**

If the file already has an `mcpServers` key, merge the `docchat` entry in. If the file is empty or missing, write:

```json
{
  "mcpServers": {
    "docchat": {
      "command": "/Users/divyanshu/Desktop/All Projects/docchat/venv/bin/python",
      "args": ["/Users/divyanshu/Desktop/All Projects/docchat/app/mcp_server.py"]
    }
  }
}
```

> **Important:** Use the absolute path to the venv `python`. Claude Desktop launches with a minimal PATH — bare `python` will either fail to resolve or resolve to the system interpreter where `mcp` is not installed.

- [ ] **Step 3: Fully quit and relaunch Claude Desktop**

Cmd+Q (not just close the window). Reopen. Check Settings → Developer → MCP Servers — `docchat` should appear with a green indicator.

- [ ] **Step 4: End-to-end test in a Claude Desktop conversation**

Open a new conversation in Claude Desktop. Ask:

> "Use the list_documents tool to show me what's in the knowledge base."

Expected: Claude calls `list_documents` and returns a JSON array (possibly empty if no documents ingested yet). No error banner.

Then ingest a document if you want a full round-trip:

> "Use ingest_document to ingest the PDF at `/path/to/some.pdf`."

Then query it:

> "Use query_documents to ask: what is this document about?"

---

## Self-Review Checklist

**Spec coverage:**
- [x] `query_documents` tool with `query` + `source_ids` params → Task 3
- [x] `ingest_document` tool with `source_type`, `location`, `name` → Task 3
- [x] `list_documents` tool → Task 3
- [x] `print()` fix in retriever.py → Task 1
- [x] `mcp>=1.27.0` in requirements.txt → Task 2
- [x] `logging.basicConfig(stream=sys.stderr)` → Task 3 (line 1 of mcp_server.py)
- [x] Absolute venv path in Claude Desktop config → Task 4
- [x] `sources` param dropped (planner overrides it) → not present in Task 3
- [x] `source_ids` honored → Task 3 (`state["source_ids"] = source_ids or []`)
- [x] `ingest_document` returns parseable JSON → Task 3 (`json.dumps(...)`)
- [x] `list_documents` returns parseable JSON array with shape `{source_id, type, name}` → Task 3
- [x] Non-existent collection handled gracefully → Task 3 (`except UnexpectedResponse`)
