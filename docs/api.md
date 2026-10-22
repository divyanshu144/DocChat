# API reference, configuration and data model

Moved from the README. See the [README](../README.md) for setup.

## API reference

All endpoints (except `/api/v1/health`, `/api/v1/auth/signup`, `/api/v1/auth/login`, `/api/v1/auth/refresh`) require a Bearer token in the `Authorization` header.

### Auth

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/auth/signup` | Create account and return `access_token` + `refresh_token` |
| `POST` | `/api/v1/auth/login` | Log in; returns `access_token` + `refresh_token` |
| `POST` | `/api/v1/auth/refresh` | Exchange refresh token for new access token |
| `POST` | `/api/v1/auth/logout` | Revoke refresh token |
| `GET` | `/api/v1/auth/me` | Current user info |

**Login example:**

```bash
curl -X POST http://localhost:8080/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "secret"}'
# → {"access_token": "eyJ...", "refresh_token": "eyJ...", "token_type": "bearer"}
```

### Ingest

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/ingest/pdf` | Upload a PDF (`multipart/form-data`, field `file`). |
| `POST` | `/api/v1/ingest/youtube` | Ingest a YouTube video (`{"url": "..."}`). |
| `POST` | `/api/v1/ingest/web` | Scrape a web page (`{"url": "..."}`). |
| `GET` | `/api/v1/sources` | List all ingested sources. |
| `DELETE` | `/api/v1/sources/{source_id}` | Delete a source and its chunks from Qdrant. |

There's also an async, job-based path (`POST /api/v1/ingest/{pdf,youtube,web}/jobs` +
`GET /api/v1/ingest/jobs/{job_id}`) for persisted ingestion jobs — added alongside the
synchronous routes above; not yet documented here in detail.

**PDF example:**

```bash
curl -X POST http://localhost:8080/api/v1/ingest/pdf \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@paper.pdf"
```

### Chat

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/chat` | Send a query; returns an SSE stream. Pass `conversation_id` to continue a conversation; omit to start a new one. |

**Request body:**

```json
{
  "query": "What are the key findings?",
  "conversation_id": "optional-uuid",
  "sources": ["pdf", "youtube"],
  "source_ids": ["abc-123", "def-456"]
}
```

- `sources` — filter source types in `source_chunks` (`pdf`, `youtube`, `web`). Omit to search all source types.
- `source_ids` — restrict retrieval to specific ingested documents by their `source_id`. Omit (or pass `[]`) to search across all sources of the selected types.

**Response:** SSE stream — one token per `data:` line, `[DONE]` at end, `[ERROR]` on failure. The response header `X-Conversation-Id` carries the conversation UUID for subsequent requests.

```
data: The

data:  key

data:  findings are...

data: [DONE]
```

### Conversations

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/conversations` | List all conversations (id, title, folder_id, created_at). |
| `GET` | `/api/v1/conversations/{id}` | Get a conversation with full message history. |
| `PATCH` | `/api/v1/conversations/{id}` | Move to a folder (`{"folder_id": "uuid"}`) or unassign (`{"folder_id": null}`). |

### Folders

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/folders` | Create a folder (`{"name": "My Project"}`). |
| `GET` | `/api/v1/folders` | List all folders with conversation counts. |
| `PATCH` | `/api/v1/folders/{id}` | Rename a folder (`{"name": "New Name"}`). |
| `DELETE` | `/api/v1/folders/{id}` | Delete a folder; its conversations become uncategorised. |

### Health

```
GET /api/v1/health
# 200 when both probes succeed; 503 otherwise
# {"status":"ok","version":"2.0.0","timestamp":"...",
#  "dependencies":{"database":"ok","qdrant":"ok"}}
```

---

## Configuration

All settings load from environment variables or a `.env` file.

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `groq` | Chat provider: `groq`, `openai`, `mistral`, or `local` (self-hosted, e.g. vLLM) |
| `FALLBACK_LLM_PROVIDER` | `openai` | Cross-provider fallback for retryable Groq failures; requires `OPENAI_API_KEY` |
| `GROQ_API_KEY` | *(required for Groq)* | Groq API key |
| `OPENAI_API_KEY` | *(required for OpenAI)* | OpenAI API key |
| `LOCAL_BASE_URL` | *(empty)* | Base URL of a self-hosted OpenAI-compatible server (e.g. a vLLM pod); required for `LLM_PROVIDER=local` |
| `LOCAL_CHAT_MODEL` | *(empty)* | Model name as served by the local endpoint |
| `LOCAL_API_KEY` | *(empty)* | Bearer token for the local endpoint, if it requires one |
| `JWT_SECRET_KEY` | *(required)* | Secret for signing JWTs — use a long random string |
| `DATABASE_URL` | `postgresql+asyncpg://docchat:docchat@localhost:5432/docchat` | SQLAlchemy async DSN |
| `QDRANT_HOST` | `localhost` | Qdrant host (use `qdrant` inside Docker Compose) |
| `QDRANT_PORT` | `6333` | Qdrant REST port |
| `CHAT_MODEL` | `openai/gpt-oss-120b` | Groq model ID |
| `GROQ_FALLBACK_CHAT_MODEL` | *(empty)* | Optional same-provider Groq fallback before cross-provider fallback |
| `OPENAI_REASONING_EFFORT` | blank | Optional reasoning setting; blank preserves model default |
| `OPENAI_CHAT_MODEL` | `gpt-5.6-luna` | OpenAI model ID |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | fastembed model name |
| `EMBEDDING_DIM` | `384` | Vector dimension (must match the embedding model) |
| `RETRIEVAL_MIN_SCORE` | `0.3` | Minimum cosine similarity for retrieved chunks |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Access token lifetime |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh token lifetime |
| `LANGSMITH_API_KEY` | `None` | Enables LangSmith tracing when set |
| `LANGSMITH_PROJECT` | `docchat-agent` | LangSmith project name |
| `DEBUG` | `false` | Enable SQLAlchemy query logging |

---

## Database schema

```
users  ──< refresh_tokens
users  ──< conversations  ──< messages
folders  ──< conversations
```

Schema columns are added automatically at startup via idempotent migrations (using `information_schema.columns` on PostgreSQL). No manual schema changes are needed when upgrading.

---

## Folder & conversation organisation

- **New Folder** — click the button in the sidebar, type a name, press Enter
- **New chat in folder** — hover over a folder name; click the `+` button that appears; the next message you send creates a conversation automatically assigned to that folder
- **Move by drag-and-drop** — drag any conversation item onto a folder header; the folder highlights with a dashed border while hovering; drop to move
- **Move via menu** — hover over a conversation, click `⋯`, select a target folder or "Uncategorized"
- **Delete folder** — `DELETE /api/v1/folders/{id}`; conversations are uncategorised, not deleted
