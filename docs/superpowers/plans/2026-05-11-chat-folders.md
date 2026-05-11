# Chat Folders Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add manual folder organisation to DocChat with a left sidebar showing folders and conversations, and fix conversation persistence across page refreshes.

**Architecture:** A new `Folder` SQLAlchemy model links to `Conversation` via a nullable FK. Two new API routers expose folder CRUD and conversation list/detail/move. The frontend sidebar is restructured to show folders and chats; `localStorage` persists the active conversation across refreshes.

**Tech Stack:** FastAPI, SQLAlchemy async, SQLite, vanilla JS, CSS custom properties.

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `app/models/conversation.py` | Add `Folder` model + `folder_id` FK on `Conversation` |
| Modify | `app/core/database.py` | Import `Folder` so `create_all_tables` creates it |
| Create | `app/api/folders.py` | Folder CRUD endpoints |
| Create | `app/api/conversations.py` | Conversation list, detail, move endpoints |
| Modify | `app/main.py` | Register new routers |
| Create | `tests/test_api_folders.py` | Tests for folder endpoints |
| Create | `tests/test_api_conversations.py` | Tests for conversation endpoints |
| Modify | `app/static/index.html` | Restructure sidebar; add collapsible ingest in main area |
| Modify | `app/static/app.js` | Sidebar rendering, localStorage, conversation switching |
| Modify | `app/static/styles.css` | Styles for folder/conversation sidebar elements |

---

## Task 1: Add Folder model and folder_id to Conversation

**Files:**
- Modify: `app/models/conversation.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_models.py` already exists — open it and add at the bottom, OR create a new test file `tests/test_folder_model.py`:

```python
# tests/test_folder_model.py
import pytest
from sqlalchemy import inspect
from app.models.conversation import Folder, Conversation


def test_folder_model_has_expected_columns():
    mapper = inspect(Folder)
    cols = {c.key for c in mapper.columns}
    assert cols == {"id", "name", "created_at"}


def test_conversation_has_folder_id_column():
    mapper = inspect(Conversation)
    cols = {c.key for c in mapper.columns}
    assert "folder_id" in cols


def test_folder_id_is_nullable():
    mapper = inspect(Conversation)
    col = next(c for c in mapper.columns if c.key == "folder_id")
    assert col.columns[0].nullable is True
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd /Users/divyanshu/Desktop/FDE_Projects/docchat
source venv/bin/activate
pytest tests/test_folder_model.py -v
```

Expected: `FAILED` — `Folder` not defined.

- [ ] **Step 3: Add Folder model and folder_id to conversation.py**

Replace the full contents of `app/models/conversation.py` with:

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


class Folder(Base):
    __tablename__ = "folders"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    conversations: Mapped[list["Conversation"]] = relationship(
        "Conversation", back_populates="folder"
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    folder_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("folders.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    folder: Mapped["Folder | None"] = relationship("Folder", back_populates="conversations")
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

- [ ] **Step 4: Update database.py to import Folder**

In `app/core/database.py`, update `create_all_tables` to import the Folder model:

```python
async def create_all_tables() -> None:
    import app.models.conversation  # noqa: F401 — registers Folder, Conversation, Message with Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
```

(The import already covers all models in that module — no change needed if the module is already imported. Just verify it's `import app.models.conversation` not a specific class import.)

- [ ] **Step 5: Run tests to confirm they pass**

```bash
pytest tests/test_folder_model.py -v
```

Expected: 3 PASSED.

- [ ] **Step 6: Commit**

```bash
git add app/models/conversation.py app/core/database.py tests/test_folder_model.py
git commit -m "feat: add Folder model and folder_id FK on Conversation"
```

---

## Task 2: Folder CRUD API

**Files:**
- Create: `app/api/folders.py`
- Create: `tests/test_api_folders.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_api_folders.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from datetime import datetime, timezone


@pytest.fixture
def client():
    from app.main import app
    from app.core.database import get_db

    async def mock_db():
        session = MagicMock()
        session.get = AsyncMock(return_value=None)
        session.add = MagicMock()
        session.commit = AsyncMock()
        session.delete = AsyncMock()
        session.refresh = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        result_mock.all.return_value = []
        session.execute = AsyncMock(return_value=result_mock)
        yield session

    app.dependency_overrides[get_db] = mock_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_list_folders_returns_empty(client):
    response = client.get("/api/v1/folders")
    assert response.status_code == 200
    assert response.json() == []


def test_create_folder_returns_201(client):
    from app.models.conversation import Folder

    folder = Folder(id="f-1", name="Work", created_at=datetime(2026, 5, 11, tzinfo=timezone.utc))

    with patch("app.api.folders.Folder") as MockFolder:
        instance = MagicMock()
        instance.id = "f-1"
        instance.name = "Work"
        instance.created_at = datetime(2026, 5, 11, tzinfo=timezone.utc)
        MockFolder.return_value = instance

        response = client.post("/api/v1/folders", json={"name": "Work"})

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Work"
    assert body["conversation_count"] == 0


def test_rename_folder_404_when_not_found(client):
    response = client.patch("/api/v1/folders/missing-id", json={"name": "New Name"})
    assert response.status_code == 404


def test_delete_folder_404_when_not_found(client):
    response = client.delete("/api/v1/folders/missing-id")
    assert response.status_code == 404
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_api_folders.py -v
```

Expected: `FAILED` — router not registered yet.

- [ ] **Step 3: Create app/api/folders.py**

```python
import uuid as _uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.conversation import Conversation, Folder

router = APIRouter()


class FolderCreate(BaseModel):
    name: str


class FolderRename(BaseModel):
    name: str


@router.post("/folders", status_code=201)
async def create_folder(body: FolderCreate, db: AsyncSession = Depends(get_db)):
    folder = Folder(id=str(_uuid.uuid4()), name=body.name.strip())
    db.add(folder)
    await db.commit()
    await db.refresh(folder)
    return {"id": folder.id, "name": folder.name, "created_at": folder.created_at, "conversation_count": 0}


@router.get("/folders")
async def list_folders(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Folder).order_by(Folder.created_at))
    folders = result.scalars().all()

    counts: dict[str, int] = {}
    if folders:
        count_result = await db.execute(
            select(Conversation.folder_id, func.count(Conversation.id))
            .where(Conversation.folder_id.isnot(None))
            .group_by(Conversation.folder_id)
        )
        counts = dict(count_result.all())

    return [
        {
            "id": f.id,
            "name": f.name,
            "created_at": f.created_at,
            "conversation_count": counts.get(f.id, 0),
        }
        for f in folders
    ]


@router.patch("/folders/{folder_id}")
async def rename_folder(folder_id: str, body: FolderRename, db: AsyncSession = Depends(get_db)):
    folder = await db.get(Folder, folder_id)
    if not folder:
        raise HTTPException(404, "Folder not found")
    folder.name = body.name.strip()
    await db.commit()
    await db.refresh(folder)
    return {"id": folder.id, "name": folder.name, "created_at": folder.created_at}


@router.delete("/folders/{folder_id}", status_code=204)
async def delete_folder(folder_id: str, db: AsyncSession = Depends(get_db)):
    folder = await db.get(Folder, folder_id)
    if not folder:
        raise HTTPException(404, "Folder not found")
    await db.execute(
        update(Conversation).where(Conversation.folder_id == folder_id).values(folder_id=None)
    )
    await db.delete(folder)
    await db.commit()
```

- [ ] **Step 4: Register the router in app/main.py**

Add these two lines to `app/main.py`, after the existing `from app.api import chat` import and after the existing `app.include_router(chat.router, ...)` line:

```python
# In imports section:
from app.api import folders

# After app.include_router(chat.router, ...):
app.include_router(folders.router, prefix=settings.api_prefix, tags=["Folders"])
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
pytest tests/test_api_folders.py -v
```

Expected: 4 PASSED.

- [ ] **Step 6: Commit**

```bash
git add app/api/folders.py app/main.py tests/test_api_folders.py
git commit -m "feat: add folder CRUD API"
```

---

## Task 3: Conversation list, detail, and move API

**Files:**
- Create: `app/api/conversations.py`
- Create: `tests/test_api_conversations.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_api_conversations.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient
from datetime import datetime, timezone


@pytest.fixture
def client():
    from app.main import app
    from app.core.database import get_db

    async def mock_db():
        session = MagicMock()
        session.get = AsyncMock(return_value=None)
        session.add = MagicMock()
        session.commit = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(return_value=result_mock)
        yield session

    app.dependency_overrides[get_db] = mock_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_list_conversations_returns_empty(client):
    response = client.get("/api/v1/conversations")
    assert response.status_code == 200
    assert response.json() == []


def test_get_conversation_404_when_not_found(client):
    response = client.get("/api/v1/conversations/does-not-exist")
    assert response.status_code == 404


def test_move_conversation_404_when_not_found(client):
    response = client.patch("/api/v1/conversations/does-not-exist", json={"folder_id": None})
    assert response.status_code == 404


def test_list_conversations_returns_conversations(client):
    from app.models.conversation import Conversation
    from unittest.mock import patch

    conv = MagicMock(spec=Conversation)
    conv.id = "conv-1"
    conv.title = "Test Chat"
    conv.folder_id = None
    conv.created_at = datetime(2026, 5, 11, tzinfo=timezone.utc)

    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = [conv]

    from app.main import app
    from app.core.database import get_db

    async def mock_db_with_conv():
        session = MagicMock()
        session.execute = AsyncMock(return_value=result_mock)
        yield session

    app.dependency_overrides[get_db] = mock_db_with_conv
    response = client.get("/api/v1/conversations")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == "conv-1"
    assert data[0]["title"] == "Test Chat"
    assert data[0]["folder_id"] is None
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_api_conversations.py -v
```

Expected: `FAILED` — router not registered.

- [ ] **Step 3: Create app/api/conversations.py**

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.conversation import Conversation, Message

router = APIRouter()


class ConversationMove(BaseModel):
    folder_id: str | None = None


@router.get("/conversations")
async def list_conversations(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Conversation).order_by(Conversation.created_at.desc()))
    convs = result.scalars().all()
    return [
        {"id": c.id, "title": c.title, "folder_id": c.folder_id, "created_at": c.created_at}
        for c in convs
    ]


@router.get("/conversations/{conv_id}")
async def get_conversation(conv_id: str, db: AsyncSession = Depends(get_db)):
    conv = await db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    msgs_result = await db.execute(
        select(Message).where(Message.conversation_id == conv_id).order_by(Message.created_at)
    )
    msgs = msgs_result.scalars().all()
    return {
        "id": conv.id,
        "title": conv.title,
        "folder_id": conv.folder_id,
        "created_at": conv.created_at,
        "messages": [
            {"role": m.role.value, "content": m.content, "created_at": m.created_at}
            for m in msgs
        ],
    }


@router.patch("/conversations/{conv_id}")
async def move_conversation(conv_id: str, body: ConversationMove, db: AsyncSession = Depends(get_db)):
    conv = await db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    conv.folder_id = body.folder_id
    await db.commit()
    return {"id": conv.id, "title": conv.title, "folder_id": conv.folder_id}
```

- [ ] **Step 4: Register the router in app/main.py**

Add to `app/main.py`:

```python
# In imports section (add alongside existing api imports):
from app.api import conversations

# After app.include_router(folders.router, ...):
app.include_router(conversations.router, prefix=settings.api_prefix, tags=["Conversations"])
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
pytest tests/test_api_conversations.py -v
```

Expected: 4 PASSED.

- [ ] **Step 6: Run full test suite to verify no regressions**

```bash
pytest tests/ -v --ignore=tests/test_chroma.py --ignore=tests/test_agent_graph.py -x
```

Expected: all passing (chroma/agent tests require live services so skip them).

- [ ] **Step 7: Commit**

```bash
git add app/api/conversations.py app/main.py tests/test_api_conversations.py
git commit -m "feat: add conversation list, detail, and move API"
```

---

## Task 4: Rebuild the HTML sidebar

**Files:**
- Modify: `app/static/index.html`

- [ ] **Step 1: Replace the sidebar section in index.html**

Replace everything inside `<aside class="sidebar">...</aside>` with:

```html
<aside class="sidebar">

  <header class="sidebar-header">
    <div class="logo">
      <svg class="logo-gem" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M12 2L22 8V16L12 22L2 16V8L12 2Z" stroke="currentColor" stroke-width="1.5" fill="none"/>
        <path d="M12 2L12 22M2 8L22 8M2 16L22 16" stroke="currentColor" stroke-width="0.75" opacity="0.4"/>
      </svg>
      <span class="logo-text">DocChat <em>Agent</em></span>
    </div>
    <div class="health-badge" id="healthBadge">
      <span class="health-dot" id="healthDot"></span>
      <span id="healthLabel">—</span>
    </div>
  </header>

  <div class="sidebar-actions">
    <button class="action-btn" id="newChatBtn">
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
        <path d="M8 3v10M3 8h10"/>
      </svg>
      New Chat
    </button>
    <button class="action-btn action-btn-secondary" id="newFolderBtn">
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
        <path d="M1 4a1 1 0 011-1h4l1.5 2H14a1 1 0 011 1v7a1 1 0 01-1 1H2a1 1 0 01-1-1V4z"/>
      </svg>
      New Folder
    </button>
    <div class="new-folder-input-wrap" id="newFolderWrap" style="display:none">
      <input class="new-folder-input" id="newFolderInput" placeholder="Folder name…" maxlength="100" />
    </div>
  </div>

  <nav class="conv-nav" id="convNav">
    <p class="empty-hint" style="padding: 16px 20px;">No conversations yet.</p>
  </nav>

</aside>
```

- [ ] **Step 2: Add collapsible ingest panel to the main area**

In `<main class="chat-panel">`, add this block immediately before `<div class="messages" id="messages">`:

```html
<details class="ingest-panel" id="ingestPanel">
  <summary class="ingest-summary">
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
      <path d="M8 11V3M8 3L5 6M8 3l3 3M2 12v1a1 1 0 001 1h10a1 1 0 001-1v-1"/>
    </svg>
    Ingest Source
    <span class="sources-count-badge" id="sourcesCount">0</span>
    <svg class="chevron" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
      <path d="M4 6l4 4 4-4"/>
    </svg>
  </summary>

  <div class="ingest-body">
    <div class="tab-strip">
      <button class="tab active" data-tab="pdf">PDF</button>
      <button class="tab" data-tab="youtube">YouTube</button>
      <button class="tab" data-tab="web">Web</button>
    </div>

    <div class="tab-pane active" id="pane-pdf">
      <div class="drop-zone" id="dropZone">
        <svg class="drop-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.25">
          <path d="M12 15V3M12 3L8 7M12 3L16 7"/>
          <path d="M3 17v2a2 2 0 002 2h14a2 2 0 002-2v-2"/>
        </svg>
        <p class="drop-label">Drop PDF here</p>
        <p class="drop-sub">or <label class="text-link" for="fileInput">browse</label></p>
        <input type="file" id="fileInput" accept=".pdf" hidden />
      </div>
      <div class="ingest-feedback" id="pdfFeedback"></div>
    </div>

    <div class="tab-pane" id="pane-youtube">
      <div class="url-row">
        <input class="url-input" id="ytUrl" type="url" placeholder="youtube.com/watch?v=…" />
        <button class="pill-btn" id="ytBtn">Go</button>
      </div>
      <div class="ingest-feedback" id="ytFeedback"></div>
    </div>

    <div class="tab-pane" id="pane-web">
      <div class="url-row">
        <input class="url-input" id="webUrl" type="url" placeholder="https://…" />
        <button class="pill-btn" id="webBtn">Go</button>
      </div>
      <div class="ingest-feedback" id="webFeedback"></div>
    </div>

    <div class="sources-list" id="sourcesList" style="margin-top:12px">
      <p class="empty-hint">Nothing ingested yet.</p>
    </div>
  </div>
</details>
```

- [ ] **Step 3: Manual check — open http://localhost:8080 in the browser**

The sidebar should now show "New Chat" and "New Folder" buttons with an empty conversation list. The ingest panel should be a collapsible `<details>` section at the top of the chat area. No JS errors in the console.

- [ ] **Step 4: Commit**

```bash
git add app/static/index.html
git commit -m "feat: restructure sidebar HTML for conversation/folder navigation"
```

---

## Task 5: Add sidebar and persistence CSS

**Files:**
- Modify: `app/static/styles.css`

- [ ] **Step 1: Add new CSS rules to the end of styles.css**

Append the following to `app/static/styles.css`:

```css
/* ── Sidebar Actions ─────────────────────────────────── */
.sidebar-actions {
  padding: 12px 14px;
  border-bottom: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex-shrink: 0;
}

.action-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  background: var(--accent);
  color: #0c0b09;
  border: none;
  border-radius: var(--radius);
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.04em;
  padding: 8px 12px;
  cursor: pointer;
  transition: background var(--transition);
}

.action-btn svg { width: 14px; height: 14px; flex-shrink: 0; }
.action-btn:hover { background: var(--accent-h); }

.action-btn-secondary {
  background: var(--surface-2);
  color: var(--text-2);
  border: 1px solid var(--border);
}

.action-btn-secondary:hover {
  background: var(--surface-3);
  color: var(--text);
  border-color: var(--border-2);
}

.new-folder-input-wrap { padding: 2px 0; }

.new-folder-input {
  width: 100%;
  background: var(--surface-2);
  border: 1px solid var(--accent);
  border-radius: var(--radius);
  color: var(--text);
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  padding: 7px 10px;
  outline: none;
}

/* ── Conversation Nav ─────────────────────────────────── */
.conv-nav {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}

.conv-nav::-webkit-scrollbar { width: 3px; }
.conv-nav::-webkit-scrollbar-track { background: transparent; }
.conv-nav::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }

/* Folder section */
.folder-section { border-bottom: 1px solid var(--border); }

.folder-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px 10px 16px;
  cursor: pointer;
  user-select: none;
  transition: background var(--transition);
}

.folder-header:hover { background: var(--surface-2); }

.folder-icon { width: 13px; height: 13px; color: var(--accent); flex-shrink: 0; }

.folder-name {
  flex: 1;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10.5px;
  font-weight: 500;
  letter-spacing: 0.06em;
  color: var(--text-2);
  text-transform: uppercase;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.folder-chevron {
  width: 12px;
  height: 12px;
  color: var(--text-3);
  transition: transform var(--transition);
  flex-shrink: 0;
}

.folder-section.collapsed .folder-chevron { transform: rotate(-90deg); }
.folder-section.collapsed .folder-conv-list { display: none; }

/* Uncategorized label */
.uncategorized-label {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--text-3);
  padding: 12px 16px 6px;
}

/* Conversation item */
.conv-item {
  display: flex;
  align-items: center;
  gap: 0;
  padding: 7px 10px 7px 28px;
  cursor: pointer;
  transition: background var(--transition);
  position: relative;
  group: true;
}

.folder-conv-list .conv-item { padding-left: 36px; }

.conv-item:hover { background: var(--surface-2); }

.conv-item.active {
  background: var(--accent-dim);
  border-right: 2px solid var(--accent);
}

.conv-title {
  flex: 1;
  font-size: 13px;
  color: var(--text-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.4;
}

.conv-item.active .conv-title { color: var(--text); }

.conv-menu-btn {
  display: none;
  background: none;
  border: none;
  color: var(--text-3);
  cursor: pointer;
  font-size: 16px;
  padding: 2px 6px;
  border-radius: 3px;
  line-height: 1;
  flex-shrink: 0;
}

.conv-item:hover .conv-menu-btn,
.conv-item.active .conv-menu-btn { display: block; }

.conv-menu-btn:hover { color: var(--text-2); background: var(--surface-3); }

/* Context menu */
.ctx-menu {
  position: fixed;
  background: var(--surface-2);
  border: 1px solid var(--border-2);
  border-radius: var(--radius);
  box-shadow: 0 8px 24px rgba(0,0,0,0.4);
  z-index: 1000;
  min-width: 160px;
  padding: 4px 0;
}

.ctx-menu-label {
  font-family: 'JetBrains Mono', monospace;
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--text-3);
  padding: 6px 14px 4px;
}

.ctx-menu-item {
  display: block;
  width: 100%;
  background: none;
  border: none;
  text-align: left;
  color: var(--text-2);
  font-size: 13px;
  padding: 7px 14px;
  cursor: pointer;
  transition: background var(--transition);
}

.ctx-menu-item:hover { background: var(--surface-3); color: var(--text); }
.ctx-menu-item.active-folder { color: var(--accent); }

/* ── Ingest Panel (collapsible in main area) ─────────── */
.ingest-panel {
  border-bottom: 1px solid var(--border);
  background: var(--surface);
  flex-shrink: 0;
}

.ingest-summary {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 11px 20px;
  cursor: pointer;
  list-style: none;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--text-3);
  user-select: none;
  transition: background var(--transition);
}

.ingest-summary:hover { background: var(--surface-2); color: var(--text-2); }
.ingest-summary::-webkit-details-marker { display: none; }
.ingest-summary svg:first-child { width: 14px; height: 14px; flex-shrink: 0; }

.sources-count-badge {
  background: var(--surface-3);
  color: var(--text-2);
  border: 1px solid var(--border);
  font-size: 9px;
  padding: 1px 6px;
  border-radius: 20px;
  line-height: 1.6;
}

.chevron {
  width: 12px;
  height: 12px;
  margin-left: auto;
  transition: transform var(--transition);
}

details[open] .chevron { transform: rotate(180deg); }

.ingest-body { padding: 0 20px 16px; }
```

- [ ] **Step 2: Manual check — open http://localhost:8080**

Sidebar should show styled "New Chat" and "New Folder" buttons. Ingest panel at top of main area should be collapsible (click to expand/collapse). No layout breakage.

- [ ] **Step 3: Commit**

```bash
git add app/static/styles.css
git commit -m "feat: add sidebar and ingest panel CSS"
```

---

## Task 6: Frontend JavaScript — sidebar, conversation switching, localStorage

**Files:**
- Modify: `app/static/app.js`

- [ ] **Step 1: Add conversation state to the state object**

Replace the state declaration at the top of `app/static/app.js`:

```javascript
const state = {
  conversationId: null,
  isStreaming: false,
  activeSources: new Set(['pdf', 'youtube', 'web']),
  folders: [],        // [{ id, name, conversation_count }]
  conversations: [],  // [{ id, title, folder_id, created_at }]
};
```

- [ ] **Step 2: Add localStorage helpers**

Add after the `esc()` function:

```javascript
const LS_KEY = 'docchat_conv_id';

function persistConvId(id) {
  if (id) localStorage.setItem(LS_KEY, id);
  else localStorage.removeItem(LS_KEY);
}

function getPersistedConvId() {
  return localStorage.getItem(LS_KEY);
}
```

- [ ] **Step 3: Add API helpers for conversations and folders**

Add after the existing `apiFetch` function:

```javascript
async function apiFetchConversations() {
  return apiFetch('/conversations');
}

async function apiFetchConversation(id) {
  return apiFetch(`/conversations/${id}`);
}

async function apiMoveConversation(convId, folderId) {
  return apiFetch(`/conversations/${convId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ folder_id: folderId }),
  });
}

async function apiFetchFolders() {
  return apiFetch('/folders');
}

async function apiCreateFolder(name) {
  return apiFetch('/folders', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
}
```

- [ ] **Step 4: Add loadSidebar function**

Add after the API helpers:

```javascript
async function loadSidebar() {
  try {
    const [folders, conversations] = await Promise.all([
      apiFetchFolders(),
      apiFetchConversations(),
    ]);
    state.folders = folders;
    state.conversations = conversations;
    renderSidebar();
  } catch (e) {
    console.error('Failed to load sidebar:', e);
  }
}

function renderSidebar() {
  const nav = document.getElementById('convNav');
  if (!state.conversations.length) {
    nav.innerHTML = '<p class="empty-hint" style="padding:16px 20px;">No conversations yet.</p>';
    return;
  }

  const byFolder = {};
  const uncategorized = [];
  for (const conv of state.conversations) {
    if (conv.folder_id) {
      (byFolder[conv.folder_id] = byFolder[conv.folder_id] || []).push(conv);
    } else {
      uncategorized.push(conv);
    }
  }

  let html = '';

  for (const folder of state.folders) {
    const convs = byFolder[folder.id] || [];
    html += `
      <div class="folder-section" data-folder-id="${esc(folder.id)}">
        <div class="folder-header" onclick="toggleFolder('${esc(folder.id)}')">
          <svg class="folder-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M1 4a1 1 0 011-1h4l1.5 2H14a1 1 0 011 1v7a1 1 0 01-1 1H2a1 1 0 01-1-1V4z"/>
          </svg>
          <span class="folder-name">${esc(folder.name)}</span>
          <svg class="folder-chevron" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M4 6l4 4 4-4"/>
          </svg>
        </div>
        <div class="folder-conv-list">
          ${convs.map(c => convItemHtml(c)).join('') || '<p class="empty-hint" style="padding:6px 36px 10px;font-size:12px;">Empty folder</p>'}
        </div>
      </div>`;
  }

  if (uncategorized.length) {
    html += `<div class="uncategorized-label">Uncategorized</div>`;
    html += uncategorized.map(c => convItemHtml(c)).join('');
  }

  nav.innerHTML = html;
}

function convItemHtml(conv) {
  const active = conv.id === state.conversationId ? ' active' : '';
  const title = esc(conv.title || 'Untitled');
  return `
    <div class="conv-item${active}" data-conv-id="${esc(conv.id)}" onclick="switchConversation('${esc(conv.id)}')">
      <span class="conv-title" title="${title}">${title}</span>
      <button class="conv-menu-btn" title="Move to folder"
        onclick="event.stopPropagation(); openConvMenu(event, '${esc(conv.id)}', '${esc(conv.folder_id || '')}')">⋯</button>
    </div>`;
}

function toggleFolder(folderId) {
  const section = document.querySelector(`.folder-section[data-folder-id="${folderId}"]`);
  if (section) section.classList.toggle('collapsed');
}
```

- [ ] **Step 5: Add switchConversation and startNewChat**

Add after `renderSidebar`:

```javascript
async function switchConversation(convId) {
  if (convId === state.conversationId) return;
  state.conversationId = convId;
  persistConvId(convId);
  renderSidebar();

  const msgs = document.getElementById('messages');
  msgs.innerHTML = '';

  try {
    const conv = await apiFetchConversation(convId);
    if (!conv.messages.length) {
      showWelcome();
      return;
    }
    hideWelcome();
    for (const m of conv.messages) {
      if (m.role === 'user') {
        appendStoredMessage('user', m.content);
      } else {
        appendStoredMessage('assistant', m.content);
      }
    }
  } catch (e) {
    console.error('Failed to load conversation:', e);
  }
}

function appendStoredMessage(role, content) {
  const msgs = document.getElementById('messages');
  const div = document.createElement('div');
  if (role === 'user') {
    div.className = 'msg msg-user';
    div.innerHTML = `
      <div class="msg-avatar">you</div>
      <div class="msg-body"><div class="msg-content">${esc(content)}</div></div>`;
  } else {
    div.className = 'msg msg-assistant';
    div.innerHTML = `
      <div class="msg-avatar">${GEM_SVG}</div>
      <div class="msg-body"><div class="msg-content">${parseCitations(content)}</div></div>`;
  }
  msgs.appendChild(div);
  scrollBottom();
}

function showWelcome() {
  const msgs = document.getElementById('messages');
  if (document.getElementById('welcome')) return;
  const div = document.createElement('div');
  div.id = 'welcome';
  div.className = 'welcome';
  div.innerHTML = `
    <svg class="welcome-gem" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M12 2L22 8V16L12 22L2 16V8L12 2Z" stroke="currentColor" stroke-width="1.25" fill="none"/>
      <path d="M12 2L12 22M2 8L22 8M2 16L22 16" stroke="currentColor" stroke-width="0.6" opacity="0.35"/>
    </svg>
    <h1 class="welcome-title">Research Assistant</h1>
    <p class="welcome-sub">Ingest documents, videos, or web pages — then ask anything.</p>
    <div class="welcome-hints">
      <span class="hint-chip">Explain multi-head attention</span>
      <span class="hint-chip">Summarise key findings</span>
      <span class="hint-chip">Compare sources</span>
    </div>`;
  msgs.appendChild(div);
}

function startNewChat() {
  state.conversationId = null;
  persistConvId(null);
  renderSidebar();
  const msgs = document.getElementById('messages');
  msgs.innerHTML = '';
  showWelcome();
  document.getElementById('chatInput').focus();
}
```

- [ ] **Step 6: Add folder creation and context menu**

Add after `startNewChat`:

```javascript
function initNewFolder() {
  const btn = document.getElementById('newFolderBtn');
  const wrap = document.getElementById('newFolderWrap');
  const input = document.getElementById('newFolderInput');

  btn.addEventListener('click', () => {
    wrap.style.display = wrap.style.display === 'none' ? 'block' : 'none';
    if (wrap.style.display === 'block') {
      input.value = '';
      input.focus();
    }
  });

  input.addEventListener('keydown', async (e) => {
    if (e.key === 'Enter') {
      const name = input.value.trim();
      if (!name) return;
      try {
        await apiCreateFolder(name);
        wrap.style.display = 'none';
        await loadSidebar();
      } catch (err) {
        console.error('Create folder failed:', err);
      }
    }
    if (e.key === 'Escape') {
      wrap.style.display = 'none';
    }
  });
}

let _ctxMenu = null;

function openConvMenu(event, convId, currentFolderId) {
  closeConvMenu();

  const menu = document.createElement('div');
  menu.className = 'ctx-menu';

  let items = `<div class="ctx-menu-label">Move to folder</div>`;

  for (const folder of state.folders) {
    const active = folder.id === currentFolderId ? ' active-folder' : '';
    items += `<button class="ctx-menu-item${active}" onclick="handleMoveConv('${esc(convId)}','${esc(folder.id)}')">${esc(folder.name)}</button>`;
  }

  const uncatActive = !currentFolderId ? ' active-folder' : '';
  items += `<button class="ctx-menu-item${uncatActive}" onclick="handleMoveConv('${esc(convId)}',null)">Uncategorized</button>`;

  menu.innerHTML = items;

  const x = Math.min(event.clientX, window.innerWidth - 180);
  const y = Math.min(event.clientY, window.innerHeight - 200);
  menu.style.left = x + 'px';
  menu.style.top = y + 'px';

  document.body.appendChild(menu);
  _ctxMenu = menu;

  setTimeout(() => document.addEventListener('click', closeConvMenu, { once: true }), 0);
}

function closeConvMenu() {
  if (_ctxMenu) { _ctxMenu.remove(); _ctxMenu = null; }
}

async function handleMoveConv(convId, folderId) {
  closeConvMenu();
  try {
    await apiMoveConversation(convId, folderId || null);
    await loadSidebar();
  } catch (e) {
    console.error('Move conversation failed:', e);
  }
}
```

- [ ] **Step 7: Update sendMessage to persist convId and refresh sidebar**

In the existing `sendMessage` function, after the line:
```javascript
state.conversationId = res.headers.get('X-Conversation-Id') || state.conversationId;
```

Add:
```javascript
persistConvId(state.conversationId);
```

And at the end of the `try` block in `sendMessage`, after `finishAssistantMessage()`, add a call to reload the sidebar:
```javascript
await loadSidebar();
```

- [ ] **Step 8: Update init() to restore conversation and wire up buttons**

Replace the `init()` function with:

```javascript
function init() {
  initTabs();
  initFilters();
  initDropZone();
  initChatInput();
  initNewFolder();

  document.getElementById('newChatBtn').addEventListener('click', startNewChat);
  document.getElementById('ytBtn').addEventListener('click', ingestYoutube);
  document.getElementById('webBtn').addEventListener('click', ingestWeb);

  document.getElementById('ytUrl').addEventListener('keydown', e => {
    if (e.key === 'Enter') ingestYoutube();
  });
  document.getElementById('webUrl').addEventListener('keydown', e => {
    if (e.key === 'Enter') ingestWeb();
  });

  checkHealth();
  loadSources();
  loadSidebar().then(async () => {
    const savedId = getPersistedConvId();
    if (savedId && state.conversations.find(c => c.id === savedId)) {
      await switchConversation(savedId);
    }
  });

  document.getElementById('chatInput').focus();
}
```

- [ ] **Step 9: Manual verification — full browser test**

Start the app (or rebuild Docker) and open http://localhost:8080. Verify:

1. **Sidebar loads** — "New Chat" and "New Folder" buttons visible, conversation list shows any existing conversations.
2. **New Chat** — clicking "New Chat" clears messages and resets to the welcome screen.
3. **New Folder** — clicking "New Folder" shows inline input; typing a name + Enter creates the folder and it appears in the sidebar.
4. **Send a message** — new conversation appears in the "Uncategorized" section of the sidebar after the response completes.
5. **Reload persistence** — after sending a message, reload the page. The same conversation loads with its messages visible.
6. **Switch conversation** — click a different conversation in the sidebar; its messages load in the main panel.
7. **Move to folder** — hover a conversation, click "⋯", choose a folder. The conversation moves to the folder section in the sidebar.
8. **Ingest panel** — clicking "Ingest Source" in the main area expands/collapses the ingest form.

- [ ] **Step 10: Commit**

```bash
git add app/static/app.js
git commit -m "feat: sidebar conversation navigation, folder management, and localStorage persistence"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** Folder CRUD ✓, Conversation list/detail/move ✓, Sidebar layout ✓, localStorage persistence ✓, Collapsible ingest panel ✓, Uncategorized section ✓, Folder collapse ✓, "..." menu ✓
- [x] **No placeholders:** All code blocks contain complete, runnable code
- [x] **Type consistency:** `folder_id` is nullable `str | None` throughout backend and frontend; `conv.id`, `folder.id` are strings everywhere; `apiFetch` returns parsed JSON consistently
- [x] **Router registration:** Both `folders.router` and `conversations.router` are registered in Task 2/3 Step 4 — no gap
- [x] **sendMessage update:** `persistConvId` + `loadSidebar` added in Task 6 Step 7
