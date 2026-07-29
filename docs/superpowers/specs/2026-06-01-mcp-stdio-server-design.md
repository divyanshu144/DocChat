# MCP stdio Server Design

## Goal

Expose DocChat's document ingestion and query pipeline as an MCP (Model Context Protocol) stdio server so Claude Desktop and other MCP clients can call it as a set of tools.

## Constraints

- Single new file: `app/mcp_server.py`. No changes to `app/main.py`, pipeline architecture, or database schema.
- Permitted side-effect: fix 3 latent `print()` calls in `retriever.py` (lines 48, 57, 68) that would corrupt the stdio JSON-RPC channel.
- Transport: stdio. stdout is owned by FastMCP's JSON-RPC layer — all logging must go to stderr.
- No new PostgreSQL dependency in the MCP path. Ingestion writes only to Qdrant. Queries run the LangGraph pipeline directly (also Qdrant-only).

---

## Tools

### `query_documents`

Runs the full 5-node LangGraph pipeline (Planner → Retriever → Synthesizer → Grounding → Critic) and returns the final answer.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `query` | `str` | Natural language question to ask the knowledge base |
| `source_ids` | `list[str] \| None` | Restrict retrieval to specific source IDs. Omit to search all. |

**Notes:**
- `sources` is intentionally absent. The Planner node unconditionally overwrites `sources_to_use` with its own LLM decision — a caller-supplied value would be silently discarded.
- `source_ids` is honored: the Retriever builds a Qdrant `MatchAny` filter from it. Planner does not touch it.
- Returns the `state["answer"]` string, which contains inline citations formatted as `[PDF — file.pdf p.3]`.

**Returns:** `str` — answer with inline citations.

---

### `ingest_document`

Ingests a document into the Qdrant knowledge base. Awaits full ingestion before returning (all ingestion services call `client.upsert()` and return `source_id` — no fire-and-forget).

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `source_type` | `Literal["pdf", "youtube", "web"]` | Type of source |
| `location` | `str` | File path (pdf), YouTube URL (youtube), or web URL (web) |
| `name` | `str \| None` | Optional human-readable label. Defaults: pdf → basename of path, youtube/web → URL |

**Returns:** JSON string `{"source_id": "...", "source_type": "...", "name": "..."}` — parseable by the caller. `name` reflects the resolved label (after applying the default).

---

### `list_documents`

Lists all ingested sources across the three Qdrant collections (`pdf_chunks`, `youtube_chunks`, `web_chunks`).

**Returns:** JSON string — a list of objects, each with shape:
```json
[{"source_id": "...", "type": "pdf|youtube|web", "name": "..."}, ...]
```

Uses Qdrant scroll (not search) to enumerate distinct `source_id` values, deduplicating by `source_id` across collections. The `name` field per source type: pdf → `filename` payload field, youtube → `title` payload field, web → `title` payload field.

---

## Architecture

```
Claude Desktop
      │  stdio (JSON-RPC)
      ▼
app/mcp_server.py  (FastMCP)
      │
      ├── query_documents ──► agent_graph.ainvoke()  (LangGraph pipeline)
      │                              └── Qdrant (read)
      │
      ├── ingest_document ──► pdf/youtube/web ingestion service
      │                              └── Qdrant (write)
      │
      └── list_documents ──► Qdrant scroll (3 collections, read)
```

No FastAPI app, no HTTP server, no PostgreSQL in this path.

---

## Files Changed

| File | Change |
|------|--------|
| `app/mcp_server.py` | Create — FastMCP server, three tools |
| `app/agent/nodes/retriever.py` | Fix lines 48, 57, 68: `print()` → `logger.debug()` |
| `requirements.txt` | Add `mcp>=1.27.0` |

---

## stdio Safety

FastMCP's `transport="stdio"` owns stdout entirely — the JSON-RPC framing writes directly to `sys.stdout`. Any non-JSON bytes on stdout (from `print()` or third-party banners) corrupts the channel silently.

Mitigations:
1. `logging.basicConfig(stream=sys.stderr)` at the top of `mcp_server.py` — redirects all Python logging to stderr.
2. Fix the 3 `print()` calls in `retriever.py` before the server is used.
3. Import chain is clean at import time — no third-party library writes to stdout on import.

---

## Claude Desktop Configuration

`~/Library/Application Support/Claude/claude_desktop_config.json`:

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

Absolute venv path required — Claude Desktop launches with minimal PATH and bare `python` may resolve to the system interpreter where `mcp` is not installed.

---

## Out of Scope (v1)

- Streaming answers over MCP
- `sources` filter (planner overrides it — deferred to after planner is refactored)
- Authentication / per-user scoping
- Delete / re-ingest tools
