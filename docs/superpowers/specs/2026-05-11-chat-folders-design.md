# Chat Folders — Design Spec
**Date:** 2026-05-11  
**Status:** Approved

## Overview

Add manual folder organisation to DocChat, styled after Claude's Projects UI. Users create named folders and assign conversations to them. New conversations land in Uncategorized until moved. Also fixes conversation persistence — conversations are currently lost on page refresh because the frontend never fetches saved history from SQLite.

## Data Model

### New `folders` table
| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID string | Primary key |
| `name` | VARCHAR(100) | Folder display name |
| `created_at` | DateTime (UTC) | Server default |

### Changes to `conversations` table
| Column | Type | Notes |
|--------|------|-------|
| `folder_id` | VARCHAR (nullable FK → `folders.id`) | NULL = Uncategorized |

**Deletion behaviour:** Deleting a folder sets `folder_id = NULL` on all its conversations (they become Uncategorized). Conversations are never deleted by folder deletion.

**Migration:** Added to the existing `_run_migrations()` startup function in `app/core/database.py` — creates `folders` table and adds `folder_id` column to `conversations` idempotently.

## Backend API

New router `app/api/folders.py`, mounted at `/api/v1`.

### Folder endpoints
| Method | Path | Body / Response |
|--------|------|-----------------|
| `POST` | `/folders` | `{name}` → `Folder` |
| `GET` | `/folders` | `[{id, name, created_at, conversation_count}]` |
| `PATCH` | `/folders/{id}` | `{name}` → `Folder` |
| `DELETE` | `/folders/{id}` | 204; conversations become Uncategorized |

### Conversation endpoints (new, in `app/api/conversations.py`)
| Method | Path | Response |
|--------|------|----------|
| `GET` | `/conversations` | All conversations with `folder_id`, `title`, `created_at` |
| `GET` | `/conversations/{id}` | Conversation + full message list (for reload on refresh) |
| `PATCH` | `/conversations/{id}` | `{folder_id: "<uuid> or null"}` → moves to folder / Uncategorized |

Existing `POST /chat` is unchanged — new chats always start with `folder_id = NULL`.

## Frontend

### Conversation persistence fix
- Active `conversationId` stored in `localStorage` on every new chat / conversation switch.
- On page load: if `localStorage` has a `conversationId`, fetch `GET /conversations/{id}` and render its messages into the chat panel before the user types anything.

### Sidebar layout
The existing left panel is replaced with a full-height sidebar:

```
┌─────────────────────┐
│ + New Chat          │
│ + New Folder        │
├─────────────────────┤
│ 📁 Work Research ▾  │
│   · Chat about ML   │
│   · Legal review    │
├─────────────────────┤
│ 📁 Personal ▾       │
│   · Travel plans    │
├─────────────────────┤
│ Uncategorized       │
│   · what is the...  │  ← active conversation highlighted
└─────────────────────┘
```

**Interactions:**
- Clicking a chat item loads it in the main panel and updates `localStorage`.
- "**+ New Folder**" → inline text input to name the folder; creates it on Enter.
- "**...**" menu on each chat item → "Move to folder" submenu listing all folders + "Uncategorized".
- Folders are collapsible (click name to toggle).
- Active conversation is highlighted.

**Ingest source panel:** Moved into a collapsible section at the top of the main chat area (no longer in the sidebar).

## File Changes Summary

| File | Change |
|------|--------|
| `app/models/conversation.py` | Add `Folder` model; add `folder_id` FK to `Conversation` |
| `app/core/database.py` | Add migration for `folders` table + `folder_id` column |
| `app/api/folders.py` | New — folder CRUD router |
| `app/api/conversations.py` | New — conversation list + detail + move endpoints |
| `app/main.py` | Register new routers |
| `app/static/index.html` | Replace left panel with sidebar markup |
| `app/static/app.js` | Sidebar rendering, conversation load/switch, folder CRUD, localStorage persistence |
| `app/static/styles.css` | Sidebar styles |

## Out of Scope

- Automatic/AI-based folder assignment
- Nested folders (sub-folders)
- Drag-and-drop to move chats (use "..." menu instead)
- Search within a folder
