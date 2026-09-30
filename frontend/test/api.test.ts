import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

function jsonResponse(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json', ...(init.headers ?? {}) },
    ...init,
  });
}

describe('api client', () => {
  beforeEach(() => {
    vi.resetModules();
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('coalesces concurrent refresh attempts after parallel 401s', async () => {
    localStorage.setItem('docchat_token', 'expired-access');
    localStorage.setItem('docchat_refresh', 'refresh-a');

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/v1/auth/refresh') {
        return jsonResponse({ access_token: 'access-b', refresh_token: 'refresh-b', token_type: 'bearer' });
      }
      if (url === '/api/v1/folders' || url === '/api/v1/conversations') {
        const authed = init?.headers as Record<string, string> | undefined;
        if (authed?.Authorization === 'Bearer access-b') return jsonResponse([]);
        return new Response('unauthorized', { status: 401 });
      }
      return new Response('not found', { status: 404 });
    });
    vi.stubGlobal('fetch', fetchMock);

    const { apiFetch } = await import('../src/api');
    const [folders, conversations] = await Promise.all([
      apiFetch('/folders'),
      apiFetch('/conversations'),
    ]);

    expect(folders.status).toBe(200);
    expect(conversations.status).toBe(200);
    expect(fetchMock.mock.calls.filter(call => call[0] === '/api/v1/auth/refresh')).toHaveLength(1);
    expect(localStorage.getItem('docchat_refresh')).toBe('refresh-b');
  });

  it('parses SSE status and token events', async () => {
    localStorage.setItem('docchat_token', 'access');
    const encoder = new TextEncoder();
    const body = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode('event: status\ndata: Planning\n\n'));
        controller.enqueue(encoder.encode('event: token\ndata: Hello \n\n'));
        controller.enqueue(encoder.encode('event: token\ndata: world\n\n'));
        controller.enqueue(encoder.encode('event: done\ndata: [DONE]\n\n'));
        controller.close();
      },
    });
    vi.stubGlobal('fetch', vi.fn(async () => new Response(body, {
      status: 200,
      headers: { 'X-Conversation-Id': 'conv-1' },
    })));

    const { ssePost } = await import('../src/api');
    const result = await ssePost('/chat', { query: 'hello' });
    const events = [];
    for await (const event of result.stream) events.push(event);

    expect(result.conversationId).toBe('conv-1');
    expect(events).toEqual([
      { type: 'status', data: 'Planning' },
      { type: 'token', data: 'Hello ' },
      { type: 'token', data: 'world' },
    ]);
  });
});
