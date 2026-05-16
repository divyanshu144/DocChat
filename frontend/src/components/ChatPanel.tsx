import { useCallback, useEffect, useRef, useState } from 'react';
import { apiFetch, ssePost } from '../api';
import type { SourceFilter } from '../types';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
}

interface Props {
  conversationId: string | null;
  onConvCreated: (id: string) => void;
  selectedSourceIds: Set<string>;
}

function parseCitations(text: string): string {
  return text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\[PDF\s*[—–-]\s*([^\]]+?)\]/gi,
      (_, inner: string) => `<span class="cite cite-pdf">${inner.trim()}</span>`)
    .replace(/\[YouTube\s*[—–-]\s*([^\]]+?)\]/gi,
      (_, inner: string) => `<span class="cite cite-yt">${inner.trim()}</span>`)
    .replace(/\[Web\s*[—–-]\s*([^\]]+?)\]/gi,
      (_, inner: string) => `<span class="cite cite-web">${inner.trim()}</span>`);
}

export default function ChatPanel({ conversationId, onConvCreated, selectedSourceIds }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [streamText, setStreamText] = useState('');
  const [activeFilters, setActiveFilters] = useState<Set<SourceFilter>>(new Set(['pdf', 'youtube', 'web']));
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  // Prevents useEffect from loading history when we just created this conversation mid-stream
  const skipNextLoad = useRef(false);

  useEffect(() => {
    if (!conversationId) { setMessages([]); return; }
    if (skipNextLoad.current) { skipNextLoad.current = false; return; }
    loadHistory(conversationId);
  }, [conversationId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamText]);

  async function loadHistory(id: string) {
    try {
      const res = await apiFetch(`/conversations/${id}`);
      if (res.ok) {
        const data = await res.json() as { messages: Message[] };
        setMessages((data.messages ?? []).map((m, i) => ({ ...m, id: m.id ?? String(i) })));
      }
    } catch { /* silent */ }
  }

  function toggleFilter(f: SourceFilter) {
    setActiveFilters(prev => {
      const next = new Set(prev);
      next.has(f) ? next.delete(f) : next.add(f);
      return next;
    });
  }

  const autoResize = useCallback(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 160) + 'px';
  }, []);

  async function sendMessage() {
    const text = input.trim();
    if (!text || streaming) return;
    setInput('');
    if (textareaRef.current) textareaRef.current.style.height = 'auto';

    setMessages(prev => [...prev, {
      id: crypto.randomUUID(),
      role: 'user',
      content: text,
      created_at: new Date().toISOString(),
    }]);
    setStreaming(true);
    setStreamText('');

    let finalConvId = conversationId;

    try {
      const { conversationId: newConvId, stream } = await ssePost('/chat', {
        query: text,
        conversation_id: conversationId,
        sources: Array.from(activeFilters),
        source_ids: selectedSourceIds.size > 0 ? Array.from(selectedSourceIds) : undefined,
      });

      if (newConvId && !conversationId) {
        // Mark that the upcoming conversationId change should NOT trigger loadHistory —
        // we're still streaming; we'll reload from DB after the stream finishes.
        skipNextLoad.current = true;
        finalConvId = newConvId;
        onConvCreated(newConvId);
      }

      let fullText = '';
      for await (const chunk of stream) {
        fullText += chunk;
        setStreamText(fullText);
      }

      // Stream succeeded — reload from DB (authoritative, properly formatted)
      if (finalConvId) await loadHistory(finalConvId);

    } catch (err) {
      setMessages(prev => [...prev, {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: `Error: ${err instanceof Error ? err.message : 'Unknown error'}`,
        created_at: new Date().toISOString(),
      }]);
    } finally {
      setStreaming(false);
      setStreamText('');
    }
  }

  const showWelcome = messages.length === 0 && !streaming;

  return (
    <main className="chat-panel">
      <div className="messages">
        {showWelcome && (
          <div className="welcome">
            <svg className="welcome-gem" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M12 2L22 8V16L12 22L2 16V8L12 2Z" stroke="currentColor" strokeWidth="1.25" fill="none"/>
              <path d="M12 2L12 22M2 8L22 8M2 16L22 16" stroke="currentColor" strokeWidth="0.6" opacity="0.35"/>
            </svg>
            <h1 className="welcome-title">Research Assistant</h1>
            <p className="welcome-sub">Ingest documents, videos, or web pages — then ask anything.</p>
            <div className="welcome-hints">
              <span className="hint-chip">Explain multi-head attention</span>
              <span className="hint-chip">Summarise key findings</span>
              <span className="hint-chip">Compare sources</span>
            </div>
          </div>
        )}

        {messages.map(msg => (
          <div key={msg.id} className={`msg msg-${msg.role}`}>
            <div className="msg-avatar">
              {msg.role === 'user'
                ? 'U'
                : (
                  <svg className="avatar-gem" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M12 2L22 8V16L12 22L2 16V8L12 2Z" stroke="currentColor" strokeWidth="1.5" fill="none"/>
                  </svg>
                )
              }
            </div>
            <div className="msg-body">
              <div
                className="msg-content"
                dangerouslySetInnerHTML={{ __html: parseCitations(msg.content) }}
              />
            </div>
          </div>
        ))}

        {streaming && (
          <div className="msg msg-assistant">
            <div className="msg-avatar">
              <svg className="avatar-gem" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M12 2L22 8V16L12 22L2 16V8L12 2Z" stroke="currentColor" strokeWidth="1.5" fill="none"/>
              </svg>
            </div>
            <div className="msg-body">
              <div
                className="msg-content"
                dangerouslySetInnerHTML={{ __html: parseCitations(streamText) + '<span class="cursor"></span>' }}
              />
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <footer className="chat-footer">
        <div className="filter-row">
          <span className="filter-label">Search:</span>
          {(['pdf', 'youtube', 'web'] as const).map(f => (
            <button
              key={f}
              className={`filter-chip ${activeFilters.has(f) ? 'active' : ''}`}
              onClick={() => toggleFilter(f)}
            >
              <span className={`chip-dot chip-${f === 'youtube' ? 'yt' : f}`}></span>
              {f === 'youtube' ? 'YouTube' : f === 'pdf' ? 'PDF' : 'Web'}
            </button>
          ))}
        </div>
        <div className="input-row">
          <textarea
            ref={textareaRef}
            className="chat-input"
            placeholder="Ask anything about your sources…"
            rows={1}
            value={input}
            onChange={e => { setInput(e.target.value); autoResize(); }}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
            }}
            disabled={streaming}
          />
          <button
            className="send-btn"
            onClick={sendMessage}
            disabled={streaming || !input.trim()}
            title="Send (Enter)"
          >
            <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.75">
              <path d="M3 10h14M11 4l6 6-6 6"/>
            </svg>
          </button>
        </div>
      </footer>
    </main>
  );
}
