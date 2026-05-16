import type { TokenResponse } from './types';

const LS_TOKEN = 'docchat_token';
const LS_REFRESH = 'docchat_refresh';

let _accessToken: string | null = localStorage.getItem(LS_TOKEN);
let _refreshToken: string | null = localStorage.getItem(LS_REFRESH);

export function setTokens(access: string, refresh?: string) {
  _accessToken = access;
  localStorage.setItem(LS_TOKEN, access);
  if (refresh) {
    _refreshToken = refresh;
    localStorage.setItem(LS_REFRESH, refresh);
  }
}

export function clearTokens() {
  _accessToken = null;
  _refreshToken = null;
  localStorage.removeItem(LS_TOKEN);
  localStorage.removeItem(LS_REFRESH);
}

export function hasToken(): boolean {
  return !!(_accessToken || localStorage.getItem(LS_TOKEN));
}

function authHeaders(): Record<string, string> {
  const token = _accessToken || localStorage.getItem(LS_TOKEN);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function tryRefresh(): Promise<boolean> {
  const rt = _refreshToken || localStorage.getItem(LS_REFRESH);
  if (!rt) return false;
  try {
    const r = await fetch('/api/v1/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: rt }),
    });
    if (!r.ok) return false;
    const d: TokenResponse = await r.json();
    setTokens(d.access_token);
    return true;
  } catch {
    return false;
  }
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
  stream: AsyncGenerator<string>;
}

export async function ssePost(path: string, body: unknown): Promise<SseResult> {
  const res = await apiFetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok || !res.body) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error((err as { detail?: string }).detail || res.statusText);
  }
  const conversationId = res.headers.get('X-Conversation-Id');

  async function* readStream(): AsyncGenerator<string> {
    const reader = res.body!.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop() ?? '';
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6);          // keep trailing space — it's the word separator
          const trimmed = data.trimEnd();
          if (trimmed === '[DONE]') return;
          if (trimmed === '[ERROR]') throw new Error('Stream error');
          yield data;
        }
      }
    }
  }

  return { conversationId, stream: readStream() };
}
