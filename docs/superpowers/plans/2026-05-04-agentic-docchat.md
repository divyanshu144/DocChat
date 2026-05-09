# Agentic DocChat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Evolve DocChat into a multi-source agentic research assistant using LangGraph, ChromaDB, and LangSmith.

**Architecture:** Single FastAPI service. LangGraph agent (Planner → Retriever → Synthesizer → Critic) orchestrates retrieval across three ChromaDB collections (pdf_chunks, youtube_chunks, web_chunks). Existing DocChat PDF parser and Groq client are reused; BM25/SQLite retrieval, FlashRank, and old API endpoints are deleted.

**Tech Stack:** FastAPI, LangGraph, ChromaDB, Groq (AsyncGroq), fastembed (BAAI/bge-small-en-v1.5), youtube-transcript-api, pytube, trafilatura, httpx, LangSmith, SQLite (conversation history only), Docker Compose.

---

## Pre-flight: Delete Existing DB

The schema changes incompatibly. Before running the app after this migration, delete `docchat.db`:
```bash
rm -f docchat.db docchat.db-shm docchat.db-wal
```

---

## Task 0: Foundation Files (embedder + health)

**Files:**
- Create/Replace: `app/services/embedder.py`
- Verify: `app/api/health.py` (already correct — add test only)
- Create: `tests/test_embedder.py`
- Create: `tests/test_api_health.py`

These two files are depended on by every subsequent task. Establish them first.

### 0a — Embedder

- [ ] **Step 1: Write failing test**

Create `tests/test_embedder.py`:

```python
import numpy as np
from unittest.mock import MagicMock, patch
from app.services.embedder import get_embedder


def test_get_embedder_returns_singleton():
    from app.services.embedder import get_embedder
    # Clear module-level singleton so the mock takes effect
    import app.services.embedder as emb_mod
    emb_mod._embedder_instance = None

    mock_fe = MagicMock()
    mock_fe.embed.return_value = iter([np.array([0.1] * 384, dtype="float32")])

    with patch("app.services.embedder.TextEmbedding", return_value=mock_fe):
        e1 = get_embedder()
        e2 = get_embedder()

    assert e1 is e2  # singleton


def test_embed_query_returns_ndarray():
    import app.services.embedder as emb_mod
    emb_mod._embedder_instance = None

    mock_fe = MagicMock()
    mock_fe.embed.return_value = iter([np.array([0.1] * 384, dtype="float32")])

    with patch("app.services.embedder.TextEmbedding", return_value=mock_fe):
        embedder = get_embedder()

    mock_fe.embed.return_value = iter([np.array([0.2] * 384, dtype="float32")])
    result = embedder.embed_query("hello world")
    assert isinstance(result, np.ndarray)
    assert result.shape == (384,)
    emb_mod._embedder_instance = None


def test_get_embedder_returns_none_on_import_error():
    import app.services.embedder as emb_mod
    emb_mod._embedder_instance = None

    with patch("app.services.embedder.TextEmbedding", side_effect=ImportError("no fastembed")):
        result = get_embedder()

    assert result is None
    emb_mod._embedder_instance = None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_embedder.py -v
```

Expected: `ImportError` or `AttributeError` — module doesn't match expected interface yet.

- [ ] **Step 3: Replace `app/services/embedder.py`**

Write the following (replaces the existing untracked file entirely):

```python
"""
Embedding service using fastembed (BAAI/bge-small-en-v1.5, 384-dim).

Provides a unified interface used by all three ingestion services and the
retriever node. Returns None gracefully if fastembed is unavailable so the
rest of the app can still start in degraded mode.
"""

from __future__ import annotations

import logging
import numpy as np

logger = logging.getLogger(__name__)

_embedder_instance: "_Embedder | None" = None


def get_embedder() -> "_Embedder | None":
    """Lazy-init singleton. Returns None if fastembed fails to load."""
    global _embedder_instance
    if _embedder_instance is not None:
        return _embedder_instance
    try:
        from app.core.config import settings
        _embedder_instance = _Embedder(settings.embedding_model)
    except Exception:
        logger.exception("embedder_init_failed — running without embeddings")
    return _embedder_instance


class _Embedder:
    """Thin wrapper around fastembed.TextEmbedding with a stable public API."""

    def __init__(self, model_name: str) -> None:
        from app.services.embedder import TextEmbedding  # local import so mock patches work
        self._fe = TextEmbedding(model_name=model_name)
        # Warm-up: forces model download before the first real request
        list(self._fe.embed(["warmup"]))

    def embed_query(self, text: str) -> np.ndarray:
        """Embed a single query string. Returns float32 ndarray of shape (dim,)."""
        return next(self._fe.embed([text])).astype(np.float32)

    def embed_independently(self, texts: list[str]) -> list[np.ndarray]:
        """Embed each text independently. Returns list of float32 ndarrays."""
        return [e.astype(np.float32) for e in self._fe.embed(texts)]

    def embed_late(
        self,
        segment_text: str,
        chunk_texts: list[str],
        chunk_char_starts: list[int],
    ) -> list[np.ndarray]:
        """Embed chunks with segment context. Degrades to independent embedding in v1."""
        return self.embed_independently(chunk_texts)
```

- [ ] **Step 4: Fix the import inside `_Embedder.__init__`**

The `__init__` does `from app.services.embedder import TextEmbedding` which is wrong — it should import from `fastembed`. Fix it:

```python
    def __init__(self, model_name: str) -> None:
        from fastembed import TextEmbedding
        self._fe = TextEmbedding(model_name=model_name)
        list(self._fe.embed(["warmup"]))
```

Also add the top-level import so the mock in tests can patch it:

```python
try:
    from fastembed import TextEmbedding
except ImportError:
    TextEmbedding = None  # type: ignore[assignment,misc]
```

Final `app/services/embedder.py`:

```python
"""
Embedding service using fastembed (BAAI/bge-small-en-v1.5, 384-dim).

Provides a unified interface used by all three ingestion services and the
retriever node. Returns None gracefully if fastembed is unavailable so the
rest of the app can still start in degraded mode.
"""

from __future__ import annotations

import logging
import numpy as np

logger = logging.getLogger(__name__)

try:
    from fastembed import TextEmbedding
except ImportError:
    TextEmbedding = None  # type: ignore[assignment,misc]

_embedder_instance: "_Embedder | None" = None


def get_embedder() -> "_Embedder | None":
    """Lazy-init singleton. Returns None if fastembed fails to load."""
    global _embedder_instance
    if _embedder_instance is not None:
        return _embedder_instance
    try:
        from app.core.config import settings
        _embedder_instance = _Embedder(settings.embedding_model)
    except Exception:
        logger.exception("embedder_init_failed — running without embeddings")
    return _embedder_instance


class _Embedder:
    """Thin fastembed wrapper with a stable public API."""

    def __init__(self, model_name: str) -> None:
        if TextEmbedding is None:
            raise ImportError("fastembed is not installed")
        self._fe = TextEmbedding(model_name=model_name)
        list(self._fe.embed(["warmup"]))

    def embed_query(self, text: str) -> np.ndarray:
        """Embed a single string. Returns float32 ndarray shape (dim,)."""
        return next(self._fe.embed([text])).astype(np.float32)

    def embed_independently(self, texts: list[str]) -> list[np.ndarray]:
        """Embed each text independently."""
        return [e.astype(np.float32) for e in self._fe.embed(texts)]

    def embed_late(
        self,
        segment_text: str,
        chunk_texts: list[str],
        chunk_char_starts: list[int],
    ) -> list[np.ndarray]:
        """Embed chunks. Degrades to independent embedding in v1."""
        return self.embed_independently(chunk_texts)
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/test_embedder.py -v
```

Expected: `PASSED`

### 0b — Health endpoint

- [ ] **Step 6: Verify `app/api/health.py` is correct**

The file should contain:

```python
from datetime import datetime, timezone
from fastapi import APIRouter
from app.core.config import settings

router = APIRouter()

@router.get("/health")
async def health_check():
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": settings.version,
    }
```

Run: `cat app/api/health.py` — if it matches, no changes needed.

- [ ] **Step 7: Write health test**

Create `tests/test_api_health.py`:

```python
from fastapi.testclient import TestClient


def test_health_returns_ok():
    from app.main import app
    client = TestClient(app)
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data
```

- [ ] **Step 8: Run health test**

```bash
pytest tests/test_api_health.py -v
```

Expected: `PASSED` (this test will fail until main.py is updated in Task 13 — note it and continue)

- [ ] **Step 9: Commit**

```bash
git add app/services/embedder.py tests/test_embedder.py tests/test_api_health.py
git commit -m "feat: add embedder service and health test"
```

---

## Task 1: Cleanup & Dependencies

**Files:**
- Delete: `app/services/retrieval.py`, `app/services/reranker.py`, `app/services/semantic_cache.py`, `app/services/storage.py`
- Delete: `app/api/documents.py`, `app/api/conversations.py`
- Delete: `app/workers/` (entire directory)
- Delete: `app/core/security.py`, `app/core/limiter.py`, `app/core/metrics.py`
- Delete: `app/models/chunk.py`, `app/models/document.py`, `app/models/message.py`
- Delete: `tests/test_chat.py`, `tests/test_conversations_incomplete.py`, `tests/test_ingestion.py`, `tests/test_sse_framing.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Delete old service files**

```bash
rm app/services/retrieval.py app/services/reranker.py \
   app/services/semantic_cache.py app/services/storage.py
```

- [ ] **Step 2: Delete old API files**

```bash
rm app/api/documents.py app/api/conversations.py
```

- [ ] **Step 3: Delete old workers, core helpers, models**

```bash
rm -rf app/workers/
rm app/core/security.py app/core/limiter.py app/core/metrics.py
rm app/models/chunk.py app/models/document.py app/models/message.py
```

- [ ] **Step 4: Delete old tests**

```bash
rm tests/test_chat.py tests/test_conversations_incomplete.py \
   tests/test_ingestion.py tests/test_sse_framing.py
```

- [ ] **Step 5: Replace requirements.txt**

Write the following to `requirements.txt`:

```
fastapi==0.104.1
uvicorn[standard]==0.24.0
pydantic==2.5.0
pydantic-settings==2.1.0
python-multipart==0.0.6
sqlalchemy[asyncio]==2.0.46
aiosqlite==0.19.0
groq>=0.9.0
fastembed>=0.3.0
numpy>=1.26.0
nltk>=3.8.0
langchain-text-splitters>=0.2.0
pymupdf>=1.24.0
pytesseract>=0.3.10
Pillow>=10.0.0
python-docx==1.1.0
chromadb>=0.5.0
youtube-transcript-api>=0.6.0
pytube>=15.0.0
trafilatura>=1.9.0
httpx>=0.27.0
langsmith>=0.1.0
langgraph>=0.2.0
langchain-core>=0.3.0
tokenizers>=0.19.0
pytest>=8.0.0
pytest-asyncio>=0.23.0
```

- [ ] **Step 6: Install dependencies**

```bash
source venv/bin/activate && pip install -r requirements.txt
```

Expected: all packages install without errors.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt
git add -u  # stage all deletions
git commit -m "chore: remove old services, models, and workers for agent migration"
```

---

## Task 2: Config, Database & Models

**Files:**
- Modify: `app/core/config.py`
- Modify: `app/core/database.py`
- Modify: `app/models/conversation.py` (add Message model, remove document_id)

- [ ] **Step 1: Update `app/core/config.py`**

Replace the entire file:

```python
from pathlib import Path
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_PROJECT_ROOT / ".env"))

    app_name: str = "DocChat Agent"
    version: str = "2.0.0"
    debug: bool = False

    api_prefix: str = "/api/v1"
    database_url: str = f"sqlite+aiosqlite:///{_PROJECT_ROOT / 'docchat.db'}"

    # LLM
    groq_api_key: str
    chat_model: str = "llama-3.3-70b-versatile"
    chat_history_limit: int = 10

    # Embeddings
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384

    # ChromaDB
    chroma_host: str = "localhost"
    chroma_port: int = 8001

    # LangSmith observability
    langsmith_api_key: str = ""
    langsmith_project: str = "docchat-agent"

    # YouTube (optional — pytube works without it)
    youtube_api_key: str = ""

    # DB connection pool (PostgreSQL only)
    db_pool_size: int = 10
    db_max_overflow: int = 20


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
```

- [ ] **Step 2: Update `app/models/conversation.py`**

Replace the entire file with both `Conversation` and `Message` models:

```python
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class MessageRole(str, enum.Enum):
    user = "user"
    assistant = "assistant"


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    messages: Mapped[list["Message"]] = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    conversation_id: Mapped[str] = mapped_column(
        String, ForeignKey("conversations.id"), nullable=False
    )
    role: Mapped[MessageRole] = mapped_column(Enum(MessageRole), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    conversation: Mapped["Conversation"] = relationship(
        "Conversation", back_populates="messages"
    )
```

- [ ] **Step 3: Update `app/core/database.py`**

Replace the entire file:

```python
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

if settings.database_url.startswith("sqlite"):
    engine = create_async_engine(settings.database_url, echo=settings.debug)

    @event.listens_for(engine.sync_engine, "connect")
    def _set_wal_mode(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()
else:
    engine = create_async_engine(
        settings.database_url,
        echo=settings.debug,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
    )

AsyncSessionLocal = sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


async def create_all_tables() -> None:
    import app.models.conversation  # noqa: F401 — registers Conversation + Message with Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
```

- [ ] **Step 4: Write test**

Create `tests/test_models.py`:

```python
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from app.core.database import Base
from app.models.conversation import Conversation, Message, MessageRole


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    import app.models.conversation  # noqa
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_conversation_and_message(db):
    conv = Conversation(title="test chat")
    db.add(conv)
    await db.flush()

    msg = Message(conversation_id=conv.id, role=MessageRole.user, content="hello")
    db.add(msg)
    await db.commit()

    await db.refresh(conv)
    assert len(conv.messages) == 1
    assert conv.messages[0].content == "hello"
    assert conv.messages[0].role == MessageRole.user
```

- [ ] **Step 5: Run test**

```bash
pytest tests/test_models.py -v
```

Expected: `PASSED`

- [ ] **Step 6: Commit**

```bash
git add app/core/config.py app/core/database.py app/models/conversation.py tests/test_models.py
git commit -m "feat: update config, database, and models for agent architecture"
```

---

## Task 3: ChromaDB Client

**Files:**
- Create: `app/core/chroma.py`
- Create: `tests/test_chroma.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_chroma.py`:

```python
from unittest.mock import MagicMock, patch
from app.core.chroma import get_chroma_client, get_collection


def test_get_chroma_client_returns_singleton():
    with patch("app.core.chroma.chromadb.HttpClient") as mock_client_cls:
        mock_client_cls.return_value = MagicMock()
        # Clear the lru_cache so patch takes effect
        get_chroma_client.cache_clear()
        c1 = get_chroma_client()
        c2 = get_chroma_client()
        assert c1 is c2
        assert mock_client_cls.call_count == 1
        get_chroma_client.cache_clear()


def test_get_collection_uses_cosine_space():
    mock_collection = MagicMock()
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection

    with patch("app.core.chroma.get_chroma_client", return_value=mock_client):
        result = get_collection("pdf_chunks")

    mock_client.get_or_create_collection.assert_called_once_with(
        name="pdf_chunks",
        metadata={"hnsw:space": "cosine"},
    )
    assert result is mock_collection
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_chroma.py -v
```

Expected: `ModuleNotFoundError` or `ImportError` — `app.core.chroma` doesn't exist yet.

- [ ] **Step 3: Create `app/core/chroma.py`**

```python
from functools import lru_cache
import chromadb
from app.core.config import settings


@lru_cache()
def get_chroma_client() -> chromadb.HttpClient:
    return chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)


def get_collection(name: str):
    return get_chroma_client().get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_chroma.py -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add app/core/chroma.py tests/test_chroma.py
git commit -m "feat: add ChromaDB client singleton"
```

---

## Task 4: LLM Service

**Files:**
- Create: `app/services/llm.py`
- Delete: `app/services/chat.py`
- Create: `tests/test_llm.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_llm.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.llm import chat_complete, chat_stream


@pytest.mark.asyncio
async def test_chat_complete_returns_content():
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "hello world"

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    with patch("app.services.llm._get_client", return_value=mock_client):
        result = await chat_complete([{"role": "user", "content": "hi"}])

    assert result == "hello world"


@pytest.mark.asyncio
async def test_chat_stream_yields_tokens():
    chunk1 = MagicMock()
    chunk1.choices[0].delta.content = "hello"
    chunk2 = MagicMock()
    chunk2.choices[0].delta.content = " world"
    chunk3 = MagicMock()
    chunk3.choices[0].delta.content = None

    async def fake_stream(*args, **kwargs):
        for c in [chunk1, chunk2, chunk3]:
            yield c

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=fake_stream())

    with patch("app.services.llm._get_client", return_value=mock_client):
        tokens = []
        async for token in chat_stream([{"role": "user", "content": "hi"}]):
            tokens.append(token)

    assert tokens == ["hello", " world"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_llm.py -v
```

Expected: `ImportError` — `app.services.llm` doesn't exist yet.

- [ ] **Step 3: Create `app/services/llm.py`**

```python
from typing import AsyncGenerator
from groq import AsyncGroq
from app.core.config import settings

_client: AsyncGroq | None = None


def _get_client() -> AsyncGroq:
    global _client
    if _client is None:
        _client = AsyncGroq(api_key=settings.groq_api_key)
    return _client


async def chat_complete(messages: list[dict], max_tokens: int = 1024) -> str:
    resp = await _get_client().chat.completions.create(
        model=settings.chat_model,
        messages=messages,
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content or ""


async def chat_stream(
    messages: list[dict], max_tokens: int = 1024
) -> AsyncGenerator[str, None]:
    stream = await _get_client().chat.completions.create(
        model=settings.chat_model,
        messages=messages,
        max_tokens=max_tokens,
        stream=True,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta
```

- [ ] **Step 4: Delete old chat.py**

```bash
rm app/services/chat.py
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/test_llm.py -v
```

Expected: `PASSED`

- [ ] **Step 6: Commit**

```bash
git add app/services/llm.py tests/test_llm.py
git add -u
git commit -m "feat: add LLM service (extracted from chat.py)"
```

---

## Task 5: PDF Ingestion Service

**Files:**
- Create: `app/services/ingestion/__init__.py`
- Create: `app/services/ingestion/pdf.py`
- Delete: `app/services/ingestion.py`
- Create: `tests/test_ingestion_pdf.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_ingestion_pdf.py`:

```python
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path


@pytest.mark.asyncio
async def test_ingest_pdf_stores_chunks_in_chromadb():
    mock_collection = MagicMock()
    mock_embedder = MagicMock()
    mock_embedder.embed_late.return_value = [
        __import__("numpy").array([0.1] * 384, dtype="float32")
    ]
    mock_embedder.embed_independently.return_value = [
        __import__("numpy").array([0.1] * 384, dtype="float32")
    ]

    fake_segments = [MagicMock(text="Sample text", page_number=1, section_heading="Intro")]
    fake_chunks = [{"text": "Sample text", "page_number": 1, "section_heading": "Intro",
                    "seg_idx": 0, "char_start": 0}]

    with (
        patch("app.services.ingestion.pdf.get_collection", return_value=mock_collection),
        patch("app.services.ingestion.pdf.get_embedder", return_value=mock_embedder),
        patch("app.services.ingestion.pdf._extract_segments", return_value=fake_segments),
        patch("app.services.ingestion.pdf._chunk_segments", return_value=fake_chunks),
        patch("app.services.ingestion.pdf._embed_chunks_late",
              return_value=[__import__("numpy").array([0.1] * 384, dtype="float32")]),
    ):
        from app.services.ingestion.pdf import ingest_pdf
        source_id = await ingest_pdf("/fake/path.pdf", "test.pdf", "application/pdf")

    assert isinstance(source_id, str) and len(source_id) == 36
    mock_collection.add.assert_called_once()
    call_kwargs = mock_collection.add.call_args[1]
    assert len(call_kwargs["ids"]) == 1
    assert call_kwargs["documents"] == ["Sample text"]
    assert call_kwargs["metadatas"][0]["filename"] == "test.pdf"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_ingestion_pdf.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Create `app/services/ingestion/__init__.py`**

```python
```
(empty file)

- [ ] **Step 4: Create `app/services/ingestion/pdf.py`**

```python
import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.core.chroma import get_collection
from app.services.embedder import get_embedder

COLLECTION = "pdf_chunks"
CHUNK_SIZE = 1500
CHUNK_OVERLAP = 200


# ---------------------------------------------------------------------------
# Segment dataclass — carries text plus provenance metadata
# ---------------------------------------------------------------------------

from dataclasses import dataclass


@dataclass
class _Segment:
    text: str
    page_number: int | None = None
    section_heading: str | None = None


# ---------------------------------------------------------------------------
# PDF extraction (pymupdf primary, pypdf fallback, pytesseract OCR for scans)
# ---------------------------------------------------------------------------

def _detect_pdf_heading(page) -> str | None:
    try:
        max_size, heading = 0.0, None
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    size = span.get("size", 0.0)
                    txt = span.get("text", "").strip()
                    if size > max_size and 3 < len(txt) < 200:
                        max_size, heading = size, txt
        return heading if max_size > 13 else None
    except Exception:
        return None


def _extract_pdf_segments(path: Path) -> list[_Segment]:
    try:
        import fitz
        doc = fitz.open(str(path))
        segments: list[_Segment] = []
        for page_num, page in enumerate(doc, start=1):
            text = page.get_text()
            heading = _detect_pdf_heading(page)
            if not text.strip():
                try:
                    import pytesseract
                    from PIL import Image
                    pix = page.get_pixmap(dpi=200)
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    text = pytesseract.image_to_string(img)
                except Exception:
                    pass
            if text.strip():
                segments.append(_Segment(text=text, page_number=page_num, section_heading=heading))
        doc.close()
        return segments
    except ImportError:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        return [
            _Segment(text=page.extract_text() or "", page_number=i + 1)
            for i, page in enumerate(reader.pages)
            if (page.extract_text() or "").strip()
        ]


def _extract_docx_segments(path: Path) -> list[_Segment]:
    from docx import Document as DocxDocument
    doc = DocxDocument(str(path))
    segments: list[_Segment] = []
    current_heading: str | None = None
    current_paragraphs: list[str] = []
    for para in doc.paragraphs:
        if para.style.name.startswith("Heading"):
            if current_paragraphs:
                segments.append(_Segment(
                    text="\n".join(current_paragraphs),
                    section_heading=current_heading,
                ))
                current_paragraphs = []
            current_heading = para.text or current_heading
        elif para.text.strip():
            current_paragraphs.append(para.text)
    if current_paragraphs:
        segments.append(_Segment(text="\n".join(current_paragraphs), section_heading=current_heading))
    return segments


def _extract_segments(file_path: "str | Path", content_type: str) -> list[_Segment]:
    path = Path(file_path)
    if content_type == "text/plain":
        return [_Segment(text=path.read_text(encoding="utf-8", errors="replace"))]
    if content_type == "application/pdf":
        return _extract_pdf_segments(path)
    if content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return _extract_docx_segments(path)
    raise ValueError(f"Unsupported content type: {content_type}")


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def _get_splitter():
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    return RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", "! ", "? ", "; ", " ", ""],
        length_function=len,
        add_start_index=True,
    )


def _chunk_segments(segments: list[_Segment]) -> list[dict]:
    splitter = _get_splitter()
    chunks: list[dict] = []
    for seg_idx, seg in enumerate(segments):
        for doc in splitter.create_documents([seg.text]):
            if doc.page_content.strip():
                chunks.append({
                    "text": doc.page_content,
                    "page_number": seg.page_number,
                    "section_heading": seg.section_heading,
                    "seg_idx": seg_idx,
                    "char_start": doc.metadata.get("start_index", 0),
                })
    return chunks


def _embed_chunks_late(raw_chunks, segments, embedder) -> list:
    results = [None] * len(raw_chunks)
    i = 0
    while i < len(raw_chunks):
        seg_idx = raw_chunks[i].get("seg_idx")
        j = i
        while j < len(raw_chunks) and raw_chunks[j].get("seg_idx") == seg_idx:
            j += 1
        group = raw_chunks[i:j]
        chunk_texts = [c["text"] for c in group]
        char_starts = [c.get("char_start", 0) for c in group]
        if seg_idx is not None and seg_idx < len(segments):
            embs = embedder.embed_late(segments[seg_idx].text, chunk_texts, char_starts)
        else:
            embs = embedder.embed_independently(chunk_texts)
        for k, emb in enumerate(embs):
            results[i + k] = emb
        i = j
    return results


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

SUPPORTED_TYPES = {
    "application/pdf",
    "text/plain",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


async def ingest_pdf(file_path: "str | Path", filename: str, content_type: str) -> str:
    """Extract, chunk, embed a document file and store in ChromaDB. Returns source_id."""
    source_id = str(uuid.uuid4())
    loop = asyncio.get_running_loop()

    segments = await loop.run_in_executor(None, _extract_segments, file_path, content_type)
    raw_chunks = await loop.run_in_executor(None, _chunk_segments, segments)

    embedder = get_embedder()
    if embedder:
        embeddings = await loop.run_in_executor(
            None, _embed_chunks_late, raw_chunks, segments, embedder
        )
    else:
        embeddings = [None] * len(raw_chunks)

    collection = get_collection(COLLECTION)
    ids, docs, metas, embs = [], [], [], []
    now = datetime.now(timezone.utc).isoformat()

    for i, (chunk, emb) in enumerate(zip(raw_chunks, embeddings)):
        if emb is None:
            continue
        ids.append(f"{source_id}_{i}")
        docs.append(chunk["text"])
        metas.append({
            "source_id": source_id,
            "filename": filename,
            "page_number": chunk.get("page_number") or 0,
            "section_heading": chunk.get("section_heading") or "",
            "chunk_index": i,
            "ingested_at": now,
        })
        embs.append(emb.tolist())

    if ids:
        collection.add(ids=ids, embeddings=embs, documents=docs, metadatas=metas)

    return source_id
```

- [ ] **Step 5: Delete old ingestion.py**

```bash
rm app/services/ingestion.py
```

- [ ] **Step 6: Run test to verify it passes**

```bash
pytest tests/test_ingestion_pdf.py -v
```

Expected: `PASSED`

- [ ] **Step 7: Commit**

```bash
git add app/services/ingestion/ tests/test_ingestion_pdf.py
git add -u
git commit -m "feat: add PDF ingestion service writing to ChromaDB"
```

---

## Task 6: YouTube Ingestion Service

**Files:**
- Create: `app/services/ingestion/youtube.py`
- Create: `tests/test_ingestion_youtube.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_ingestion_youtube.py`:

```python
import pytest
from unittest.mock import MagicMock, patch
import numpy as np
from app.services.ingestion.youtube import _extract_video_id, _chunk_transcript


def test_extract_video_id_from_watch_url():
    assert _extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_extract_video_id_from_short_url():
    assert _extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_chunk_transcript_groups_by_duration():
    transcript = [
        {"text": "Hello", "start": 0.0, "duration": 5.0},
        {"text": "world", "start": 5.0, "duration": 5.0},
        {"text": "end", "start": 65.0, "duration": 5.0},  # new chunk after 60s
    ]
    chunks = _chunk_transcript(transcript)
    assert len(chunks) == 2
    assert "Hello" in chunks[0]["text"]
    assert "end" in chunks[1]["text"]


@pytest.mark.asyncio
async def test_ingest_youtube_stores_chunks():
    mock_collection = MagicMock()
    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = np.array([0.1] * 384, dtype="float32")

    fake_transcript = [{"text": "attention is all you need", "start": 0.0, "duration": 30.0}]
    fake_meta = {"title": "Lecture 1", "channel": "MIT OCW", "video_id": "abc123"}

    with (
        patch("app.services.ingestion.youtube.get_collection", return_value=mock_collection),
        patch("app.services.ingestion.youtube.get_embedder", return_value=mock_embedder),
        patch("app.services.ingestion.youtube._fetch_transcript", return_value=fake_transcript),
        patch("app.services.ingestion.youtube._get_video_metadata", return_value=fake_meta),
        patch("app.services.ingestion.youtube._extract_video_id", return_value="abc123"),
    ):
        from app.services.ingestion.youtube import ingest_youtube
        source_id = await ingest_youtube("https://youtube.com/watch?v=abc123")

    assert isinstance(source_id, str) and len(source_id) == 36
    mock_collection.add.assert_called_once()
    meta = mock_collection.add.call_args[1]["metadatas"][0]
    assert meta["title"] == "Lecture 1"
    assert meta["channel"] == "MIT OCW"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_ingestion_youtube.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Create `app/services/ingestion/youtube.py`**

```python
import uuid
import asyncio
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs

from app.core.chroma import get_collection
from app.services.embedder import get_embedder

COLLECTION = "youtube_chunks"
CHUNK_DURATION_SECONDS = 60


def _extract_video_id(url: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname in ("youtu.be",):
        return parsed.path.lstrip("/")
    qs = parse_qs(parsed.query)
    return qs["v"][0]


def _fetch_transcript(video_id: str) -> list[dict]:
    from youtube_transcript_api import YouTubeTranscriptApi
    return YouTubeTranscriptApi.get_transcript(video_id)


def _get_video_metadata(url: str) -> dict:
    from pytube import YouTube
    yt = YouTube(url)
    return {"title": yt.title, "channel": yt.author, "video_id": yt.video_id}


def _chunk_transcript(transcript: list[dict]) -> list[dict]:
    if not transcript:
        return []
    chunks: list[dict] = []
    current_texts: list[str] = []
    current_start = transcript[0]["start"]
    current_end = current_start

    for seg in transcript:
        current_texts.append(seg["text"])
        current_end = seg["start"] + seg.get("duration", 0)
        if current_end - current_start >= CHUNK_DURATION_SECONDS:
            chunks.append({
                "text": " ".join(current_texts),
                "timestamp_start": round(current_start),
                "timestamp_end": round(current_end),
            })
            current_texts = []
            current_start = current_end

    if current_texts:
        chunks.append({
            "text": " ".join(current_texts),
            "timestamp_start": round(current_start),
            "timestamp_end": round(current_end),
        })
    return chunks


async def ingest_youtube(url: str) -> str:
    """Fetch YouTube transcript, chunk, embed, and store in ChromaDB. Returns source_id."""
    source_id = str(uuid.uuid4())
    loop = asyncio.get_running_loop()
    video_id = _extract_video_id(url)

    meta, transcript = await asyncio.gather(
        loop.run_in_executor(None, _get_video_metadata, url),
        loop.run_in_executor(None, _fetch_transcript, video_id),
    )

    chunks = _chunk_transcript(transcript)
    embedder = get_embedder()
    collection = get_collection(COLLECTION)
    ids, docs, metas, embs = [], [], [], []
    now = datetime.now(timezone.utc).isoformat()

    for i, chunk in enumerate(chunks):
        if not embedder:
            continue
        emb = embedder.embed_query(chunk["text"])
        ids.append(f"{source_id}_{i}")
        docs.append(chunk["text"])
        metas.append({
            "source_id": source_id,
            "video_id": meta["video_id"],
            "video_url": url,
            "title": meta["title"],
            "channel": meta["channel"],
            "timestamp_start": chunk["timestamp_start"],
            "timestamp_end": chunk["timestamp_end"],
            "chunk_index": i,
            "ingested_at": now,
        })
        embs.append(emb.tolist())

    if ids:
        collection.add(ids=ids, embeddings=embs, documents=docs, metadatas=metas)

    return source_id
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_ingestion_youtube.py -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add app/services/ingestion/youtube.py tests/test_ingestion_youtube.py
git commit -m "feat: add YouTube ingestion service"
```

---

## Task 7: Web Ingestion Service

**Files:**
- Create: `app/services/ingestion/web.py`
- Create: `tests/test_ingestion_web.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_ingestion_web.py`:

```python
import pytest
from unittest.mock import MagicMock, patch
import numpy as np
from app.services.ingestion.web import _scrape


def test_scrape_extracts_content():
    fake_html = "<html><head><title>Test Page</title></head><body><p>Hello world content here.</p></body></html>"

    with (
        patch("app.services.ingestion.web.httpx.get") as mock_get,
        patch("app.services.ingestion.web.trafilatura.extract", return_value="Hello world content here."),
    ):
        mock_resp = MagicMock()
        mock_resp.text = fake_html
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = _scrape("https://example.com")

    assert result["content"] == "Hello world content here."
    assert result["title"] == "Test Page"


@pytest.mark.asyncio
async def test_ingest_web_stores_chunks():
    mock_collection = MagicMock()
    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = np.array([0.1] * 384, dtype="float32")

    fake_scraped = {"content": "Article content about AI.", "title": "AI News"}

    with (
        patch("app.services.ingestion.web.get_collection", return_value=mock_collection),
        patch("app.services.ingestion.web.get_embedder", return_value=mock_embedder),
        patch("app.services.ingestion.web._scrape", return_value=fake_scraped),
    ):
        from app.services.ingestion.web import ingest_web
        source_id = await ingest_web("https://example.com/article")

    assert isinstance(source_id, str) and len(source_id) == 36
    mock_collection.add.assert_called_once()
    meta = mock_collection.add.call_args[1]["metadatas"][0]
    assert meta["url"] == "https://example.com/article"
    assert meta["title"] == "AI News"
    assert meta["domain"] == "example.com"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_ingestion_web.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Create `app/services/ingestion/web.py`**

```python
import re
import uuid
import asyncio
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
import trafilatura
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.chroma import get_collection
from app.services.embedder import get_embedder

COLLECTION = "web_chunks"

_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1500,
    chunk_overlap=200,
    separators=["\n\n", "\n", ". ", " ", ""],
)


def _scrape(url: str) -> dict:
    response = httpx.get(url, timeout=30, follow_redirects=True)
    response.raise_for_status()
    content = trafilatura.extract(response.text, include_comments=False, include_tables=False)
    if not content:
        raise ValueError(f"Could not extract readable content from {url}")
    title_match = re.search(r"<title>(.*?)</title>", response.text, re.IGNORECASE | re.DOTALL)
    title = title_match.group(1).strip() if title_match else url
    return {"content": content, "title": title}


async def ingest_web(url: str) -> str:
    """Scrape URL, chunk, embed, and store in ChromaDB. Returns source_id."""
    source_id = str(uuid.uuid4())
    loop = asyncio.get_running_loop()
    domain = urlparse(url).netloc

    scraped = await loop.run_in_executor(None, _scrape, url)
    chunk_texts = _splitter.split_text(scraped["content"])

    embedder = get_embedder()
    collection = get_collection(COLLECTION)
    ids, docs, metas, embs = [], [], [], []
    now = datetime.now(timezone.utc).isoformat()

    for i, text in enumerate(chunk_texts):
        if not text.strip() or not embedder:
            continue
        emb = embedder.embed_query(text)
        ids.append(f"{source_id}_{i}")
        docs.append(text)
        metas.append({
            "source_id": source_id,
            "url": url,
            "title": scraped["title"],
            "domain": domain,
            "chunk_index": i,
            "scraped_at": now,
        })
        embs.append(emb.tolist())

    if ids:
        collection.add(ids=ids, embeddings=embs, documents=docs, metadatas=metas)

    return source_id
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_ingestion_web.py -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add app/services/ingestion/web.py tests/test_ingestion_web.py
git commit -m "feat: add web scraping ingestion service"
```

---

## Task 8: Agent State & Planner Node

**Files:**
- Create: `app/agent/__init__.py`
- Create: `app/agent/state.py`
- Create: `app/agent/nodes/__init__.py`
- Create: `app/agent/nodes/planner.py`
- Create: `tests/test_agent_planner.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_agent_planner.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch
from app.agent.state import AgentState
from app.agent.nodes.planner import planner_node


@pytest.mark.asyncio
async def test_planner_selects_sources_from_llm_response():
    with patch("app.agent.nodes.planner.chat_complete",
               new=AsyncMock(return_value='{"sources_to_use": ["pdf", "web"], "rewritten_query": "attention mechanisms"}')):
        state: AgentState = {
            "query": "What are attention mechanisms?",
            "conversation_id": "conv-1",
            "sources_to_use": [],
            "retrieved_chunks": [],
            "answer": "",
            "critic_feedback": "",
            "needs_replan": False,
            "iteration": 0,
        }
        result = await planner_node(state)

    assert result["sources_to_use"] == ["pdf", "web"]
    assert result["query"] == "attention mechanisms"


@pytest.mark.asyncio
async def test_planner_falls_back_on_invalid_json():
    with patch("app.agent.nodes.planner.chat_complete",
               new=AsyncMock(return_value="not valid json")):
        state: AgentState = {
            "query": "test query",
            "conversation_id": "conv-1",
            "sources_to_use": [],
            "retrieved_chunks": [],
            "answer": "",
            "critic_feedback": "",
            "needs_replan": False,
            "iteration": 0,
        }
        result = await planner_node(state)

    assert set(result["sources_to_use"]) == {"pdf", "youtube", "web"}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_agent_planner.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Create agent package files**

```bash
touch app/agent/__init__.py app/agent/nodes/__init__.py
```

- [ ] **Step 4: Create `app/agent/state.py`**

```python
from typing import TypedDict


class AgentState(TypedDict):
    query: str
    conversation_id: str
    sources_to_use: list[str]
    retrieved_chunks: list[dict]
    answer: str
    critic_feedback: str
    needs_replan: bool
    iteration: int
```

- [ ] **Step 5: Create `app/agent/nodes/planner.py`**

```python
import json
from app.agent.state import AgentState
from app.services.llm import chat_complete

_PROMPT = """\
You are a research planner. Decide which source types to search for the user's query.

Available sources:
- pdf: uploaded document files
- youtube: video transcripts
- web: scraped web pages

Respond ONLY with valid JSON matching this schema exactly:
{{"sources_to_use": ["pdf", "youtube", "web"], "rewritten_query": "..."}}

Rules:
- Include any source that could plausibly help answer the query
- If critic_feedback is provided, rewrite the query to address what was missing
- Otherwise rewritten_query should equal the original query
- sources_to_use must contain at least one value

Query: {query}
Critic feedback: {critic_feedback}
"""


async def planner_node(state: AgentState) -> dict:
    prompt = _PROMPT.format(
        query=state["query"],
        critic_feedback=state.get("critic_feedback") or "none",
    )
    response = await chat_complete([{"role": "user", "content": prompt}], max_tokens=200)

    try:
        data = json.loads(response)
        sources = [s for s in data.get("sources_to_use", []) if s in ("pdf", "youtube", "web")]
        rewritten = data.get("rewritten_query", state["query"])
    except (json.JSONDecodeError, KeyError, TypeError):
        sources = ["pdf", "youtube", "web"]
        rewritten = state["query"]

    if not sources:
        sources = ["pdf", "youtube", "web"]

    return {"sources_to_use": sources, "query": rewritten}
```

- [ ] **Step 6: Run test to verify it passes**

```bash
pytest tests/test_agent_planner.py -v
```

Expected: `PASSED`

- [ ] **Step 7: Commit**

```bash
git add app/agent/ tests/test_agent_planner.py
git commit -m "feat: add agent state and planner node"
```

---

## Task 9: Retriever Node

**Files:**
- Create: `app/agent/nodes/retriever.py`
- Create: `tests/test_agent_retriever.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_agent_retriever.py`:

```python
import pytest
import numpy as np
from unittest.mock import MagicMock, patch
from app.agent.state import AgentState
from app.agent.nodes.retriever import retriever_node


@pytest.mark.asyncio
async def test_retriever_queries_selected_sources():
    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "documents": [["chunk text"]],
        "metadatas": [[{"filename": "doc.pdf"}]],
        "distances": [[0.1]],
    }
    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = np.array([0.1] * 384, dtype="float32")

    state: AgentState = {
        "query": "attention mechanisms",
        "conversation_id": "conv-1",
        "sources_to_use": ["pdf"],
        "retrieved_chunks": [],
        "answer": "",
        "critic_feedback": "",
        "needs_replan": False,
        "iteration": 0,
    }

    with (
        patch("app.agent.nodes.retriever.get_collection", return_value=mock_collection),
        patch("app.agent.nodes.retriever.get_embedder", return_value=mock_embedder),
    ):
        result = await retriever_node(state)

    assert len(result["retrieved_chunks"]) == 1
    assert result["retrieved_chunks"][0]["text"] == "chunk text"
    assert result["retrieved_chunks"][0]["source_type"] == "pdf"
    mock_collection.query.assert_called_once()


@pytest.mark.asyncio
async def test_retriever_deduplicates_chunks():
    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "documents": [["duplicate text", "duplicate text"]],
        "metadatas": [[{"filename": "a.pdf"}, {"filename": "b.pdf"}]],
        "distances": [[0.1, 0.2]],
    }
    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = np.array([0.1] * 384, dtype="float32")

    state: AgentState = {
        "query": "test",
        "conversation_id": "conv-1",
        "sources_to_use": ["pdf"],
        "retrieved_chunks": [],
        "answer": "",
        "critic_feedback": "",
        "needs_replan": False,
        "iteration": 0,
    }

    with (
        patch("app.agent.nodes.retriever.get_collection", return_value=mock_collection),
        patch("app.agent.nodes.retriever.get_embedder", return_value=mock_embedder),
    ):
        result = await retriever_node(state)

    assert len(result["retrieved_chunks"]) == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_agent_retriever.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Create `app/agent/nodes/retriever.py`**

```python
from app.agent.state import AgentState
from app.core.chroma import get_collection
from app.services.embedder import get_embedder

_SOURCE_COLLECTIONS = {
    "pdf": "pdf_chunks",
    "youtube": "youtube_chunks",
    "web": "web_chunks",
}
N_RESULTS = 5


async def retriever_node(state: AgentState) -> dict:
    embedder = get_embedder()
    if not embedder:
        return {"retrieved_chunks": []}

    query_emb = embedder.embed_query(state["query"]).tolist()
    all_chunks: list[dict] = []

    for source in state["sources_to_use"]:
        collection_name = _SOURCE_COLLECTIONS.get(source)
        if not collection_name:
            continue
        try:
            collection = get_collection(collection_name)
            results = collection.query(
                query_embeddings=[query_emb],
                n_results=N_RESULTS,
                include=["documents", "metadatas", "distances"],
            )
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            ):
                all_chunks.append({
                    "text": doc,
                    "metadata": meta,
                    "source_type": source,
                    "distance": dist,
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

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_agent_retriever.py -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add app/agent/nodes/retriever.py tests/test_agent_retriever.py
git commit -m "feat: add retriever node"
```

---

## Task 10: Synthesizer & Critic Nodes

**Files:**
- Create: `app/agent/nodes/synthesizer.py`
- Create: `app/agent/nodes/critic.py`
- Create: `tests/test_agent_synthesizer_critic.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_agent_synthesizer_critic.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch
from app.agent.state import AgentState


def _make_state(**kwargs) -> AgentState:
    base: AgentState = {
        "query": "What is attention?",
        "conversation_id": "conv-1",
        "sources_to_use": ["pdf"],
        "retrieved_chunks": [
            {"text": "Attention allows models to focus on relevant parts.",
             "metadata": {"filename": "paper.pdf", "page_number": 3},
             "source_type": "pdf", "distance": 0.1}
        ],
        "answer": "",
        "critic_feedback": "",
        "needs_replan": False,
        "iteration": 0,
    }
    base.update(kwargs)
    return base


@pytest.mark.asyncio
async def test_synthesizer_produces_answer():
    from app.agent.nodes.synthesizer import synthesizer_node
    with patch("app.agent.nodes.synthesizer.chat_complete",
               new=AsyncMock(return_value="Attention focuses on relevant parts.")):
        result = await synthesizer_node(_make_state())
    assert result["answer"] == "Attention focuses on relevant parts."


@pytest.mark.asyncio
async def test_critic_approves_good_answer():
    from app.agent.nodes.critic import critic_node
    with patch("app.agent.nodes.critic.chat_complete",
               new=AsyncMock(return_value='{"quality": "good", "feedback": ""}')):
        result = await critic_node(_make_state(answer="Attention focuses on relevant parts."))
    assert result["needs_replan"] is False
    assert result["iteration"] == 1


@pytest.mark.asyncio
async def test_critic_requests_replan_on_poor_answer():
    from app.agent.nodes.critic import critic_node
    with patch("app.agent.nodes.critic.chat_complete",
               new=AsyncMock(return_value='{"quality": "poor", "feedback": "Missing mathematical definition."}')):
        result = await critic_node(_make_state(answer="I don't know.", iteration=0))
    assert result["needs_replan"] is True
    assert "Missing" in result["critic_feedback"]


@pytest.mark.asyncio
async def test_critic_stops_at_max_iterations():
    from app.agent.nodes.critic import critic_node
    with patch("app.agent.nodes.critic.chat_complete",
               new=AsyncMock(return_value='{"quality": "poor", "feedback": "still bad"}')):
        result = await critic_node(_make_state(answer="bad answer", iteration=1))
    assert result["needs_replan"] is False
    assert result["iteration"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_agent_synthesizer_critic.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Create `app/agent/nodes/synthesizer.py`**

```python
from app.agent.state import AgentState
from app.services.llm import chat_complete

_SYSTEM = """\
You are a research assistant. Answer the user's question using ONLY the provided context.
Cite sources inline (e.g., "[PDF — paper.pdf p.3]", "[YouTube — Lecture 1 @120s]", "[Web — example.com]").
If the context doesn't contain enough information, say so clearly — do not fabricate.

Context:
{context}
"""


def _format_chunks(chunks: list[dict]) -> str:
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
    return "\n\n---\n\n".join(parts) if parts else "No context retrieved."


async def synthesizer_node(state: AgentState) -> dict:
    context = _format_chunks(state["retrieved_chunks"])
    messages = [
        {"role": "system", "content": _SYSTEM.format(context=context)},
        {"role": "user", "content": state["query"]},
    ]
    answer = await chat_complete(messages, max_tokens=1024)
    return {"answer": answer}
```

- [ ] **Step 4: Create `app/agent/nodes/critic.py`**

```python
import json
from app.agent.state import AgentState
from app.services.llm import chat_complete

_PROMPT = """\
You are a quality critic. Evaluate whether the answer adequately addresses the query.

Query: {query}
Answer: {answer}

Respond ONLY with valid JSON:
{{"quality": "good" | "poor", "feedback": "..."}}

- "good": answer is grounded in context and addresses the full query
- "poor": answer is missing key information, vague, or doesn't address the query
- feedback: if "poor", one sentence explaining what's missing
"""


async def critic_node(state: AgentState) -> dict:
    iteration = state.get("iteration", 0) + 1

    if iteration >= 2:
        return {"needs_replan": False, "iteration": iteration, "critic_feedback": ""}

    prompt = _PROMPT.format(query=state["query"], answer=state["answer"])
    response = await chat_complete([{"role": "user", "content": prompt}], max_tokens=150)

    try:
        data = json.loads(response)
        quality = data.get("quality", "good")
        feedback = data.get("feedback", "")
    except (json.JSONDecodeError, KeyError, TypeError):
        quality = "good"
        feedback = ""

    needs_replan = quality == "poor"
    return {
        "needs_replan": needs_replan,
        "critic_feedback": feedback if needs_replan else "",
        "iteration": iteration,
    }
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/test_agent_synthesizer_critic.py -v
```

Expected: `PASSED`

- [ ] **Step 6: Commit**

```bash
git add app/agent/nodes/synthesizer.py app/agent/nodes/critic.py tests/test_agent_synthesizer_critic.py
git commit -m "feat: add synthesizer and critic nodes"
```

---

## Task 11: LangGraph Graph

**Files:**
- Create: `app/agent/graph.py`
- Create: `tests/test_agent_graph.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_agent_graph.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch
from app.agent.state import AgentState


@pytest.mark.asyncio
async def test_graph_runs_full_pipeline():
    planner_result = {"sources_to_use": ["pdf"], "query": "attention mechanisms"}
    retriever_result = {"retrieved_chunks": [{"text": "Attention is key.", "metadata": {}, "source_type": "pdf", "distance": 0.1}]}
    synthesizer_result = {"answer": "Attention allows focus on relevant parts."}
    critic_result = {"needs_replan": False, "iteration": 1, "critic_feedback": ""}

    with (
        patch("app.agent.nodes.planner.chat_complete", new=AsyncMock(
            return_value='{"sources_to_use": ["pdf"], "rewritten_query": "attention mechanisms"}')),
        patch("app.agent.nodes.synthesizer.chat_complete", new=AsyncMock(
            return_value="Attention allows focus on relevant parts.")),
        patch("app.agent.nodes.critic.chat_complete", new=AsyncMock(
            return_value='{"quality": "good", "feedback": ""}')),
        patch("app.agent.nodes.retriever.get_embedder") as mock_emb,
        patch("app.agent.nodes.retriever.get_collection") as mock_col,
    ):
        import numpy as np
        mock_emb.return_value.embed_query.return_value = np.array([0.1] * 384)
        mock_col.return_value.query.return_value = {
            "documents": [["Attention is key."]],
            "metadatas": [[{}]],
            "distances": [[0.1]],
        }

        from app.agent.graph import agent_graph
        initial_state: AgentState = {
            "query": "What is attention?",
            "conversation_id": "conv-1",
            "sources_to_use": ["pdf", "youtube", "web"],
            "retrieved_chunks": [],
            "answer": "",
            "critic_feedback": "",
            "needs_replan": False,
            "iteration": 0,
        }
        final_state = await agent_graph.ainvoke(initial_state)

    assert final_state["answer"] == "Attention allows focus on relevant parts."
    assert final_state["needs_replan"] is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_agent_graph.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Create `app/agent/graph.py`**

```python
import os
from langgraph.graph import StateGraph, END

from app.agent.state import AgentState
from app.agent.nodes.planner import planner_node
from app.agent.nodes.retriever import retriever_node
from app.agent.nodes.synthesizer import synthesizer_node
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
    g.add_node("critic", critic_node)

    g.set_entry_point("planner")
    g.add_edge("planner", "retriever")
    g.add_edge("retriever", "synthesizer")
    g.add_edge("synthesizer", "critic")
    g.add_conditional_edges("critic", _route_critic, {"planner": "planner", END: END})

    return g.compile()


agent_graph = build_graph()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_agent_graph.py -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add app/agent/graph.py tests/test_agent_graph.py
git commit -m "feat: build LangGraph agent with Planner→Retriever→Synthesizer→Critic"
```

---

## Task 12: Ingest API

**Files:**
- Create: `app/api/ingest.py`
- Create: `tests/test_api_ingest.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_api_ingest.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
import io


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def test_ingest_pdf_returns_source_id(client):
    with patch("app.api.ingest.ingest_pdf", new=AsyncMock(return_value="src-123")):
        response = client.post(
            "/api/v1/ingest/pdf",
            files={"file": ("test.pdf", io.BytesIO(b"%PDF-fake"), "application/pdf")},
        )
    assert response.status_code == 200
    assert response.json()["source_id"] == "src-123"


def test_ingest_youtube_returns_source_id(client):
    with patch("app.api.ingest.ingest_youtube", new=AsyncMock(return_value="src-456")):
        response = client.post(
            "/api/v1/ingest/youtube",
            json={"url": "https://youtube.com/watch?v=abc123"},
        )
    assert response.status_code == 200
    assert response.json()["source_id"] == "src-456"


def test_ingest_web_returns_source_id(client):
    with patch("app.api.ingest.ingest_web", new=AsyncMock(return_value="src-789")):
        response = client.post(
            "/api/v1/ingest/web",
            json={"url": "https://example.com/article"},
        )
    assert response.status_code == 200
    assert response.json()["source_id"] == "src-789"


def test_list_sources_returns_empty_on_no_data(client):
    mock_col = MagicMock()
    mock_col.get.return_value = {"metadatas": []}
    with patch("app.api.ingest.get_collection", return_value=mock_col):
        response = client.get("/api/v1/sources")
    assert response.status_code == 200
    assert response.json()["sources"] == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_api_ingest.py -v
```

Expected: fails (app not updated yet to include ingest router)

- [ ] **Step 3: Create `app/api/ingest.py`**

```python
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.core.chroma import get_collection
from app.services.ingestion.pdf import ingest_pdf, SUPPORTED_TYPES
from app.services.ingestion.youtube import ingest_youtube
from app.services.ingestion.web import ingest_web

router = APIRouter()


class UrlRequest(BaseModel):
    url: str


class IngestResponse(BaseModel):
    source_id: str
    message: str


@router.post("/ingest/pdf", response_model=IngestResponse)
async def ingest_pdf_endpoint(file: UploadFile = File(...)):
    if file.content_type not in SUPPORTED_TYPES:
        raise HTTPException(400, f"Unsupported file type: {file.content_type}")

    suffix = Path(file.filename or "upload").suffix or ".bin"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        source_id = await ingest_pdf(tmp_path, file.filename or "upload", file.content_type)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return IngestResponse(source_id=source_id, message=f"Ingested {file.filename}")


@router.post("/ingest/youtube", response_model=IngestResponse)
async def ingest_youtube_endpoint(req: UrlRequest):
    try:
        source_id = await ingest_youtube(req.url)
    except Exception as exc:
        raise HTTPException(400, str(exc))
    return IngestResponse(source_id=source_id, message=f"Ingested YouTube: {req.url}")


@router.post("/ingest/web", response_model=IngestResponse)
async def ingest_web_endpoint(req: UrlRequest):
    try:
        source_id = await ingest_web(req.url)
    except Exception as exc:
        raise HTTPException(400, str(exc))
    return IngestResponse(source_id=source_id, message=f"Ingested web: {req.url}")


@router.get("/sources")
async def list_sources():
    sources = []
    for name in ("pdf_chunks", "youtube_chunks", "web_chunks"):
        try:
            col = get_collection(name)
            results = col.get(include=["metadatas"])
            seen_ids: set[str] = set()
            for meta in results["metadatas"]:
                sid = meta.get("source_id")
                if sid and sid not in seen_ids:
                    seen_ids.add(sid)
                    sources.append({
                        "source_id": sid,
                        "source_type": name.replace("_chunks", ""),
                        **{k: v for k, v in meta.items()
                           if k in ("filename", "title", "url", "ingested_at", "scraped_at")},
                    })
        except Exception:
            pass
    return {"sources": sources}


@router.delete("/sources/{source_id}")
async def delete_source(source_id: str):
    deleted = False
    for name in ("pdf_chunks", "youtube_chunks", "web_chunks"):
        try:
            col = get_collection(name)
            results = col.get(where={"source_id": source_id}, include=[])
            if results["ids"]:
                col.delete(ids=results["ids"])
                deleted = True
        except Exception:
            pass
    if not deleted:
        raise HTTPException(404, f"Source {source_id} not found")
    return {"message": f"Deleted source {source_id}"}
```

- [ ] **Step 4: Run test to verify it passes (after main.py update in next step)**

Defer to Task 13 after main.py is updated.

- [ ] **Step 5: Commit ingest router**

```bash
git add app/api/ingest.py tests/test_api_ingest.py
git commit -m "feat: add ingest API endpoints for pdf, youtube, and web"
```

---

## Task 13: Chat API & Updated main.py

**Files:**
- Create: `app/api/chat.py`
- Modify: `app/main.py`
- Create: `tests/test_api_chat.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_api_chat.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    from app.core.database import get_db

    async def mock_db():
        session = MagicMock()
        session.get = AsyncMock(return_value=None)
        session.flush = AsyncMock()
        session.add = MagicMock()
        session.commit = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(return_value=result_mock)
        yield session

    app.dependency_overrides[get_db] = mock_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_chat_streams_sse_answer(client):
    final_state = {
        "query": "What is attention?",
        "conversation_id": "conv-123",
        "sources_to_use": ["pdf"],
        "retrieved_chunks": [],
        "answer": "Attention is a mechanism.",
        "critic_feedback": "",
        "needs_replan": False,
        "iteration": 1,
    }

    with patch("app.api.chat.agent_graph") as mock_graph:
        mock_graph.ainvoke = AsyncMock(return_value=final_state)
        response = client.post(
            "/api/v1/chat",
            json={"query": "What is attention?"},
        )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert "Attention" in response.text
    assert "[DONE]" in response.text
```

- [ ] **Step 2: Create `app/api/chat.py`**

```python
import uuid
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.conversation import Conversation, Message, MessageRole
from app.agent.graph import agent_graph
from app.agent.state import AgentState

router = APIRouter()


class ChatRequest(BaseModel):
    query: str
    conversation_id: str | None = None
    sources: list[str] | None = None


@router.post("/chat")
async def chat(req: ChatRequest, db: AsyncSession = Depends(get_db)):
    if req.conversation_id:
        conv = await db.get(Conversation, req.conversation_id)
        if not conv:
            raise HTTPException(404, "Conversation not found")
    else:
        conv = Conversation(title=req.query[:100])
        db.add(conv)
        await db.flush()

    history_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.created_at)
        .limit(10)
    )
    history = [
        {"role": m.role.value, "content": m.content}
        for m in history_result.scalars().all()
    ]

    initial_state: AgentState = {
        "query": req.query,
        "conversation_id": conv.id,
        "sources_to_use": req.sources or ["pdf", "youtube", "web"],
        "retrieved_chunks": [],
        "answer": "",
        "critic_feedback": "",
        "needs_replan": False,
        "iteration": 0,
    }

    final_state = await agent_graph.ainvoke(initial_state)
    answer = final_state["answer"]

    db.add(Message(conversation_id=conv.id, role=MessageRole.user, content=req.query))
    db.add(Message(conversation_id=conv.id, role=MessageRole.assistant, content=answer))
    await db.commit()

    async def sse_stream():
        for word in answer.split():
            yield f"data: {word} \n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        sse_stream(),
        media_type="text/event-stream",
        headers={"X-Conversation-Id": conv.id},
    )
```

- [ ] **Step 3: Rewrite `app/main.py`**

```python
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from app.core.config import settings
from app.core.database import create_all_tables
from app.api import health
from app.api import ingest
from app.api import chat

logger = logging.getLogger("app")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_all_tables()
    logger.info("startup", extra={"app": settings.app_name, "version": settings.version})
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    debug=settings.debug,
    lifespan=lifespan,
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    start = time.perf_counter()
    response = None
    try:
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        return response
    except Exception:
        logger.exception(
            "request_failed",
            extra={"request_id": request_id, "method": request.method, "path": request.url.path},
        )
        raise
    finally:
        duration = time.perf_counter() - start
        status = response.status_code if response else 500
        logger.info(
            "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": status,
                "duration_s": round(duration, 4),
            },
        )


app.include_router(health.router, prefix=settings.api_prefix, tags=["Health"])
app.include_router(ingest.router, prefix=settings.api_prefix, tags=["Ingest"])
app.include_router(chat.router, prefix=settings.api_prefix, tags=["Chat"])


@app.get("/")
async def root():
    return {"status": "ok", "app": settings.app_name, "version": settings.version}
```

- [ ] **Step 4: Add pytest config for asyncio**

Create `pytest.ini` at project root:

```ini
[pytest]
asyncio_mode = auto
```

- [ ] **Step 5: Run all tests**

```bash
pytest tests/ -v
```

Expected: all tests pass (models, chroma, llm, ingestion, agent nodes, graph, ingest API, chat API)

- [ ] **Step 6: Start the server and verify it starts**

```bash
source venv/bin/activate && uvicorn app.main:app --reload
```

Expected: server starts on port 8000, no import errors in logs. Visit `http://localhost:8000/docs` — should show Health, Ingest, Chat route groups.

- [ ] **Step 7: Commit**

```bash
git add app/api/chat.py app/main.py tests/test_api_chat.py pytest.ini
git add -u
git commit -m "feat: add chat API, update main.py — agent is wired up end to end"
```

---

## Task 14: Docker

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `.env.example`

- [ ] **Step 1: Create `Dockerfile`**

```dockerfile
FROM python:3.13-slim

RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Create `docker-compose.yml`**

```yaml
services:
  app:
    build: .
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      chromadb:
        condition: service_healthy
    volumes:
      - ./data:/app/data

  chromadb:
    image: chromadb/chroma:latest
    ports:
      - "8001:8000"
    volumes:
      - ./chroma_data:/chroma/chroma
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/v1/heartbeat"]
      interval: 10s
      timeout: 5s
      retries: 5
```

- [ ] **Step 3: Create `.env.example`**

```
GROQ_API_KEY=your_groq_api_key_here
LANGSMITH_API_KEY=your_langsmith_api_key_here
LANGSMITH_PROJECT=docchat-agent

# ChromaDB — use these values when running with docker-compose
CHROMA_HOST=chromadb
CHROMA_PORT=8000

# Optional
YOUTUBE_API_KEY=
DEBUG=false
```

- [ ] **Step 4: Build and verify Docker image**

```bash
docker build -t docchat-agent .
```

Expected: image builds without errors.

- [ ] **Step 5: Start with docker-compose**

```bash
cp .env.example .env
# Edit .env with your real GROQ_API_KEY
docker-compose up
```

Expected: both `app` and `chromadb` containers start. Visit `http://localhost:8000/docs`.

- [ ] **Step 6: Commit**

```bash
git add Dockerfile docker-compose.yml .env.example
git commit -m "feat: add Dockerfile and docker-compose for app + chromadb"
```

---

## Task 15: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Rewrite project-specific sections of `CLAUDE.md`**

Replace only the **Project Overview**, **Commands**, and **Architecture** sections. Keep **Workflow Orchestration**, **Task Management**, **Core Principles**, and **graphify** sections unchanged.

New **Project Overview**:
```markdown
## Project Overview

DocChat Agent is a multi-source agentic research assistant (v2.0.0). Users ingest PDFs, YouTube videos, and web pages. A LangGraph agent (Planner → Retriever → Synthesizer → Critic) orchestrates retrieval across three ChromaDB vector collections and synthesizes answers via Groq. All LLM traces visible in LangSmith.
```

New **Commands**:
```markdown
## Commands

```bash
# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the dev server (requires ChromaDB running — see Docker below)
uvicorn app.main:app --reload

# Start full stack with Docker Compose
docker-compose up

# Run ChromaDB locally (without Docker)
pip install chromadb
chroma run --host localhost --port 8001 --path ./chroma_data

# Run tests
pytest tests/ -v

# API docs
http://localhost:8000/docs
```
```

New **Architecture**:
```markdown
## Architecture

- **app/main.py** — FastAPI app, registers health/ingest/chat routers, SQLite table creation on startup.
- **app/core/config.py** — Pydantic Settings singleton. Extended with ChromaDB, LangSmith, YouTube settings.
- **app/core/database.py** — Async SQLAlchemy engine (SQLite). Stores conversation history only.
- **app/core/chroma.py** — ChromaDB HttpClient singleton + `get_collection(name)` helper.
- **app/agent/state.py** — `AgentState` TypedDict (query, sources_to_use, retrieved_chunks, answer, critic_feedback, needs_replan, iteration).
- **app/agent/graph.py** — Compiled LangGraph StateGraph. Entry point: `agent_graph.ainvoke(state)`.
- **app/agent/nodes/** — Four nodes: `planner` (source selection), `retriever` (ChromaDB queries), `synthesizer` (Groq answer), `critic` (quality gate with replan loop).
- **app/services/ingestion/pdf.py** — pymupdf + late-chunking embedder → ChromaDB `pdf_chunks`.
- **app/services/ingestion/youtube.py** — youtube-transcript-api + pytube → ChromaDB `youtube_chunks`.
- **app/services/ingestion/web.py** — httpx + trafilatura → ChromaDB `web_chunks`.
- **app/services/llm.py** — AsyncGroq client. `chat_complete()` and `chat_stream()`.
- **app/services/embedder.py** — LateChunkingEmbedder (BAAI/bge-small-en-v1.5 ONNX). Used by all ingestion services and the retriever.
- **app/api/ingest.py** — POST /ingest/pdf, /ingest/youtube, /ingest/web. GET/DELETE /sources.
- **app/api/chat.py** — POST /chat. Runs agent, saves history to SQLite, streams SSE answer.
- **app/models/conversation.py** — `Conversation` + `Message` SQLAlchemy models (conversation history).
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for agent architecture"
```

---

## Final Verification

- [ ] Run full test suite:
```bash
pytest tests/ -v
```
Expected: all tests pass.

- [ ] Start server and smoke test:
```bash
uvicorn app.main:app --reload
curl http://localhost:8000/api/v1/health
```
Expected: `{"status": "ok"}`

- [ ] Check API docs show all three route groups:
```
http://localhost:8000/docs
```
Expected: Health, Ingest (pdf/youtube/web), Chat sections visible.
