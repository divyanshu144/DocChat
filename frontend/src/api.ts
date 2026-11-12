import type { TokenResponse } from './types';

const LS_TOKEN = 'docchat_token';
const LS_REFRESH = 'docchat_refresh';

// localStorage is the source of truth: several tabs share one session, and a refresh token is single-use on
// the server (replaying a rotated one revokes every session). A per-tab in-memory copy would go stale as soon
// as another tab rotated, so reads always go to storage and `_memory` is only the fallback when storage is
// unavailable (private mode, quota).
const _memory: { access: string | null; refresh: string | null } = {
  access: localStorage.getItem(LS_TOKEN),
  refresh: localStorage.getItem(LS_REFRESH),
};
let refreshPromise: Promise<boolean> | null = null;

function readAccess(): string | null {
  return localStorage.getItem(LS_TOKEN) ?? _memory.access;
}

function readRefresh(): string | null {
  return localStorage.getItem(LS_REFRESH) ?? _memory.refresh;
}

export function setTokens(access: string, refresh?: string) {
  _memory.access = access;
  localStorage.setItem(LS_TOKEN, access);
  if (refresh) {
    _memory.refresh = refresh;
    localStorage.setItem(LS_REFRESH, refresh);
  }
}

export function clearTokens() {
  _memory.access = null;
  _memory.refresh = null;
  localStorage.removeItem(LS_TOKEN);
  localStorage.removeItem(LS_REFRESH);
}

export function hasToken(): boolean {
  return !!readAccess();
}

function authHeaders(): Record<string, string> {
  const token = readAccess();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function tryRefresh(): Promise<boolean> {
  if (refreshPromise) return refreshPromise;

  const rt = readRefresh();
  if (!rt) return false;

  refreshPromise = (async () => {
    try {
      const r = await fetch('/api/v1/auth/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: rt }),
      });
      if (!r.ok) {
        // Another tab may have rotated the token a moment before us; if storage now holds a different
        // refresh token, the session is alive and the caller should simply retry with it.
        const current = readRefresh();
        return current !== null && current !== rt;
      }
      const d: TokenResponse = await r.json();
      setTokens(d.access_token, d.refresh_token);
      return true;
    } catch {
      return false;
    } finally {
      refreshPromise = null;
    }
  })();

  return refreshPromise;
}

export async function apiFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const headers = { ...authHeaders(), ...(options.headers as Record<string, string> || {}) };
  const res = await fetch(`/api/v1${path}`, { ...options, headers });
  if (res.status === 401) {
    if (await tryRefresh()) {
      const retryHeaders = { ...authHeaders(), ...(options.headers as Record<string, string> || {}) };
      return fetch(`/api/v1${path}`, { ...options, headers: retryHeaders });
    }
    clearTokens();
    window.location.reload();
  }
  return res;
}

export async function apiJson<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await apiFetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers as Record<string, string> || {}) },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  return res.json() as Promise<T>;
}

export interface SseResult {
  conversationId: string | null;
  stream: AsyncGenerator<SseEvent>;
}

export type SseEvent =
  | { type: 'status'; data: string }
  | { type: 'token'; data: string };

export async function ssePost(path: string, body: unknown, signal?: AbortSignal): Promise<SseResult> {
  const res = await apiFetch(path, {
    method: 'POST',
    signal,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok || !res.body) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  const conversationId = res.headers.get('X-Conversation-Id');

  async function* readStream(): AsyncGenerator<SseEvent> {
    const reader = res.body!.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    let eventType = 'token';
    // A token's own newlines are now sent as multiple consecutive "data: "
    // lines (per the SSE spec), one per line of the value — accumulate them
    // here and only join + yield once the blank-line event terminator is
    // seen, instead of treating every "data: " line as its own event.
    let dataLines: string[] = [];
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop() ?? '';
      for (const line of lines) {
        if (line.startsWith('event: ')) {
          eventType = line.slice(7).trim();
          continue;
        }
        if (line.startsWith('data: ')) {
          dataLines.push(line.slice(6));
          continue;
        }
        if (line === '') {
          if (dataLines.length === 0) continue;
          const data = dataLines.join('\n'); // keep trailing/internal whitespace — it's real content
          dataLines = [];
          const trimmed = data.trimEnd();
          if (trimmed === '[DONE]') return;
          if (eventType === 'error') throw new Error(trimmed || 'Stream error');
          if (trimmed === '[ERROR]') throw new Error('Stream error');
          if (eventType === 'status') {
            yield { type: 'status', data: trimmed };
          } else {
            yield { type: 'token', data };
          }
          eventType = 'token';
        }
      }
    }
  }

  return { conversationId, stream: readStream() };
}
