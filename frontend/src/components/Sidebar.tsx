import { useEffect, useRef, useState } from 'react';
import { apiJson } from '../api';
import type { Conversation, Folder } from '../types';

interface Props {
  activeConvId: string | null;
  onSelectConv: (id: string) => void;
  onNewChat: (folderId?: string) => void;
  onLogout: () => void;
  email: string;
  health: 'ok' | 'fail' | 'unknown';
  refreshTrigger: number;
}

interface CtxMenu {
  convId: string;
  x: number;
  y: number;
}

export default function Sidebar({ activeConvId, onSelectConv, onNewChat, onLogout, email, health, refreshTrigger }: Props) {
  const [folders, setFolders] = useState<Folder[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [collapsedFolders, setCollapsedFolders] = useState<Set<string>>(new Set());
  const [showFolderInput, setShowFolderInput] = useState(false);
  const [folderName, setFolderName] = useState('');
  const [ctxMenu, setCtxMenu] = useState<CtxMenu | null>(null);
  const [dragTarget, setDragTarget] = useState<string | null>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { load(); }, [refreshTrigger]);

  async function load() {
    const [f, c] = await Promise.all([
      apiJson<Folder[]>('/folders').catch(() => [] as Folder[]),
      apiJson<Conversation[]>('/conversations').catch(() => [] as Conversation[]),
    ]);
    setFolders(f);
    setConversations(c);
  }

  async function createFolder() {
    const name = folderName.trim();
    if (!name) return;
    await apiJson<Folder>('/folders', {
      method: 'POST',
      body: JSON.stringify({ name }),
    }).catch(() => null);
    setFolderName('');
    setShowFolderInput(false);
    load();
  }

  async function moveToFolder(convId: string, folderId: string | null) {
    await apiJson(`/conversations/${convId}`, {
      method: 'PATCH',
      body: JSON.stringify({ folder_id: folderId }),
    }).catch(() => null);
    load();
    setCtxMenu(null);
  }

  function toggleFolder(id: string) {
    setCollapsedFolders(s => {
      const n = new Set(s);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });
  }

  function openCtx(e: React.MouseEvent, convId: string) {
    e.preventDefault();
    e.stopPropagation();
    setCtxMenu({ convId, x: e.clientX, y: e.clientY });
  }

  useEffect(() => {
    if (!ctxMenu) return;
    const close = () => setCtxMenu(null);
    window.addEventListener('click', close);
    return () => window.removeEventListener('click', close);
  }, [ctxMenu]);

  // Show folder input and focus
  useEffect(() => {
    if (showFolderInput) folderInputRef.current?.focus();
  }, [showFolderInput]);

  const folderConvs = (folderId: string) => conversations.filter(c => c.folder_id === folderId);
  const uncategorized = conversations.filter(c => c.folder_id === null);

  return (
    <aside className="sidebar">
      <header className="sidebar-header">
        <div className="logo">
          <svg className="logo-gem" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M12 2L22 8V16L12 22L2 16V8L12 2Z" stroke="currentColor" strokeWidth="1.5" fill="none"/>
            <path d="M12 2L12 22M2 8L22 8M2 16L22 16" stroke="currentColor" strokeWidth="0.75" opacity="0.4"/>
          </svg>
          <span className="logo-text">DocChat <em>Agent</em></span>
        </div>
        <div className="health-badge">
          <span className={`health-dot ${health}`}></span>
          <span>{health === 'ok' ? 'ok' : health === 'fail' ? 'err' : '—'}</span>
        </div>
      </header>

      <div className="user-row">
        <span className="user-email">{email}</span>
        <button className="logout-btn" title="Sign out" onClick={onLogout}>
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M6 3H3a1 1 0 00-1 1v8a1 1 0 001 1h3M10 5l3 3-3 3M13 8H6"/>
          </svg>
        </button>
      </div>

      <div className="sidebar-actions">
        <button className="action-btn" onClick={() => onNewChat()}>
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M8 3v10M3 8h10"/>
          </svg>
          New Chat
        </button>
        <button className="action-btn action-btn-secondary" onClick={() => setShowFolderInput(v => !v)}>
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M1 4a1 1 0 011-1h4l1.5 2H14a1 1 0 011 1v7a1 1 0 01-1 1H2a1 1 0 01-1-1V4z"/>
          </svg>
          New Folder
        </button>
        {showFolderInput && (
          <div className="new-folder-input-wrap">
            <input
              ref={folderInputRef}
              className="new-folder-input"
              placeholder="Folder name…"
              maxLength={100}
              value={folderName}
              onChange={e => setFolderName(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter') createFolder();
                if (e.key === 'Escape') { setShowFolderInput(false); setFolderName(''); }
              }}
              onBlur={() => { if (!folderName.trim()) setShowFolderInput(false); }}
            />
          </div>
        )}
      </div>

      <nav className="conv-nav">
        {folders.length === 0 && conversations.length === 0 && (
          <p className="empty-hint">No conversations yet.</p>
        )}

        {folders.map(folder => (
          <div
            key={folder.id}
            className={`folder-section ${collapsedFolders.has(folder.id) ? 'collapsed' : ''} ${dragTarget === folder.id ? 'drag-target' : ''}`}
            onDragOver={e => { e.preventDefault(); setDragTarget(folder.id); }}
            onDragLeave={() => setDragTarget(null)}
            onDrop={e => {
              e.preventDefault();
              const convId = e.dataTransfer.getData('text/plain');
              if (convId) moveToFolder(convId, folder.id);
              setDragTarget(null);
            }}
          >
            <div className="folder-header" onClick={() => toggleFolder(folder.id)}>
              <svg className="folder-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M1 4a1 1 0 011-1h4l1.5 2H14a1 1 0 011 1v7a1 1 0 01-1 1H2a1 1 0 01-1-1V4z"/>
              </svg>
              <span className="folder-name">{folder.name}</span>
              <button
                className="folder-new-chat-btn"
                title="New chat in folder"
                onClick={e => { e.stopPropagation(); onNewChat(folder.id); }}
              >
                <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <path d="M8 3v10M3 8h10"/>
                </svg>
              </button>
              <svg className="folder-chevron" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M4 6l4 4 4-4"/>
              </svg>
            </div>
            <div className="folder-conv-list">
              {folderConvs(folder.id).map(conv => (
                <ConvItem
                  key={conv.id}
                  conv={conv}
                  active={conv.id === activeConvId}
                  onSelect={() => onSelectConv(conv.id)}
                  onMenu={openCtx}
                />
              ))}
            </div>
          </div>
        ))}

        {uncategorized.length > 0 && (
          <>
            {folders.length > 0 && <div className="uncategorized-label">Other</div>}
            {uncategorized.map(conv => (
              <ConvItem
                key={conv.id}
                conv={conv}
                active={conv.id === activeConvId}
                onSelect={() => onSelectConv(conv.id)}
                onMenu={openCtx}
              />
            ))}
          </>
        )}
      </nav>

      {ctxMenu && (
        <div className="ctx-menu" style={{ left: ctxMenu.x, top: ctxMenu.y }} onClick={e => e.stopPropagation()}>
          <div className="ctx-menu-label">Move to folder</div>
          <button className="ctx-menu-item" onClick={() => moveToFolder(ctxMenu.convId, null)}>No folder</button>
          {folders.map(f => (
            <button
              key={f.id}
              className={`ctx-menu-item ${conversations.find(c => c.id === ctxMenu.convId)?.folder_id === f.id ? 'active-folder' : ''}`}
              onClick={() => moveToFolder(ctxMenu.convId, f.id)}
            >{f.name}</button>
          ))}
        </div>
      )}
    </aside>
  );
}

function ConvItem({ conv, active, onSelect, onMenu }: {
  conv: Conversation;
  active: boolean;
  onSelect: () => void;
  onMenu: (e: React.MouseEvent, id: string) => void;
}) {
  return (
    <div
      className={`conv-item ${active ? 'active' : ''}`}
      draggable
      onClick={onSelect}
      onDragStart={e => e.dataTransfer.setData('text/plain', conv.id)}
    >
      <span className="conv-title">{conv.title || 'New conversation'}</span>
      <button
        className="conv-menu-btn"
        onClick={e => onMenu(e, conv.id)}
      >⋯</button>
    </div>
  );
}
