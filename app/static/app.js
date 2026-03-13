const state = {
  documentId: null,
  documentStatus: null,
  documentFilename: null,
  conversationId: null,
};

const healthBtn = document.getElementById("healthBtn");
const healthStatus = document.getElementById("healthStatus");
const uploadBtn = document.getElementById("uploadBtn");
const fileInput = document.getElementById("fileInput");
const uploadStatus = document.getElementById("uploadStatus");
const documentId = document.getElementById("documentId");
const documentStatus = document.getElementById("documentStatus");
const documentChunks = document.getElementById("documentChunks");
const createConversationBtn = document.getElementById("createConversationBtn");
const conversationId = document.getElementById("conversationId");
const conversationStatus = document.getElementById("conversationStatus");
const questionInput = document.getElementById("questionInput");
const sendBtn = document.getElementById("sendBtn");
const chatWindow = document.getElementById("chatWindow");
const chatStatus = document.getElementById("chatStatus");
const downloadBtn = document.getElementById("downloadBtn");
const conversationsList = document.getElementById("conversationsList");
const conversationsEmpty = document.getElementById("conversationsEmpty");
const refreshConversationsBtn = document.getElementById("refreshConversationsBtn");

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function setStatus(el, message, type = "muted") {
  el.textContent = message;
  el.classList.remove("muted");
  if (type === "muted") el.classList.add("muted");
}

function appendMessage(role, content) {
  const message = document.createElement("div");
  message.className = `message ${role}`;
  message.textContent = content;
  chatWindow.appendChild(message);
  chatWindow.scrollTop = chatWindow.scrollHeight;
  return message;
}

function formatDate(iso) {
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------

async function checkHealth() {
  setStatus(healthStatus, "Checking...");
  try {
    const res = await fetch("/api/v1/health");
    if (!res.ok) throw new Error("Health check failed");
    const data = await res.json();
    setStatus(healthStatus, data.status === "ok" ? "Healthy" : data.status);
  } catch {
    setStatus(healthStatus, "Offline", "error");
  }
}

// ---------------------------------------------------------------------------
// Past conversations
// ---------------------------------------------------------------------------

async function loadConversations() {
  try {
    const res = await fetch("/api/v1/conversations");
    if (!res.ok) return;
    const conversations = await res.json();

    if (conversations.length === 0) {
      conversationsEmpty.style.display = "";
      return;
    }
    conversationsEmpty.style.display = "none";

    // Remove old items (keep the empty notice node)
    conversationsList.querySelectorAll(".conv-item").forEach(el => el.remove());

    for (const conv of conversations) {
      const item = document.createElement("div");
      item.className = "conv-item" + (conv.id === state.conversationId ? " active" : "");
      item.dataset.id = conv.id;
      item.innerHTML = `
        <div class="conv-meta">
          <span class="conv-filename">${conv.document_filename}</span>
          <span class="conv-detail">${formatDate(conv.created_at)}</span>
        </div>
        <span class="conv-badge">${conv.message_count} msg${conv.message_count !== 1 ? "s" : ""}</span>
      `;
      item.addEventListener("click", () => resumeConversation(conv));
      conversationsList.appendChild(item);
    }
  } catch {
    // silently ignore — list is non-critical
  }
}

async function resumeConversation(conv) {
  // Highlight the selected row
  conversationsList.querySelectorAll(".conv-item").forEach(el => {
    el.classList.toggle("active", el.dataset.id === conv.id);
  });

  // Load the full conversation (with messages)
  try {
    const res = await fetch(`/api/v1/conversations/${conv.id}`);
    if (!res.ok) throw new Error("Could not load conversation");
    const data = await res.json();

    state.conversationId = data.id;
    state.documentId = data.document_id;
    state.documentFilename = conv.document_filename;

    conversationId.textContent = data.id;
    conversationId.classList.remove("muted");
    setStatus(conversationStatus, `Resumed: ${conv.document_filename}`);

    chatWindow.innerHTML = "";
    const complete = (data.messages || []).filter(m => m.content);
    for (const m of complete) {
      appendMessage(m.role, m.content);
    }

    sendBtn.disabled = false;
    downloadBtn.disabled = false;
    chatStatus.textContent = complete.length
      ? "Ask another question."
      : "Ask your first question.";
  } catch (err) {
    setStatus(conversationStatus, err.message);
  }
}

// ---------------------------------------------------------------------------
// Document upload + polling
// ---------------------------------------------------------------------------

function pollDocumentStatus(docId) {
  return new Promise((resolve, reject) => {
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`/api/v1/documents/${docId}`);
        if (!res.ok) { clearInterval(interval); reject(new Error("Failed to fetch document status")); return; }
        const data = await res.json();
        documentStatus.textContent = data.status;
        documentChunks.textContent = data.chunk_count;
        if (data.status === "ready") { clearInterval(interval); resolve(data); }
        else if (data.status === "error") { clearInterval(interval); reject(new Error(data.error_message || "Ingestion failed")); }
      } catch (err) { clearInterval(interval); reject(err); }
    }, 1500);
  });
}

async function uploadDocument() {
  const file = fileInput.files[0];
  if (!file) { setStatus(uploadStatus, "Please choose a file first."); return; }

  uploadBtn.disabled = true;
  setStatus(uploadStatus, "Uploading...");

  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch("/api/v1/documents", { method: "POST", body: formData });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Upload failed");

    state.documentId = data.id;
    state.documentFilename = data.filename;
    documentId.textContent = data.id;
    documentStatus.textContent = data.status;
    documentChunks.textContent = data.chunk_count;

    if (data.status !== "ready") {
      setStatus(uploadStatus, "Processing document...");
      const ready = await pollDocumentStatus(data.id);
      state.documentStatus = ready.status;
    } else {
      state.documentStatus = data.status;
    }
    setStatus(uploadStatus, "Document processed.");
    createConversationBtn.disabled = false;
    setStatus(conversationStatus, "Document is ready. Create a conversation.");
  } catch (err) {
    setStatus(uploadStatus, err.message || "Upload failed.");
  } finally {
    uploadBtn.disabled = false;
  }
}

// ---------------------------------------------------------------------------
// Create conversation
// ---------------------------------------------------------------------------

async function createConversation() {
  if (!state.documentId) return;
  createConversationBtn.disabled = true;
  setStatus(conversationStatus, "Creating conversation...");

  try {
    const res = await fetch("/api/v1/conversations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ document_id: state.documentId }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Conversation failed");

    state.conversationId = data.id;
    conversationId.textContent = data.id;
    conversationId.classList.remove("muted");
    setStatus(conversationStatus, "Conversation ready.");
    sendBtn.disabled = false;
    downloadBtn.disabled = false;
    chatStatus.textContent = "Ask your first question.";
    chatWindow.innerHTML = "";

    await loadConversations();
  } catch (err) {
    setStatus(conversationStatus, err.message || "Conversation failed.");
    createConversationBtn.disabled = false;
  }
}

// ---------------------------------------------------------------------------
// Chat (streaming)
// ---------------------------------------------------------------------------

async function sendMessage() {
  const question = questionInput.value.trim();
  if (!question || !state.conversationId) return;

  sendBtn.disabled = true;
  questionInput.value = "";
  appendMessage("user", question);

  const assistantEl = document.createElement("div");
  assistantEl.className = "message assistant";
  assistantEl.textContent = "";
  chatWindow.appendChild(assistantEl);
  setStatus(chatStatus, "Receiving response...");

  try {
    const res = await fetch(
      `/api/v1/conversations/${state.conversationId}/messages/stream`,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question }) }
    );
    if (!res.ok) { const d = await res.json(); throw new Error(d.detail || "Chat failed"); }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "", done = false;

    while (!done) {
      const { done: streamDone, value } = await reader.read();
      if (streamDone) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop();
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const token = line.slice(6);
        if (token === "[DONE]") { done = true; break; }
        else if (token === "[ERROR]") { assistantEl.textContent += " [Error generating response]"; done = true; break; }
        else { assistantEl.textContent += token; chatWindow.scrollTop = chatWindow.scrollHeight; }
      }
    }
    setStatus(chatStatus, "Ask another question.");
    // Refresh conversation list so message count stays current
    loadConversations();
  } catch (err) {
    assistantEl.textContent = assistantEl.textContent || "Sorry, I could not get a response.";
    setStatus(chatStatus, err.message || "Chat failed.");
  } finally {
    sendBtn.disabled = false;
  }
}

// ---------------------------------------------------------------------------
// Download chat as Markdown
// ---------------------------------------------------------------------------

async function downloadChat() {
  if (!state.conversationId) return;

  try {
    const res = await fetch(`/api/v1/conversations/${state.conversationId}`);
    if (!res.ok) throw new Error("Could not fetch conversation");
    const data = await res.json();

    const filename = state.documentFilename || "document";
    const date = formatDate(data.created_at);
    const messages = (data.messages || []).filter(m => m.content);

    const lines = [
      `# Chat: ${filename}`,
      ``,
      `**Date:** ${date}  `,
      `**Conversation ID:** ${data.id}`,
      ``,
      `---`,
      ``,
    ];

    for (const m of messages) {
      if (m.role === "user") {
        lines.push(`**You:** ${m.content}`, ``);
      } else {
        lines.push(`**DocChat:** ${m.content}`, ``, `---`, ``);
      }
    }

    const blob = new Blob([lines.join("\n")], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `docchat-${filename.replace(/\.[^.]+$/, "")}-${data.id.slice(0, 8)}.md`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (err) {
    setStatus(chatStatus, err.message || "Download failed.");
  }
}

// ---------------------------------------------------------------------------
// Event listeners + init
// ---------------------------------------------------------------------------

healthBtn.addEventListener("click", checkHealth);
uploadBtn.addEventListener("click", uploadDocument);
createConversationBtn.addEventListener("click", createConversation);
sendBtn.addEventListener("click", sendMessage);
downloadBtn.addEventListener("click", downloadChat);
refreshConversationsBtn.addEventListener("click", loadConversations);
questionInput.addEventListener("keydown", e => { if (e.key === "Enter") sendMessage(); });

checkHealth();
loadConversations();
