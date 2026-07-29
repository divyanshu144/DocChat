import { useEffect, useState } from 'react';
import { apiJson, clearTokens, hasToken } from './api';
import AuthScreen from './components/AuthScreen';
import Sidebar from './components/Sidebar';
import SourcesDrawer from './components/SourcesDrawer';
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
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [pendingFolderId, setPendingFolderId] = useState<string | null>(null);

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
    setPendingFolderId(null);
  }

  function selectConv(id: string) {
    setConvId(id);
    localStorage.setItem(LS_CONV, id);
    setPendingFolderId(null);
  }

  function newChat(folderId?: string) {
    setConvId(null);
    localStorage.removeItem(LS_CONV);
    setPendingFolderId(folderId ?? null);
  }

  function handleConvCreated(id: string) {
    setConvId(id);
    localStorage.setItem(LS_CONV, id);
    setSidebarRefresh(n => n + 1);
    if (pendingFolderId) {
      const folderId = pendingFolderId;
      setPendingFolderId(null);
      void apiJson(`/conversations/${id}`, {
        method: 'PATCH',
        body: JSON.stringify({ folder_id: folderId }),
      }).finally(() => setSidebarRefresh(n => n + 1));
    }
  }

  function handleConvDeleted(id: string) {
    if (convId === id) {
      setConvId(null);
      localStorage.removeItem(LS_CONV);
    }
    setPendingFolderId(null);
  }

  if (!authed) return <AuthScreen onAuth={handleAuth} />;

  return (
    <div className="app">
      <Sidebar
        activeConvId={convId}
        onSelectConv={selectConv}
        onNewChat={newChat}
        onLogout={handleLogout}
        onConvDeleted={handleConvDeleted}
        email={email}
        health={health}
        refreshTrigger={sidebarRefresh}
      />
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, position: 'relative', overflow: 'hidden' }}>
        <ChatPanel
          conversationId={convId}
          onConvCreated={handleConvCreated}
          selectedSourceIds={selectedSourceIds}
          onOpenSources={() => setDrawerOpen(true)}
          selectedSourceCount={selectedSourceIds.size}
        />
        <SourcesDrawer
          open={drawerOpen}
          onClose={() => setDrawerOpen(false)}
          selectedIds={selectedSourceIds}
          onSelectionChange={setSelectedSourceIds}
        />
      </div>
    </div>
  );
}
