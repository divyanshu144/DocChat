const state = {
  documentId: null,
  documentStatus: null,
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

function setStatus(el, message, type = "muted") {
  el.textContent = message;
  el.classList.remove("muted");
  if (type === "muted") {
    el.classList.add("muted");
  }
}

function appendMessage(role, content) {
  const message = document.createElement("div");
  message.className = `message ${role}`;
  message.textContent = content;
  chatWindow.appendChild(message);
  chatWindow.scrollTop = chatWindow.scrollHeight;
  return message;
}

async function checkHealth() {
  setStatus(healthStatus, "Checking...");
  try {
    const res = await fetch("/api/v1/health");
    if (!res.ok) throw new Error("Health check failed");
    const data = await res.json();
    setStatus(healthStatus, data.status === "ok" ? "Healthy" : data.status);
  } catch (err) {
    setStatus(healthStatus, "Offline", "error");
  }
}

/**
 * Poll GET /documents/{id} every 1.5 s until status is "ready" or "error".
 */
function pollDocumentStatus(docId) {
  return new Promise((resolve, reject) => {
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`/api/v1/documents/${docId}`);
        if (!res.ok) {
          clearInterval(interval);
          reject(new Error("Failed to fetch document status"));
          return;
        }
        const data = await res.json();
        documentStatus.textContent = data.status;
        documentChunks.textContent = data.chunk_count;

        if (data.status === "ready") {
          clearInterval(interval);
          resolve(data);
        } else if (data.status === "error") {
          clearInterval(interval);
          reject(new Error(data.error_message || "Ingestion failed"));
        }
      } catch (err) {
        clearInterval(interval);
        reject(err);
      }
    }, 1500);
  });
}

async function uploadDocument() {
  const file = fileInput.files[0];
  if (!file) {
    setStatus(uploadStatus, "Please choose a file first.");
    return;
  }

  uploadBtn.disabled = true;
  setStatus(uploadStatus, "Uploading...");

  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch("/api/v1/documents", {
      method: "POST",
      body: formData,
    });

    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || "Upload failed");
    }

    state.documentId = data.id;
    documentId.textContent = data.id;
    documentStatus.textContent = data.status;
    documentChunks.textContent = data.chunk_count;

    if (data.status === "ready") {
      // Ingestion completed synchronously (shouldn't happen with background tasks, but handle it)
      state.documentStatus = data.status;
      setStatus(uploadStatus, "Document processed.");
      createConversationBtn.disabled = false;
      setStatus(conversationStatus, "Document is ready. Create a conversation.");
    } else {
      // Background ingestion in progress — poll until done
      setStatus(uploadStatus, "Processing document...");
      const readyData = await pollDocumentStatus(data.id);
      state.documentStatus = readyData.status;
      setStatus(uploadStatus, "Document processed.");
      createConversationBtn.disabled = false;
      setStatus(conversationStatus, "Document is ready. Create a conversation.");
    }
  } catch (err) {
    setStatus(uploadStatus, err.message || "Upload failed.");
  } finally {
    uploadBtn.disabled = false;
  }
}

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
    if (!res.ok) {
      throw new Error(data.detail || "Conversation failed");
    }

    state.conversationId = data.id;
    conversationId.textContent = data.id;
    conversationId.classList.remove("muted");
    setStatus(conversationStatus, "Conversation ready.");
    sendBtn.disabled = false;
    chatStatus.textContent = "Ask your first question.";
  } catch (err) {
    setStatus(conversationStatus, err.message || "Conversation failed.");
    createConversationBtn.disabled = false;
  }
}

async function sendMessage() {
  const question = questionInput.value.trim();
  if (!question || !state.conversationId) return;

  sendBtn.disabled = true;
  questionInput.value = "";
  appendMessage("user", question);

  // Create a placeholder bubble for the streaming response
  const assistantEl = document.createElement("div");
  assistantEl.className = "message assistant";
  assistantEl.textContent = "";
  chatWindow.appendChild(assistantEl);
  setStatus(chatStatus, "Receiving response...");

  try {
    const res = await fetch(
      `/api/v1/conversations/${state.conversationId}/messages/stream`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      }
    );

    if (!res.ok) {
      const data = await res.json();
      throw new Error(data.detail || "Chat failed");
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let done = false;

    while (!done) {
      const { done: streamDone, value } = await reader.read();
      if (streamDone) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop(); // keep any incomplete line

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const token = line.slice(6);
        if (token === "[DONE]") {
          done = true;
          break;
        } else if (token === "[ERROR]") {
          assistantEl.textContent += " [Error generating response]";
          done = true;
          break;
        } else {
          assistantEl.textContent += token;
          chatWindow.scrollTop = chatWindow.scrollHeight;
        }
      }
    }

    setStatus(chatStatus, "Ask another question.");
  } catch (err) {
    assistantEl.textContent = assistantEl.textContent || "Sorry, I could not get a response.";
    setStatus(chatStatus, err.message || "Chat failed.");
  } finally {
    sendBtn.disabled = false;
  }
}

healthBtn.addEventListener("click", checkHealth);
uploadBtn.addEventListener("click", uploadDocument);
createConversationBtn.addEventListener("click", createConversation);
sendBtn.addEventListener("click", sendMessage);
questionInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    sendMessage();
  }
});

checkHealth();
