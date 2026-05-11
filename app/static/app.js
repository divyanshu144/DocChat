// ── State ─────────────────────────────────────────────────
const state = {
  conversationId: null,
  isStreaming: false,
  activeSources: new Set(['pdf', 'youtube', 'web']),
  folders: [],
  conversations: [],
  targetFolderId: null,
};

// ── Utilities ─────────────────────────────────────────────
function esc(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function formatWhen(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
    + ' ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}

function sourceLabel(s) {
  return s.filename || s.title || s.url || s.source_id || '—';
}

// ── localStorage ───────────────────────────────────────────
const LS_KEY = 'docchat_conv_id';

function persistConvId(id) {
  if (id) localStorage.setItem(LS_KEY, id);
  else localStorage.removeItem(LS_KEY);
}

function getPersistedConvId() {
  return localStorage.getItem(LS_KEY);
}

// ── Citation Parser ────────────────────────────────────────
function parseCitations(text) {
  return text.replace(
    /\[PDF\s*[—–-]\s*([^\]]+?)\]/gi,
    (_, inner) => `<span class="cite cite-pdf">${esc(inner.trim())}</span>`
  ).replace(
    /\[YouTube\s*[—–-]\s*([^\]]+?)\]/gi,
    (_, inner) => `<span class="cite cite-yt">${esc(inner.trim())}</span>`
  ).replace(
    /\[Web\s*[—–-]\s*([^\]]+?)\]/gi,
    (_, inner) => `<span class="cite cite-web">${esc(inner.trim())}</span>`
  );
}

// ── API ────────────────────────────────────────────────────
async function apiFetch(path, options = {}) {
  const res = await fetch(`/api/v1${path}`, options);
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

async function checkHealth() {
  try {
    const data = await apiFetch('/health');
    const dot = document.getElementById('healthDot');
    const lbl = document.getElementById('healthLabel');
    dot.className = 'health-dot ok';
    lbl.textContent = `v${data.version}`;
  } catch {
    const dot = document.getElementById('healthDot');
    const lbl = document.getElementById('healthLabel');
    dot.className = 'health-dot fail';
    lbl.textContent = 'offline';
  }
}

async function loadSources() {
  try {
    const data = await apiFetch('/sources');
    renderSources(data.sources || []);
  } catch {
    renderSources([]);
  }
}

async function deleteSource(sourceId) {
  await apiFetch(`/sources/${sourceId}`, { method: 'DELETE' });
  await loadSources();
}

// ── Source Rendering ───────────────────────────────────────
function renderSources(sources) {
  const list = document.getElementById('sourcesList');
  const count = document.getElementById('sourcesCount');
  count.textContent = sources.length;

  if (!sources.length) {
    list.innerHTML = '<p class="empty-hint">Nothing ingested yet.</p>';
    return;
  }

  list.innerHTML = sources.map(s => {
    const type = s.source_type || 'web';
    const badgeClass = type === 'pdf' ? 'badge-pdf' : type === 'youtube' ? 'badge-youtube' : 'badge-web';
    const when = formatWhen(s.ingested_at || s.scraped_at || '');
    const label = esc(sourceLabel(s));
    return `
      <div class="source-card" data-id="${esc(s.source_id)}">
        <span class="source-type-badge ${badgeClass}">${esc(type)}</span>
        <div class="source-meta">
          <div class="source-title" title="${label}">${label}</div>
          ${when ? `<div class="source-when">${when}</div>` : ''}
        </div>
        <button class="source-delete" title="Delete source" onclick="handleDelete('${esc(s.source_id)}')">✕</button>
      </div>`;
  }).join('');
}

async function handleDelete(sourceId) {
  try {
    await deleteSource(sourceId);
  } catch (e) {
    console.error('Delete failed:', e);
  }
}

// ── Ingest Feedback ────────────────────────────────────────
function setFeedback(elId, cls, html) {
  const el = document.getElementById(elId);
  el.className = `ingest-feedback ${cls}`;
  el.innerHTML = html;
}

// ── PDF Ingest ─────────────────────────────────────────────
async function ingestPdf(file) {
  setFeedback('pdfFeedback', 'busy', `<span class="spinner"></span>Ingesting ${esc(file.name)}…`);
  try {
    const fd = new FormData();
    fd.append('file', file);
    const data = await apiFetch('/ingest/pdf', { method: 'POST', body: fd });
    setFeedback('pdfFeedback', 'ok', `✓ Ingested — ${esc(file.name)}`);
    await loadSources();
    setTimeout(() => setFeedback('pdfFeedback', '', ''), 4000);
  } catch (e) {
    setFeedback('pdfFeedback', 'err', `✕ ${esc(e.message)}`);
  }
}

// ── YouTube Ingest ─────────────────────────────────────────
async function ingestYoutube() {
  const url = document.getElementById('ytUrl').value.trim();
  if (!url) return;
  const btn = document.getElementById('ytBtn');
  btn.disabled = true;
  setFeedback('ytFeedback', 'busy', `<span class="spinner"></span>Fetching transcript…`);
  try {
    await apiFetch('/ingest/youtube', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    });
    setFeedback('ytFeedback', 'ok', `✓ Ingested`);
    document.getElementById('ytUrl').value = '';
    await loadSources();
    setTimeout(() => setFeedback('ytFeedback', '', ''), 4000);
  } catch (e) {
    setFeedback('ytFeedback', 'err', `✕ ${esc(e.message)}`);
  } finally {
    btn.disabled = false;
  }
}

// ── Web Ingest ─────────────────────────────────────────────
async function ingestWeb() {
  const url = document.getElementById('webUrl').value.trim();
  if (!url) return;
  const btn = document.getElementById('webBtn');
  btn.disabled = true;
  setFeedback('webFeedback', 'busy', `<span class="spinner"></span>Scraping page…`);
  try {
    await apiFetch('/ingest/web', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    });
    setFeedback('webFeedback', 'ok', `✓ Ingested`);
    document.getElementById('webUrl').value = '';
    await loadSources();
    setTimeout(() => setFeedback('webFeedback', '', ''), 4000);
  } catch (e) {
    setFeedback('webFeedback', 'err', `✕ ${esc(e.message)}`);
  } finally {
    btn.disabled = false;
  }
}

// ── Sidebar ────────────────────────────────────────────────
async function loadSidebar() {
  try {
    const [folders, conversations] = await Promise.all([
      apiFetch('/folders'),
      apiFetch('/conversations'),
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
  if (!state.conversations.length && !state.folders.length) {
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
    const activeClass = folder.id === state.targetFolderId ? ' folder-active' : '';
    html += `
      <div class="folder-section${activeClass}" data-folder-id="${esc(folder.id)}"
        ondragover="handleFolderDragOver(event,'${esc(folder.id)}')"
        ondragleave="handleFolderDragLeave(event,'${esc(folder.id)}')"
        ondrop="handleFolderDrop(event,'${esc(folder.id)}')">
        <div class="folder-header" onclick="toggleFolder('${esc(folder.id)}')">
          <svg class="folder-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M1 4a1 1 0 011-1h4l1.5 2H14a1 1 0 011 1v7a1 1 0 01-1 1H2a1 1 0 01-1-1V4z"/>
          </svg>
          <span class="folder-name">${esc(folder.name)}</span>
          <button class="folder-new-chat-btn" title="New chat in ${esc(folder.name)}"
            onclick="event.stopPropagation(); startNewChat('${esc(folder.id)}')">
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.75">
              <path d="M8 3v10M3 8h10"/>
            </svg>
          </button>
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
    if (state.folders.length) {
      html += `<div class="uncategorized-label">Uncategorized</div>`;
    }
    html += uncategorized.map(c => convItemHtml(c)).join('');
  }

  nav.innerHTML = html;
}

function convItemHtml(conv) {
  const active = conv.id === state.conversationId ? ' active' : '';
  const title = esc(conv.title || 'Untitled');
  const folderId = conv.folder_id ? esc(conv.folder_id) : '';
  return `
    <div class="conv-item${active}" data-conv-id="${esc(conv.id)}"
      draggable="true"
      ondragstart="handleDragStart(event,'${esc(conv.id)}')"
      onclick="switchConversation('${esc(conv.id)}')">
      <span class="conv-title" title="${title}">${title}</span>
      <button class="conv-menu-btn" title="Move to folder"
        onclick="event.stopPropagation(); openConvMenu(event, '${esc(conv.id)}', '${folderId}')">⋯</button>
    </div>`;
}

function toggleFolder(folderId) {
  const section = document.querySelector(`.folder-section[data-folder-id="${folderId}"]`);
  if (section) section.classList.toggle('collapsed');
}

// ── Conversation Switching ─────────────────────────────────
async function switchConversation(convId) {
  if (convId === state.conversationId) return;
  state.conversationId = convId;
  state.targetFolderId = null;
  persistConvId(convId);
  renderSidebar();

  const msgs = document.getElementById('messages');
  msgs.innerHTML = '';

  try {
    const conv = await apiFetch(`/conversations/${convId}`);
    if (!conv.messages.length) {
      showWelcome();
      return;
    }
    for (const m of conv.messages) {
      appendStoredMessage(m.role, m.content);
    }
  } catch (e) {
    console.error('Failed to load conversation:', e);
    showWelcome();
  }
}

function appendStoredMessage(role, content) {
  hideWelcome();
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
  if (document.getElementById('welcome')) return;
  const msgs = document.getElementById('messages');
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

function startNewChat(folderId = null) {
  state.conversationId = null;
  state.targetFolderId = folderId;
  persistConvId(null);
  renderSidebar();
  const msgs = document.getElementById('messages');
  msgs.innerHTML = '';
  showWelcome();
  document.getElementById('chatInput').focus();
}

// ── Ingest Panel Toggle ────────────────────────────────────
function initIngestPanel() {
  document.getElementById('ingestToggle').addEventListener('click', () => {
    const panel = document.getElementById('ingestPanel');
    const body = document.getElementById('ingestBody');
    const isOpen = panel.classList.toggle('open');
    body.style.display = isOpen ? 'block' : 'none';
  });
}

// ── Folder Creation ────────────────────────────────────────
function initNewFolder() {
  const btn = document.getElementById('newFolderBtn');
  const wrap = document.getElementById('newFolderWrap');
  const input = document.getElementById('newFolderInput');

  btn.addEventListener('click', () => {
    const isVisible = wrap.style.display !== 'none';
    wrap.style.display = isVisible ? 'none' : 'block';
    if (!isVisible) {
      input.value = '';
      input.focus();
    }
  });

  input.addEventListener('keydown', async (e) => {
    if (e.key === 'Enter') {
      const name = input.value.trim();
      if (!name) return;
      try {
        await apiFetch('/folders', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name }),
        });
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

// ── Context Menu ───────────────────────────────────────────
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
    await apiFetch(`/conversations/${convId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder_id: folderId || null }),
    });
    await loadSidebar();
  } catch (e) {
    console.error('Move conversation failed:', e);
  }
}

// ── Drag and Drop ─────────────────────────────────────────
let _draggedConvId = null;

function handleDragStart(e, convId) {
  _draggedConvId = convId;
  e.dataTransfer.effectAllowed = 'move';
}

function handleFolderDragOver(e, folderId) {
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
  document.querySelector(`.folder-section[data-folder-id="${folderId}"]`)?.classList.add('drag-target');
}

function handleFolderDragLeave(e, folderId) {
  const section = document.querySelector(`.folder-section[data-folder-id="${folderId}"]`);
  if (section && !section.contains(e.relatedTarget)) {
    section.classList.remove('drag-target');
  }
}

async function handleFolderDrop(e, folderId) {
  e.preventDefault();
  document.querySelector(`.folder-section[data-folder-id="${folderId}"]`)?.classList.remove('drag-target');
  if (!_draggedConvId) return;
  const convId = _draggedConvId;
  _draggedConvId = null;
  try {
    await apiFetch(`/conversations/${convId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder_id: folderId }),
    });
    await loadSidebar();
  } catch (err) {
    console.error('Drop move failed:', err);
  }
}

// ── Chat ───────────────────────────────────────────────────
const GEM_SVG = `<svg class="avatar-gem" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
  <path d="M12 2L22 8V16L12 22L2 16V8L12 2Z"/>
  <path d="M12 2L12 22M2 8L22 8M2 16L22 16" stroke-width="0.6" opacity="0.35"/>
</svg>`;

function appendUserMessage(text) {
  hideWelcome();
  const msgs = document.getElementById('messages');
  const div = document.createElement('div');
  div.className = 'msg msg-user';
  div.innerHTML = `
    <div class="msg-avatar">you</div>
    <div class="msg-body">
      <div class="msg-content">${esc(text)}</div>
    </div>`;
  msgs.appendChild(div);
  scrollBottom();
}

let _streamEl = null;
let _rawBuffer = '';

function startAssistantMessage() {
  hideWelcome();
  const msgs = document.getElementById('messages');
  const div = document.createElement('div');
  div.className = 'msg msg-assistant';
  div.innerHTML = `
    <div class="msg-avatar">${GEM_SVG}</div>
    <div class="msg-body">
      <div class="msg-content" id="streamContent"><span class="cursor"></span></div>
    </div>`;
  msgs.appendChild(div);
  _streamEl = document.getElementById('streamContent');
  _rawBuffer = '';
  scrollBottom();
}

function appendToken(token) {
  if (!_streamEl) return;
  _rawBuffer += token;
  _streamEl.innerHTML = parseCitations(_rawBuffer) + '<span class="cursor"></span>';
  scrollBottom();
}

function finishAssistantMessage() {
  if (!_streamEl) return;
  _streamEl.innerHTML = parseCitations(_rawBuffer);
  _streamEl = null;
  _rawBuffer = '';
}

function hideWelcome() {
  const w = document.getElementById('welcome');
  if (w) w.remove();
}

function scrollBottom() {
  const msgs = document.getElementById('messages');
  msgs.scrollTop = msgs.scrollHeight;
}

// ── SSE Stream ─────────────────────────────────────────────
async function sendMessage() {
  const input = document.getElementById('chatInput');
  const query = input.value.trim();
  if (!query || state.isStreaming) return;

  input.value = '';
  input.style.height = 'auto';
  setSendDisabled(true);
  state.isStreaming = true;

  appendUserMessage(query);
  startAssistantMessage();

  const sources = [...state.activeSources];

  try {
    const res = await fetch('/api/v1/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query,
        conversation_id: state.conversationId || undefined,
        sources: sources.length < 3 ? sources : undefined,
      }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }

    state.conversationId = res.headers.get('X-Conversation-Id') || state.conversationId;
    persistConvId(state.conversationId);

    if (state.targetFolderId && state.conversationId) {
      const folderId = state.targetFolderId;
      state.targetFolderId = null;
      apiFetch(`/conversations/${state.conversationId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ folder_id: folderId }),
      }).catch(err => console.error('Failed to assign folder:', err));
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });

      const lines = buf.split('\n');
      buf = lines.pop();

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const token = line.slice(6);
        if (token.trimEnd() === '[DONE]') { finishAssistantMessage(); return; }
        if (token.trimEnd() === '[ERROR]') { appendToken('\n\n[Error generating response]'); finishAssistantMessage(); return; }
        appendToken(token);
      }
    }
    finishAssistantMessage();
  } catch (e) {
    appendToken(`\n\n[Error: ${e.message}]`);
    finishAssistantMessage();
  } finally {
    state.isStreaming = false;
    setSendDisabled(false);
    document.getElementById('chatInput').focus();
    await loadSidebar();
  }
}

function setSendDisabled(disabled) {
  document.getElementById('sendBtn').disabled = disabled;
}

// ── Tab Switching ──────────────────────────────────────────
function initTabs() {
  document.querySelectorAll('.tab').forEach(btn => {
    btn.addEventListener('click', () => {
      const tab = btn.dataset.tab;
      document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById(`pane-${tab}`).classList.add('active');
    });
  });
}

// ── Source Filter Chips ────────────────────────────────────
function initFilters() {
  document.querySelectorAll('.filter-chip').forEach(btn => {
    btn.addEventListener('click', () => {
      const src = btn.dataset.src;
      if (state.activeSources.has(src)) {
        if (state.activeSources.size === 1) return;
        state.activeSources.delete(src);
        btn.classList.remove('active');
      } else {
        state.activeSources.add(src);
        btn.classList.add('active');
      }
    });
  });
}

// ── Drop Zone ──────────────────────────────────────────────
function initDropZone() {
  const zone = document.getElementById('dropZone');
  const fileInput = document.getElementById('fileInput');

  zone.addEventListener('click', () => fileInput.click());

  zone.addEventListener('dragover', e => {
    e.preventDefault();
    zone.classList.add('drag-over');
  });

  zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));

  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('drag-over');
    const file = e.dataTransfer.files[0];
    if (file) ingestPdf(file);
  });

  fileInput.addEventListener('change', () => {
    if (fileInput.files[0]) ingestPdf(fileInput.files[0]);
    fileInput.value = '';
  });
}

// ── Chat Input ─────────────────────────────────────────────
function initChatInput() {
  const input = document.getElementById('chatInput');
  const sendBtn = document.getElementById('sendBtn');

  input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 160) + 'px';
  });

  input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  sendBtn.addEventListener('click', sendMessage);
}

// ── Init ───────────────────────────────────────────────────
function init() {
  initTabs();
  initFilters();
  initDropZone();
  initChatInput();
  initIngestPanel();
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

document.addEventListener('DOMContentLoaded', init);
