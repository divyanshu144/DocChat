# Scale Upgrade: Qdrant + PostgreSQL + Grounding Verifier

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade DocChat from ChromaDB+SQLite to Qdrant+PostgreSQL and add a grounding verifier node to the LangGraph agent, enabling production-scale document handling with near-zero hallucination.

**Architecture:** Swap `app/core/chroma.py` for `app/core/qdrant.py` (same singleton pattern, different client); update all 3 ingestion services and the retriever node to use Qdrant's API (scores instead of distances, payload instead of metadatas, UUID point IDs); add a `grounding` node between `synthesizer` and `critic` that strips ungrounded sentences from the answer using an LLM verification call.

**Tech Stack:** `qdrant-client>=1.9.0`, `asyncpg>=0.29.0`, Qdrant Docker image, PostgreSQL Docker image, existing `fastembed`, `groq`, `langgraph` stack unchanged.

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `requirements.txt` | Modify | Add `qdrant-client`, `asyncpg`; remove `chromadb` |
| `app/core/config.py` | Modify | Add `qdrant_host/port`, `retrieval_min_score`; change `database_url` default to PostgreSQL |
| `app/core/qdrant.py` | Create | Singleton QdrantClient + `get_qdrant_collection()` helper (mirrors chroma.py shape) |
| `app/core/chroma.py` | Keep | Do NOT delete — existing data migration is out of scope |
| `app/services/ingestion/pdf.py` | Modify | Swap `get_collection` → `get_qdrant_collection`; use PointStruct upsert |
| `app/services/ingestion/youtube.py` | Modify | Same swap |
| `app/services/ingestion/web.py` | Modify | Same swap |
| `app/agent/nodes/retriever.py` | Modify | Swap to Qdrant search; add `score_threshold`; return `score` instead of `distance` |
| `app/agent/state.py` | Modify | Add `grounding_passed: bool` field |
| `app/agent/nodes/grounding.py` | Create | LLM-based grounding verifier; strips ungrounded sentences from answer |
| `app/agent/graph.py` | Modify | Insert `grounding` node between `synthesizer` and `critic` |
| `docker-compose.yml` | Modify | Replace `chromadb` service with `qdrant`; add `postgres` service |
| `tests/test_qdrant_core.py` | Create | Unit tests for `app/core/qdrant.py` singleton and collection helper |
| `tests/test_agent_retriever.py` | Modify | Update mocks from ChromaDB shape to Qdrant ScoredPoint shape |
| `tests/test_agent_grounding.py` | Create | Unit tests for grounding node — grounded, ungrounded, and passthrough cases |

---

## Task 1: Dependencies and Config

**Files:**
- Modify: `requirements.txt`
- Modify: `app/core/config.py`

- [ ] **Step 1: Update requirements.txt**

Replace `chromadb>=0.5.0` with Qdrant and asyncpg. Open `requirements.txt` and make these changes:

```text
# Remove this line:
chromadb>=0.5.0
aiosqlite==0.19.0

# Add these lines:
qdrant-client>=1.9.0
asyncpg>=0.29.0
```

Final relevant section of `requirements.txt` should look like:
```text
fastapi==0.104.1
uvicorn[standard]==0.24.0
pydantic>=2.7.4
pydantic-settings==2.1.0
python-multipart==0.0.6
sqlalchemy[asyncio]==2.0.46
asyncpg>=0.29.0
groq>=0.9.0
fastembed>=0.3.0
numpy>=1.26.0
nltk>=3.8.0
langchain-text-splitters>=0.2.0
pymupdf>=1.24.0
pytesseract>=0.3.10
Pillow>=10.0.0
python-docx==1.1.0
qdrant-client>=1.9.0
youtube-transcript-api>=0.6.0
pytube>=15.0.0
trafilatura>=1.9.0
httpx>=0.27.0,<0.28.0
langsmith>=0.1.0
langgraph>=0.2.0
langchain-core>=0.3.0
tokenizers>=0.19.0
python-jose[cryptography]==3.3.0
bcrypt>=4.0.0
pydantic[email]>=2.7.4
pytest>=8.0.0
pytest-asyncio>=0.23.0
```

- [ ] **Step 2: Install new dependencies**

```bash
pip install qdrant-client>=1.9.0 asyncpg>=0.29.0
```

Expected: both packages install without error.

- [ ] **Step 3: Add Qdrant and score settings to config.py**

In `app/core/config.py`, add these fields to the `Settings` class after the `# ChromaDB` block:

```python
    # ChromaDB (kept for reference — do not delete)
    chroma_host: str = "localhost"
    chroma_port: int = 8001

    # Qdrant
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333

    # Retrieval quality gate — chunks below this cosine similarity score are dropped
    retrieval_min_score: float = 0.3
```

Also change the `database_url` default to PostgreSQL:

```python
    database_url: str = f"sqlite+aiosqlite:///{_PROJECT_ROOT / 'docchat.db'}"
```
→
```python
    database_url: str = "postgresql+asyncpg://docchat:docchat@localhost:5432/docchat"
```

- [ ] **Step 4: Verify config loads**

```bash
python -c "from app.core.config import settings; print(settings.qdrant_host, settings.retrieval_min_score)"
```

Expected output: `localhost 0.3`

---

## Task 2: Qdrant Core Singleton

**Files:**
- Create: `app/core/qdrant.py`
- Create: `tests/test_qdrant_core.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_qdrant_core.py`:

```python
from unittest.mock import MagicMock, patch, call
import pytest
from qdrant_client.models import VectorParams, Distance


def test_get_qdrant_client_returns_singleton():
    with patch("app.core.qdrant.QdrantClient") as mock_cls:
        mock_cls.return_value = MagicMock()
        from app.core.qdrant import get_qdrant_client
        get_qdrant_client.cache_clear()
        c1 = get_qdrant_client()
        c2 = get_qdrant_client()
        assert c1 is c2
        assert mock_cls.call_count == 1
        get_qdrant_client.cache_clear()


def test_get_qdrant_collection_creates_if_missing():
    mock_client = MagicMock()
    mock_client.get_collection.side_effect = Exception("not found")

    with patch("app.core.qdrant.get_qdrant_client", return_value=mock_client):
        from app.core.qdrant import get_qdrant_collection
        get_qdrant_collection("pdf_chunks")

    mock_client.create_collection.assert_called_once_with(
        collection_name="pdf_chunks",
        vectors_config=VectorParams(size=384, distance=Distance.COSINE),
    )


def test_get_qdrant_collection_skips_create_if_exists():
    mock_client = MagicMock()
    mock_client.get_collection.return_value = MagicMock()

    with patch("app.core.qdrant.get_qdrant_client", return_value=mock_client):
        from app.core.qdrant import get_qdrant_collection
        get_qdrant_collection("pdf_chunks")

    mock_client.create_collection.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_qdrant_core.py -v
```

Expected: `ImportError` or `ModuleNotFoundError` — `app.core.qdrant` does not exist yet.

- [ ] **Step 3: Create app/core/qdrant.py**

```python
from functools import lru_cache
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams
from app.core.config import settings


@lru_cache()
def get_qdrant_client() -> QdrantClient:
    return QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)


def get_qdrant_collection(name: str) -> None:
    """Ensure collection exists with cosine HNSW index. Returns None — use name directly in upsert/search."""
    client = get_qdrant_client()
    try:
        client.get_collection(name)
    except Exception:
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=settings.embedding_dim, distance=Distance.COSINE),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_qdrant_core.py -v
```

Expected:
```
PASSED tests/test_qdrant_core.py::test_get_qdrant_client_returns_singleton
PASSED tests/test_qdrant_core.py::test_get_qdrant_collection_creates_if_missing
PASSED tests/test_qdrant_core.py::test_get_qdrant_collection_skips_create_if_exists
```

---

## Task 3: Update PDF Ingestion to Use Qdrant

**Files:**
- Modify: `app/services/ingestion/pdf.py`

> Qdrant differences vs ChromaDB:
> - IDs must be UUIDs (use `uuid.uuid5` for deterministic IDs from `source_id_chunkindex`)
> - Data lives in `payload` dict (no separate `documents`/`metadatas` params)
> - Use `upsert()` with `PointStruct` list
> - Collection must exist before upsert — call `get_qdrant_collection()` first

- [ ] **Step 1: Replace imports in pdf.py**

In `app/services/ingestion/pdf.py`, replace:
```python
from app.core.chroma import get_collection
```
with:
```python
import uuid as _uuid
from app.core.qdrant import get_qdrant_client, get_qdrant_collection
from qdrant_client.models import PointStruct
```

- [ ] **Step 2: Replace the upsert block in `ingest_pdf()`**

Find the block at the bottom of `ingest_pdf()` (lines 168–190) and replace it entirely:

```python
    get_qdrant_collection(COLLECTION)
    client = get_qdrant_client()
    points: list[PointStruct] = []
    now = datetime.now(timezone.utc).isoformat()

    for i, (chunk, emb) in enumerate(zip(raw_chunks, embeddings)):
        if emb is None:
            continue
        point_id = str(_uuid.uuid5(_uuid.NAMESPACE_DNS, f"{source_id}_{i}"))
        points.append(PointStruct(
            id=point_id,
            vector=emb.tolist(),
            payload={
                "text": chunk["text"],
                "source_id": source_id,
                "filename": filename,
                "page_number": chunk.get("page_number") or 0,
                "section_heading": chunk.get("section_heading") or "",
                "chunk_index": i,
                "ingested_at": now,
            },
        ))

    if points:
        client.upsert(collection_name=COLLECTION, points=points)

    return source_id
```

- [ ] **Step 3: Verify existing ingestion tests still import correctly**

```bash
pytest tests/test_ingestion_pdf.py -v
```

Expected: all tests pass or fail only on mock shape differences (we'll fix retriever tests in Task 6). No import errors.

---

## Task 4: Update YouTube Ingestion to Use Qdrant

**Files:**
- Modify: `app/services/ingestion/youtube.py`

- [ ] **Step 1: Replace imports in youtube.py**

Replace:
```python
from app.core.chroma import get_collection
```
with:
```python
import uuid as _uuid
from app.core.qdrant import get_qdrant_client, get_qdrant_collection
from qdrant_client.models import PointStruct
```

- [ ] **Step 2: Replace the upsert block in `ingest_youtube()`**

Find the block from `collection = get_collection(COLLECTION)` to `collection.add(...)` and replace entirely:

```python
    get_qdrant_collection(COLLECTION)
    client = get_qdrant_client()
    points: list[PointStruct] = []
    now = datetime.now(timezone.utc).isoformat()

    for i, chunk in enumerate(chunks):
        if not embedder:
            continue
        emb = embedder.embed_query(chunk["text"])
        point_id = str(_uuid.uuid5(_uuid.NAMESPACE_DNS, f"{source_id}_{i}"))
        points.append(PointStruct(
            id=point_id,
            vector=emb.tolist(),
            payload={
                "text": chunk["text"],
                "source_id": source_id,
                "video_id": meta["video_id"],
                "video_url": url,
                "title": meta["title"],
                "channel": meta["channel"],
                "timestamp_start": chunk["timestamp_start"],
                "timestamp_end": chunk["timestamp_end"],
                "chunk_index": i,
                "ingested_at": now,
            },
        ))

    if points:
        client.upsert(collection_name=COLLECTION, points=points)

    return source_id
```

- [ ] **Step 3: Run youtube ingestion tests**

```bash
pytest tests/test_ingestion_youtube.py -v
```

Expected: passes (mocks will need updating if they mock `collection.add` — fix by patching `get_qdrant_client` instead).

---

## Task 5: Update Web Ingestion to Use Qdrant

**Files:**
- Modify: `app/services/ingestion/web.py`

- [ ] **Step 1: Replace imports in web.py**

Replace:
```python
from app.core.chroma import get_collection
```
with:
```python
import uuid as _uuid
from app.core.qdrant import get_qdrant_client, get_qdrant_collection
from qdrant_client.models import PointStruct
```

- [ ] **Step 2: Replace the upsert block in `ingest_web()`**

Find the block from `collection = get_collection(COLLECTION)` to `collection.add(...)` and replace entirely:

```python
    get_qdrant_collection(COLLECTION)
    client = get_qdrant_client()
    points: list[PointStruct] = []
    now = datetime.now(timezone.utc).isoformat()

    for i, text in enumerate(chunk_texts):
        if not text.strip() or not embedder:
            continue
        emb = embedder.embed_query(text)
        point_id = str(_uuid.uuid5(_uuid.NAMESPACE_DNS, f"{source_id}_{i}"))
        points.append(PointStruct(
            id=point_id,
            vector=emb.tolist(),
            payload={
                "text": text,
                "source_id": source_id,
                "url": url,
                "title": scraped["title"],
                "domain": domain,
                "chunk_index": i,
                "scraped_at": now,
            },
        ))

    if points:
        client.upsert(collection_name=COLLECTION, points=points)

    return source_id
```

- [ ] **Step 3: Run web ingestion tests**

```bash
pytest tests/test_ingestion_web.py -v
```

Expected: passes.

---

## Task 6: Update Retriever to Use Qdrant

**Files:**
- Modify: `app/agent/nodes/retriever.py`
- Modify: `tests/test_agent_retriever.py`

> Key difference: Qdrant `search()` returns a list of `ScoredPoint` objects.
> Each `ScoredPoint` has: `.id`, `.score` (0–1, higher = more similar), `.payload` (dict with text + metadata).
> The `score_threshold` param in `search()` drops low-quality chunks server-side.

- [ ] **Step 1: Write updated failing tests**

Replace the contents of `tests/test_agent_retriever.py`:

```python
import pytest
import numpy as np
from unittest.mock import MagicMock, patch
from app.agent.state import AgentState
from app.agent.nodes.retriever import retriever_node


def _scored_point(text: str, score: float = 0.8, **payload_extra):
    sp = MagicMock()
    sp.score = score
    sp.payload = {"text": text, "filename": "doc.pdf", **payload_extra}
    return sp


def _base_state(**kwargs) -> AgentState:
    base: AgentState = {
        "query": "attention mechanisms",
        "conversation_id": "conv-1",
        "sources_to_use": ["pdf"],
        "source_ids": [],
        "retrieved_chunks": [],
        "answer": "",
        "critic_feedback": "",
        "needs_replan": False,
        "iteration": 0,
        "grounding_passed": False,
    }
    base.update(kwargs)
    return base


@pytest.mark.asyncio
async def test_retriever_queries_selected_sources():
    mock_client = MagicMock()
    mock_client.search.return_value = [_scored_point("chunk text", score=0.75)]
    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = np.array([0.1] * 384, dtype="float32")

    with (
        patch("app.agent.nodes.retriever.get_qdrant_client", return_value=mock_client),
        patch("app.agent.nodes.retriever.get_embedder", return_value=mock_embedder),
    ):
        result = await retriever_node(_base_state(sources_to_use=["pdf"]))

    assert len(result["retrieved_chunks"]) == 1
    assert result["retrieved_chunks"][0]["text"] == "chunk text"
    assert result["retrieved_chunks"][0]["source_type"] == "pdf"
    assert result["retrieved_chunks"][0]["score"] == 0.75


@pytest.mark.asyncio
async def test_retriever_deduplicates_chunks():
    mock_client = MagicMock()
    mock_client.search.return_value = [
        _scored_point("duplicate text", score=0.8),
        _scored_point("duplicate text", score=0.7),
    ]
    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = np.array([0.1] * 384, dtype="float32")

    with (
        patch("app.agent.nodes.retriever.get_qdrant_client", return_value=mock_client),
        patch("app.agent.nodes.retriever.get_embedder", return_value=mock_embedder),
    ):
        result = await retriever_node(_base_state(sources_to_use=["pdf"]))

    assert len(result["retrieved_chunks"]) == 1


@pytest.mark.asyncio
async def test_retriever_returns_empty_without_embedder():
    with patch("app.agent.nodes.retriever.get_embedder", return_value=None):
        result = await retriever_node(_base_state())

    assert result["retrieved_chunks"] == []


@pytest.mark.asyncio
async def test_retriever_applies_source_id_filter():
    mock_client = MagicMock()
    mock_client.search.return_value = [_scored_point("filtered chunk")]
    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = np.array([0.1] * 384, dtype="float32")

    with (
        patch("app.agent.nodes.retriever.get_qdrant_client", return_value=mock_client),
        patch("app.agent.nodes.retriever.get_embedder", return_value=mock_embedder),
    ):
        await retriever_node(_base_state(sources_to_use=["pdf"], source_ids=["src-123"]))

    call_kwargs = mock_client.search.call_args.kwargs
    assert call_kwargs["query_filter"] is not None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_agent_retriever.py -v
```

Expected: `ImportError` — retriever still imports from `chroma`.

- [ ] **Step 3: Rewrite app/agent/nodes/retriever.py**

```python
from qdrant_client.models import Filter, FieldCondition, MatchAny
from app.agent.state import AgentState
from app.core.qdrant import get_qdrant_client
from app.core.config import settings
from app.services.embedder import get_embedder

_SOURCE_COLLECTIONS = {
    "pdf": "pdf_chunks",
    "youtube": "youtube_chunks",
    "web": "web_chunks",
}
N_RESULTS = 8


async def retriever_node(state: AgentState) -> dict:
    embedder = get_embedder()
    if not embedder:
        return {"retrieved_chunks": []}

    query_emb = embedder.embed_query(state["query"]).tolist()
    source_ids = state.get("source_ids") or []
    client = get_qdrant_client()
    all_chunks: list[dict] = []

    qdrant_filter = (
        Filter(must=[FieldCondition(key="source_id", match=MatchAny(any=source_ids))])
        if source_ids
        else None
    )

    for source in state["sources_to_use"]:
        collection_name = _SOURCE_COLLECTIONS.get(source)
        if not collection_name:
            continue
        try:
            hits = client.search(
                collection_name=collection_name,
                query_vector=query_emb,
                limit=N_RESULTS,
                score_threshold=settings.retrieval_min_score,
                query_filter=qdrant_filter,
                with_payload=True,
            )
            for hit in hits:
                payload = hit.payload or {}
                all_chunks.append({
                    "text": payload.pop("text", ""),
                    "metadata": payload,
                    "source_type": source,
                    "score": hit.score,
                })
        except Exception:
            pass

    seen: set[str] = set()
    unique: list[dict] = []
    for chunk in all_chunks:
        if chunk["text"] not in seen:
            seen.add(chunk["text"])
            unique.append(chunk)

    return {"retrieved_chunks": unique}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_agent_retriever.py -v
```

Expected:
```
PASSED tests/test_agent_retriever.py::test_retriever_queries_selected_sources
PASSED tests/test_agent_retriever.py::test_retriever_deduplicates_chunks
PASSED tests/test_agent_retriever.py::test_retriever_returns_empty_without_embedder
PASSED tests/test_agent_retriever.py::test_retriever_applies_source_id_filter
```

---

## Task 7: Add Grounding Verifier Node

**Files:**
- Create: `app/agent/nodes/grounding.py`
- Create: `tests/test_agent_grounding.py`

> The synthesizer already formats answers with citations like `[PDF — paper.pdf p.3]`.
> The grounding verifier sends the answer + context to the LLM and asks it to return
> only the sentences that are supported by the context. Ungrounded sentences are dropped.
> If the LLM call fails, the original answer passes through unchanged.

- [ ] **Step 1: Write failing tests**

Create `tests/test_agent_grounding.py`:

```python
import pytest
from unittest.mock import patch, AsyncMock
from app.agent.state import AgentState
from app.agent.nodes.grounding import grounding_node


def _base_state(**kwargs) -> AgentState:
    base: AgentState = {
        "query": "What is attention?",
        "conversation_id": "conv-1",
        "sources_to_use": ["pdf"],
        "source_ids": [],
        "retrieved_chunks": [
            {
                "text": "Attention is a mechanism that allows the model to focus on relevant parts.",
                "metadata": {"filename": "paper.pdf", "page_number": 3},
                "source_type": "pdf",
                "score": 0.9,
            }
        ],
        "answer": "Attention is a mechanism. [PDF — paper.pdf p.3] The sky is green.",
        "critic_feedback": "",
        "needs_replan": False,
        "iteration": 0,
        "grounding_passed": False,
    }
    base.update(kwargs)
    return base


@pytest.mark.asyncio
async def test_grounding_passes_through_on_llm_failure():
    """If LLM call raises, original answer is preserved."""
    with patch(
        "app.agent.nodes.grounding.chat_complete",
        new_callable=AsyncMock,
        side_effect=Exception("LLM error"),
    ):
        result = await grounding_node(_base_state())

    assert result["answer"] == "Attention is a mechanism. [PDF — paper.pdf p.3] The sky is green."
    assert result["grounding_passed"] is False


@pytest.mark.asyncio
async def test_grounding_updates_answer_with_verified_text():
    """LLM returns cleaned answer — grounding_node stores it and sets grounding_passed=True."""
    cleaned = "Attention is a mechanism. [PDF — paper.pdf p.3]"
    with patch(
        "app.agent.nodes.grounding.chat_complete",
        new_callable=AsyncMock,
        return_value=cleaned,
    ):
        result = await grounding_node(_base_state())

    assert result["answer"] == cleaned
    assert result["grounding_passed"] is True


@pytest.mark.asyncio
async def test_grounding_skips_when_no_chunks():
    """No retrieved chunks → skip LLM call, pass through answer unchanged."""
    state = _base_state(retrieved_chunks=[])
    with patch("app.agent.nodes.grounding.chat_complete", new_callable=AsyncMock) as mock_llm:
        result = await grounding_node(state)

    mock_llm.assert_not_called()
    assert result["grounding_passed"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_agent_grounding.py -v
```

Expected: `ImportError` — module does not exist yet.

- [ ] **Step 3: Create app/agent/nodes/grounding.py**

```python
from app.agent.state import AgentState
from app.services.llm import chat_complete

_SYSTEM = """\
You are a grounding verifier. Your only job is to remove ungrounded sentences from an answer.

You are given:
1. Context chunks (the only valid source of truth)
2. An answer that may contain sentences not supported by those chunks

Rules:
- Keep sentences that are directly supported by the context, even if paraphrased.
- Keep meta-sentences like "Based on the provided context..." or "I don't have enough information..."
- Keep all citation markers like [PDF — ...], [YouTube — ...], [Web — ...].
- DROP sentences that make factual claims not found anywhere in the context.
- Output ONLY the cleaned answer text. No explanations. No preamble.

Context:
{context}
"""


def _format_context(chunks: list[dict]) -> str:
    parts = []
    for chunk in chunks:
        meta = chunk.get("metadata", {})
        src = chunk.get("source_type", "unknown").upper()
        if src == "PDF":
            label = f"[PDF — {meta.get('filename', '')} p.{meta.get('page_number', '')}]"
        elif src == "YOUTUBE":
            label = f"[YouTube — {meta.get('title', '')} @{meta.get('timestamp_start', '')}s]"
        else:
            label = f"[Web — {meta.get('url', '')}]"
        parts.append(f"{label}\n{chunk['text']}")
    return "\n\n---\n\n".join(parts)


async def grounding_node(state: AgentState) -> dict:
    if not state.get("retrieved_chunks"):
        return {"answer": state["answer"], "grounding_passed": False}

    context = _format_context(state["retrieved_chunks"])
    messages = [
        {"role": "system", "content": _SYSTEM.format(context=context)},
        {"role": "user", "content": state["answer"]},
    ]
    try:
        cleaned = await chat_complete(messages, max_tokens=1024)
        return {"answer": cleaned.strip(), "grounding_passed": True}
    except Exception:
        return {"answer": state["answer"], "grounding_passed": False}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_agent_grounding.py -v
```

Expected:
```
PASSED tests/test_agent_grounding.py::test_grounding_passes_through_on_llm_failure
PASSED tests/test_agent_grounding.py::test_grounding_updates_answer_with_verified_text
PASSED tests/test_agent_grounding.py::test_grounding_skips_when_no_chunks
```

---

## Task 8: Update AgentState and Graph

**Files:**
- Modify: `app/agent/state.py`
- Modify: `app/agent/graph.py`

- [ ] **Step 1: Add grounding_passed to AgentState**

In `app/agent/state.py`, add one field:

```python
from typing import TypedDict


class AgentState(TypedDict):
    query: str
    conversation_id: str
    sources_to_use: list[str]
    source_ids: list[str]
    retrieved_chunks: list[dict]
    answer: str
    critic_feedback: str
    needs_replan: bool
    iteration: int
    grounding_passed: bool   # True when grounding verifier ran and cleaned the answer
```

- [ ] **Step 2: Insert grounding node into graph.py**

In `app/agent/graph.py`, add the import and insert `grounding` between `synthesizer` and `critic`:

```python
import os
from langgraph.graph import StateGraph, END

from app.agent.state import AgentState
from app.agent.nodes.planner import planner_node
from app.agent.nodes.retriever import retriever_node
from app.agent.nodes.synthesizer import synthesizer_node
from app.agent.nodes.grounding import grounding_node
from app.agent.nodes.critic import critic_node
from app.core.config import settings


def _route_critic(state: AgentState) -> str:
    if state.get("needs_replan") and state.get("iteration", 0) < 2:
        return "planner"
    return END


def _configure_langsmith() -> None:
    if settings.langsmith_api_key:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
        os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project


def build_graph():
    _configure_langsmith()

    g = StateGraph(AgentState)
    g.add_node("planner", planner_node)
    g.add_node("retriever", retriever_node)
    g.add_node("synthesizer", synthesizer_node)
    g.add_node("grounding", grounding_node)
    g.add_node("critic", critic_node)

    g.set_entry_point("planner")
    g.add_edge("planner", "retriever")
    g.add_edge("retriever", "synthesizer")
    g.add_edge("synthesizer", "grounding")
    g.add_edge("grounding", "critic")
    g.add_conditional_edges("critic", _route_critic, {"planner": "planner", END: END})

    return g.compile()


agent_graph = build_graph()
```

- [ ] **Step 3: Run the full agent graph test suite**

```bash
pytest tests/test_agent_graph.py tests/test_agent_synthesizer_critic.py -v
```

Expected: all pass. If `test_agent_graph.py` builds the graph and fails because `AgentState` now requires `grounding_passed`, update the test fixtures to include `grounding_passed: False`.

- [ ] **Step 4: Run all tests**

```bash
pytest tests/ -v --ignore=tests/test_chroma.py
```

Expected: all pass (we ignore `test_chroma.py` since it tests the old ChromaDB module we're keeping but not actively using).

---

## Task 9: Update Docker Compose

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Replace chromadb with qdrant and add postgres**

Replace the entire `docker-compose.yml` with:

```yaml
services:
  app:
    build: .
    ports:
      - "8080:8000"
    env_file: .env
    environment:
      - QDRANT_HOST=qdrant
      - QDRANT_PORT=6333
      - DATABASE_URL=postgresql+asyncpg://docchat:docchat@postgres:5432/docchat
    depends_on:
      qdrant:
        condition: service_healthy
      postgres:
        condition: service_healthy
    volumes:
      - ./data:/app/data
      - ./app:/app/app

  qdrant:
    image: qdrant/qdrant:latest
    ports:
      - "6333:6333"
      - "6334:6334"
    volumes:
      - ./qdrant_data:/qdrant/storage
    healthcheck:
      test: ["CMD", "bash", "-c", "< /dev/tcp/localhost/6333"]
      interval: 10s
      timeout: 5s
      retries: 5

  postgres:
    image: postgres:16-alpine
    ports:
      - "5432:5432"
    environment:
      POSTGRES_USER: docchat
      POSTGRES_PASSWORD: docchat
      POSTGRES_DB: docchat
    volumes:
      - ./postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U docchat"]
      interval: 10s
      timeout: 5s
      retries: 5
```

- [ ] **Step 2: Start the stack and verify Qdrant is reachable**

```bash
docker-compose up -d qdrant postgres
```

Wait ~10 seconds, then:

```bash
curl http://localhost:6333/healthz
```

Expected: `{"title":"qdrant - vector search engine","version":"..."}`

- [ ] **Step 3: Verify PostgreSQL is reachable**

```bash
docker-compose exec postgres psql -U docchat -c "\l"
```

Expected: shows `docchat` database in the list.

---

## Task 10: End-to-End Smoke Test

- [ ] **Step 1: Start the full stack**

```bash
docker-compose up -d
```

- [ ] **Step 2: Check app startup logs**

```bash
docker-compose logs app --tail=30
```

Expected: `Application startup complete` with no import errors or connection errors.

- [ ] **Step 3: Ingest a small PDF via API**

```bash
curl -X POST http://localhost:8080/api/v1/ingest/pdf \
  -F "file=@/path/to/any/small.pdf" \
  -H "Authorization: Bearer <your-token>"
```

Expected: `{"source_id": "..."}` response.

- [ ] **Step 4: Verify the chunk landed in Qdrant**

```bash
curl http://localhost:6333/collections/pdf_chunks
```

Expected: JSON with `"points_count": <N>` where N > 0.

- [ ] **Step 5: Run a chat query and check grounding_passed**

```bash
curl -X POST http://localhost:8080/api/v1/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <your-token>" \
  -d '{"query": "summarize the document", "conversation_id": "test-conv-1", "sources_to_use": ["pdf"]}'
```

Expected: streaming SSE response with citations. No `[ERROR]` events.

---

## Self-Review

### Spec Coverage
- [x] ChromaDB → Qdrant swap: Tasks 2–6
- [x] SQLite → PostgreSQL: Task 1 (config), Task 9 (docker-compose)
- [x] Confidence threshold gating: Task 6 (`score_threshold=settings.retrieval_min_score` in retriever)
- [x] Grounding verifier node: Tasks 7–8
- [x] Infrastructure update: Task 9
- [x] End-to-end validation: Task 10

### Type Consistency
- `AgentState.grounding_passed: bool` defined in Task 8, used in Task 7 (`grounding_node` returns it), referenced in tests Task 7
- `get_qdrant_client()` defined in Task 2, imported in Tasks 3–6
- `get_qdrant_collection(name)` defined in Task 2, called in Tasks 3–5 (not in retriever — retriever calls `client.search` directly on existing collections)
- `score` field on chunks: set in Task 6 retriever, not read by synthesizer/grounding/critic (safe)

### No Placeholders Check
All code blocks are complete. No "TODO", "TBD", or "implement later" in any step.
