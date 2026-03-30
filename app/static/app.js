// ============================================================
// API client
// ============================================================

async function api(path, options = {}) {
  const res = await fetch(`/api/v1${path}`, options);
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// ============================================================
// Utilities
// ============================================================

function esc(str) {
  return String(str ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function formatDate(iso) {
  return new Date(iso).toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

function docIcon(ct) {
  if (ct === 'application/pdf') return '📕';
  if (ct?.includes('word')) return '📘';
  return '📄';
}

function scrollBottom(el) {
  if (el) el.scrollTop = el.scrollHeight;
}

// ============================================================
// Health check
// ============================================================

async function checkHealth() {
  const dot = document.getElementById('healthDot');
  const label = document.getElementById('healthLabel');
  try {
    await api('/health');
    dot.className = 'health-dot online';
    label.textContent = 'Online';
  } catch {
    dot.className = 'health-dot offline';
    label.textContent = 'Offline';
  }
}

// ============================================================
// Router
// ============================================================

function router() {
  const hash = location.hash || '#/documents';
  const [pathPart, queryPart] = (hash.startsWith('#') ? hash.slice(1) : hash).split('?');
  const params = Object.fromEntries(new URLSearchParams(queryPart || ''));
  const segments = (pathPart || '/').split('/').filter(Boolean);
  const view = segments[0] || 'documents';
  const id = segments[1];

  document.querySelectorAll('.nav-link').forEach(a => {
    a.classList.toggle('active', a.dataset.view === view);
  });

  const app = document.getElementById('app');

  // Fade out → swap content → fade in
  app.classList.add('view-leaving');
  setTimeout(() => {
    app.innerHTML = '';
    app.classList.remove('view-leaving');
    app.classList.add('view-entering');

    if (view === 'documents') renderDocuments(app, params);
    else if (view === 'conversations') renderConversations(app, params);
    else if (view === 'chat' && id) renderChat(app, id);
    else renderDocuments(app, params);

    requestAnimationFrame(() => {
      app.classList.remove('view-entering');
    });
  }, 120);
}

window.addEventListener('hashchange', router);

// ============================================================
// Documents view
// ============================================================

async function renderDocuments(container, params) {
  container.innerHTML = `
    <div class="view-page">
      <div class="view-header">
        <div class="view-title-block">
          <p class="view-eyebrow">Library</p>
          <h1 class="view-title">Documents</h1>
        </div>
        <button class="btn-primary" id="openUploadBtn">+ Upload</button>
      </div>
      <div id="docsGrid" class="docs-grid">
        <div class="skeleton-grid">
          ${Array(3).fill('<div class="skeleton-card"></div>').join('')}
        </div>
      </div>
    </div>
  `;

  document.getElementById('openUploadBtn').addEventListener('click', openUploadModal);

  try {
    const docs = await api('/documents');
    renderDocGrid(docs);
  } catch (err) {
    document.getElementById('docsGrid').innerHTML = `<p class="state-error">Failed to load: ${esc(err.message)}</p>`;
  }
}

function renderDocGrid(docs) {
  const grid = document.getElementById('docsGrid');
  if (!docs.length) {
    grid.innerHTML = `
      <div class="state-empty">
        <div class="state-icon">📂</div>
        <p class="state-title">No documents yet</p>
        <p class="state-sub">Upload a PDF, DOCX, or TXT to get started.</p>
        <button class="btn-primary" id="emptyUploadBtn">Upload document</button>
      </div>
    `;
    document.getElementById('emptyUploadBtn').addEventListener('click', openUploadModal);
    return;
  }

  grid.innerHTML = docs.map(doc => `
    <div class="doc-card doc-${esc(doc.status)}" data-id="${esc(doc.id)}" tabindex="0" role="button"
         aria-label="${esc(doc.filename)}" ${doc.status === 'ready' ? `onclick="location.hash='#/conversations?doc=${esc(doc.id)}'"` : ''}>
      <div class="doc-card-top">
        <span class="doc-type-icon">${docIcon(doc.content_type)}</span>
        <span class="status-pill status-${esc(doc.status)}">${esc(doc.status)}</span>
      </div>
      <div class="doc-name">${esc(doc.filename)}</div>
      <div class="doc-meta">
        <span>${doc.chunk_count} chunk${doc.chunk_count !== 1 ? 's' : ''}</span>
        <span>${formatDate(doc.created_at)}</span>
      </div>
      ${doc.status === 'ready' ? `<div class="doc-cta">Chat about this →</div>` : ''}
      ${doc.status === 'processing' ? `<div class="doc-processing-bar"><div class="doc-processing-fill"></div></div>` : ''}
      ${doc.status === 'error' ? `<div class="doc-error-msg">${esc(doc.error_message || 'Ingestion failed')}</div>` : ''}
    </div>
  `).join('');
}

// ============================================================
// Upload modal
// ============================================================

function openUploadModal() {
  const modal = document.getElementById('uploadModal');
  modal.hidden = false;
  document.getElementById('uploadProgress').hidden = true;
  document.getElementById('dropZone').hidden = false;
  document.getElementById('progressFill').style.width = '0%';
  document.getElementById('progressFill').style.background = '';
}

function closeUploadModal() {
  document.getElementById('uploadModal').hidden = true;
}

function initUploadModal() {
  document.getElementById('modalClose').addEventListener('click', closeUploadModal);
  document.getElementById('uploadModal').addEventListener('click', e => {
    if (e.target === e.currentTarget) closeUploadModal();
  });

  const dropZone = document.getElementById('dropZone');
  const fileInput = document.getElementById('fileInput');

  dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('drag-over'); });
  dropZone.addEventListener('dragleave', e => { if (!dropZone.contains(e.relatedTarget)) dropZone.classList.remove('drag-over'); });
  dropZone.addEventListener('drop', e => {
    e.preventDefault();
    dropZone.classList.remove('drag-over');
    const file = e.dataTransfer.files[0];
    if (file) handleUpload(file);
  });

  document.querySelector('.btn-upload-label').addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', () => {
    if (fileInput.files[0]) handleUpload(fileInput.files[0]);
    fileInput.value = '';
  });
}

async function handleUpload(file) {
  document.getElementById('dropZone').hidden = true;
  const progressEl = document.getElementById('uploadProgress');
  progressEl.hidden = false;

  document.getElementById('progressFilename').textContent = file.name;
  document.getElementById('progressState').textContent = 'Uploading…';
  document.getElementById('progressHint').textContent = '';
  setProgress(20);

  const formData = new FormData();
  formData.append('file', file);

  try {
    const doc = await api('/documents', { method: 'POST', body: formData });
    document.getElementById('progressState').textContent = 'Processing…';
    document.getElementById('progressHint').textContent = 'Extracting text and building search index…';
    setProgress(50);

    await pollDocument(doc.id, status => {
      if (status === 'processing') setProgress(75);
    });

    setProgress(100);
    document.getElementById('progressState').textContent = 'Ready!';
    document.getElementById('progressHint').textContent = 'Taking you to your conversation…';

    setTimeout(() => {
      closeUploadModal();
      location.hash = `#/conversations?doc=${doc.id}`;
    }, 900);
  } catch (err) {
    setProgress(100, true);
    document.getElementById('progressState').textContent = 'Failed';
    document.getElementById('progressHint').textContent = err.message;
  }
}

function setProgress(pct, error = false) {
  const fill = document.getElementById('progressFill');
  fill.style.width = `${pct}%`;
  fill.style.background = error ? 'var(--error)' : '';
}

function pollDocument(docId, onStatus) {
  return new Promise((resolve, reject) => {
    const iv = setInterval(async () => {
      try {
        const doc = await api(`/documents/${docId}`);
        onStatus(doc.status);
        if (doc.status === 'ready') { clearInterval(iv); resolve(doc); }
        else if (doc.status === 'error') { clearInterval(iv); reject(new Error(doc.error_message || 'Ingestion failed')); }
      } catch (err) { clearInterval(iv); reject(err); }
    }, 1500);
  });
}

// ============================================================
// Conversations view
// ============================================================

async function renderConversations(container, params) {
  const docId = params.doc || null;
  let docName = '';

  if (docId) {
    try {
      const doc = await api(`/documents/${docId}`);
      docName = doc.filename;
    } catch { /* non-critical */ }
  }

  container.innerHTML = `
    <div class="view-page">
      <div class="view-header">
        <div class="view-title-block">
          ${docName ? `<p class="view-eyebrow">${esc(docName)}</p>` : '<p class="view-eyebrow">History</p>'}
          <h1 class="view-title">Conversations</h1>
        </div>
        <div class="view-header-actions">
          ${docId ? `<button class="btn-primary" id="newConvBtn">+ New conversation</button>` : ''}
          <a class="btn-ghost" href="#/documents">← Documents</a>
        </div>
      </div>
      <div id="convList" class="conv-list">
        <div class="skeleton-list">
          ${Array(4).fill('<div class="skeleton-row"></div>').join('')}
        </div>
      </div>
    </div>
  `;

  if (docId) {
    document.getElementById('newConvBtn')?.addEventListener('click', () => startConversation(docId));
  }

  try {
    const convs = await api('/conversations');
    const filtered = docId ? convs.filter(c => c.document_id === docId) : convs;
    renderConvList(filtered, docId);
  } catch (err) {
    document.getElementById('convList').innerHTML = `<p class="state-error">Failed to load: ${esc(err.message)}</p>`;
  }
}

function renderConvList(convs, activeDocId) {
  const list = document.getElementById('convList');
  if (!convs.length) {
    list.innerHTML = `
      <div class="state-empty">
        <div class="state-icon">💬</div>
        <p class="state-title">No conversations yet</p>
        <p class="state-sub">${activeDocId ? 'Start a new conversation with this document.' : 'Upload a document to start chatting.'}</p>
      </div>
    `;
    return;
  }

  list.innerHTML = convs.map(conv => `
    <div class="conv-row" onclick="location.hash='#/chat/${esc(conv.id)}'" tabindex="0" role="button">
      <div class="conv-row-left">
        <div class="conv-row-icon">💬</div>
        <div class="conv-row-info">
          <div class="conv-row-doc">${esc(conv.document_filename)}</div>
          <div class="conv-row-date">${formatDate(conv.created_at)}</div>
        </div>
      </div>
      <span class="conv-badge">${conv.message_count} msg${conv.message_count !== 1 ? 's' : ''}</span>
    </div>
  `).join('');

  // keyboard support
  list.querySelectorAll('.conv-row').forEach(row => {
    row.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') row.click(); });
  });
}

async function startConversation(docId) {
  try {
    const conv = await api('/conversations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ document_id: docId }),
    });
    location.hash = `#/chat/${conv.id}`;
  } catch (err) {
    alert(`Could not start conversation: ${err.message}`);
  }
}

// ============================================================
// Chat view
// ============================================================

async function renderChat(container, convId) {
  container.innerHTML = `
    <div class="chat-loading">
      <div class="skeleton-sidebar"></div>
      <div class="chat-main-placeholder"></div>
    </div>
  `;

  try {
    const conv = await api(`/conversations/${convId}`);
    const doc = await api(`/documents/${conv.document_id}`).catch(() => ({
      filename: 'Unknown document', content_type: '', chunk_count: 0,
    }));

    container.innerHTML = `
      <div class="chat-layout">

        <aside class="chat-sidebar">
          <a class="back-link" href="#/conversations">← Back</a>

          <div class="sidebar-doc-card">
            <div class="sidebar-doc-icon">${docIcon(doc.content_type)}</div>
            <div class="sidebar-doc-name">${esc(doc.filename)}</div>
            <div class="sidebar-doc-meta">${doc.chunk_count} chunks</div>
          </div>

          <div class="sidebar-meta-rows">
            <div class="sidebar-meta-row">
              <span class="sidebar-meta-label">Conversation</span>
              <span class="sidebar-meta-val mono">${esc(convId.slice(0, 8))}…</span>
            </div>
            <div class="sidebar-meta-row">
              <span class="sidebar-meta-label">Started</span>
              <span class="sidebar-meta-val">${formatDate(conv.created_at)}</span>
            </div>
          </div>

          <button class="btn-ghost sidebar-download-btn" id="downloadBtn">↓ Download chat</button>
        </aside>

        <div class="chat-main">
          <div class="chat-messages" id="chatMessages">
            ${(conv.messages || []).filter(m => m.content).map(m => msgBubble(m.role, m.content)).join('')}
            ${!(conv.messages || []).filter(m => m.content).length
              ? `<div class="chat-welcome">
                  <div class="chat-welcome-icon">💬</div>
                  <p class="chat-welcome-title">Conversation started</p>
                  <p class="chat-welcome-sub">Ask anything about <strong>${esc(doc.filename)}</strong></p>
                </div>`
              : ''}
          </div>

          <div class="chat-input-row">
            <textarea class="chat-textarea" id="chatInput"
              placeholder="Ask about the document…" rows="1"
              aria-label="Your question"></textarea>
            <button class="btn-send" id="sendBtn" aria-label="Send">
              <span class="send-icon">↑</span>
            </button>
          </div>
        </div>

      </div>
    `;

    scrollBottom(document.getElementById('chatMessages'));
    setupChatInput(convId);

    document.getElementById('downloadBtn').addEventListener('click', () => downloadChat(conv, doc));

  } catch (err) {
    container.innerHTML = `
      <div class="view-page">
        <div class="state-error">
          Could not load conversation: ${esc(err.message)}
          <br><a href="#/conversations" class="link">← Go back</a>
        </div>
      </div>
    `;
  }
}

function msgBubble(role, content) {
  return `
    <div class="msg msg-${esc(role)}">
      <div class="msg-label">${role === 'user' ? 'You' : 'DocChat'}</div>
      <div class="msg-bubble">${esc(content)}</div>
    </div>
  `;
}

function setupChatInput(convId) {
  const input = document.getElementById('chatInput');
  const btn = document.getElementById('sendBtn');

  btn.addEventListener('click', () => sendMessage(convId));
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(convId); }
  });
  input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 160) + 'px';
  });

  input.focus();
}

async function sendMessage(convId) {
  const input = document.getElementById('chatInput');
  const btn = document.getElementById('sendBtn');
  const question = input.value.trim();
  if (!question || btn.disabled) return;

  input.value = '';
  input.style.height = 'auto';
  btn.disabled = true;

  const messages = document.getElementById('chatMessages');

  // Remove welcome screen if present
  messages.querySelector('.chat-welcome')?.remove();

  // User bubble
  messages.insertAdjacentHTML('beforeend', msgBubble('user', question));

  // Assistant bubble with typing indicator
  const aDiv = document.createElement('div');
  aDiv.className = 'msg msg-assistant';
  aDiv.innerHTML = `
    <div class="msg-label">DocChat</div>
    <div class="msg-bubble"><span class="typing-dots"><span></span><span></span><span></span></span></div>
  `;
  messages.appendChild(aDiv);
  scrollBottom(messages);

  const bubble = aDiv.querySelector('.msg-bubble');

  try {
    const res = await fetch(`/api/v1/conversations/${convId}/messages/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question }),
    });

    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      throw new Error(d.detail || 'Stream failed');
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '', fullText = '', done = false, started = false;

    while (!done) {
      const { done: sd, value } = await reader.read();
      if (sd) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const token = line.slice(6);
        if (token === '[DONE]') { done = true; break; }
        if (token === '[ERROR]') {
          bubble.textContent = 'Sorry, something went wrong generating the response.';
          done = true; break;
        }
        if (!started) { bubble.textContent = ''; started = true; }
        fullText += token;
        bubble.textContent = fullText;
        scrollBottom(messages);
      }
    }

    if (!started) bubble.textContent = '(No response)';
  } catch (err) {
    bubble.textContent = `Error: ${err.message}`;
  } finally {
    btn.disabled = false;
    input.focus();
    scrollBottom(messages);
  }
}

async function downloadChat(conv, doc) {
  try {
    const full = await api(`/conversations/${conv.id}`);
    const msgs = (full.messages || []).filter(m => m.content);
    const lines = [
      `# Chat: ${doc.filename}`,
      ``,
      `**Date:** ${formatDate(conv.created_at)}`,
      `**Conversation ID:** ${conv.id}`,
      ``,
      `---`,
      ``,
    ];
    for (const m of msgs) {
      if (m.role === 'user') lines.push(`**You:** ${m.content}`, ``);
      else lines.push(`**DocChat:** ${m.content}`, ``, `---`, ``);
    }
    const blob = new Blob([lines.join('\n')], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `docchat-${doc.filename.replace(/\.[^.]+$/, '')}-${conv.id.slice(0, 8)}.md`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (err) {
    alert(`Download failed: ${err.message}`);
  }
}

// ============================================================
// Init
// ============================================================

window.addEventListener('hashchange', router);
document.addEventListener('DOMContentLoaded', () => {
  try { initUploadModal(); } catch (e) { console.warn('modal init skipped:', e); }
  if (!location.hash || location.hash === '#') location.hash = '#/documents';
  router();
  checkHealth();
  setInterval(checkHealth, 30000);
});
