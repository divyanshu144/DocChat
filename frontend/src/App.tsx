import { useEffect, useState } from 'react';
import { clearTokens, hasToken } from './api';
import AuthScreen from './components/AuthScreen';
import Sidebar from './components/Sidebar';
import IngestPanel from './components/IngestPanel';
import ChatPanel from './components/ChatPanel';

const LS_EMAIL = 'docchat_email';
const LS_CONV  = 'docchat_conv_id';

type Health = 'ok' | 'fail' | 'unknown';

export default function App() {
  const [authed, setAuthed] = useState(hasToken);
  const [email, setEmail] = useState(() => localStorage.getItem(LS_EMAIL) ?? '');
  const [convId, setConvId] = useState<string | null>(() => localStorage.getItem(LS_CONV));
  const [health, setHealth] = useState<Health>('unknown');
  const [sidebarRefresh, setSidebarRefresh] = useState(0);
  const [selectedSourceIds, setSelectedSourceIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    async function check() {
      try {
        const r = await fetch('/api/v1/health');
        if (!cancelled) setHealth(r.ok ? 'ok' : 'fail');
      } catch {
        if (!cancelled) setHealth('fail');
      }
    }
    check();
    const t = setInterval(check, 30_000);
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  function handleAuth(userEmail: string) {
    localStorage.setItem(LS_EMAIL, userEmail);
    setEmail(userEmail);
    setAuthed(true);
  }

  function handleLogout() {
    clearTokens();
    localStorage.removeItem(LS_EMAIL);
    localStorage.removeItem(LS_CONV);
    setAuthed(false);
    setEmail('');
    setConvId(null);
  }

  function selectConv(id: string) {
    setConvId(id);
    localStorage.setItem(LS_CONV, id);
  }

  function newChat(folderId?: string) {
    setConvId(null);
    localStorage.removeItem(LS_CONV);
    // If folderId provided, the next sent message will create conv then move it
    // For now just clear active conv; folder assignment happens after conv creation
    void folderId; // acknowledged, used in future enhancement
  }

  function handleConvCreated(id: string) {
    setConvId(id);
    localStorage.setItem(LS_CONV, id);
    setSidebarRefresh(n => n + 1);
  }

  if (!authed) return <AuthScreen onAuth={handleAuth} />;

  return (
    <div className="app">
      <Sidebar
        activeConvId={convId}
        onSelectConv={selectConv}
        onNewChat={newChat}
        onLogout={handleLogout}
        email={email}
        health={health}
        refreshTrigger={sidebarRefresh}
      />
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <IngestPanel
          selectedIds={selectedSourceIds}
          onSelectionChange={setSelectedSourceIds}
        />
        <ChatPanel
          conversationId={convId}
          onConvCreated={handleConvCreated}
          selectedSourceIds={selectedSourceIds}
        />
      </div>
    </div>
  );
}
