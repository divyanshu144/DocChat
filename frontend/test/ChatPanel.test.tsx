import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  apiFetch: vi.fn(),
  ssePost: vi.fn(),
}));

vi.mock('../src/api', () => ({
  apiFetch: mocks.apiFetch,
  ssePost: mocks.ssePost,
}));

import ChatPanel from '../src/components/ChatPanel';

async function* emptyStream() {
  yield { type: 'status' as const, data: 'Done' };
}

describe('ChatPanel', () => {
  afterEach(cleanup);

  it('sends active source filters and selected source ids', async () => {
    mocks.ssePost.mockResolvedValue({ conversationId: 'conv-1', stream: emptyStream() });
    const onConvCreated = vi.fn();

    render(
      <ChatPanel
        conversationId={null}
        onConvCreated={onConvCreated}
        selectedSourceIds={new Set(['src-1', 'src-2'])}
        onOpenSources={vi.fn()}
        selectedSourceCount={2}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /YouTube/i }));
    fireEvent.change(screen.getByPlaceholderText(/Ask anything/i), { target: { value: 'Compare sources' } });
    fireEvent.click(screen.getByTitle(/Send/i));

    await waitFor(() => expect(mocks.ssePost).toHaveBeenCalled());
    expect(mocks.ssePost).toHaveBeenCalledWith('/chat', {
      query: 'Compare sources',
      conversation_id: null,
      sources: ['pdf', 'web'],
      source_ids: ['src-1', 'src-2'],
    }, expect.any(AbortSignal));
    expect(onConvCreated).toHaveBeenCalledWith('conv-1');
  });

  it('cancels an in-flight answer when the user switches conversation, and shows no error for it', async () => {
    let signal: AbortSignal | undefined;
    mocks.apiFetch.mockResolvedValue({ ok: true, json: async () => ({ messages: [] }) });
    mocks.ssePost.mockImplementation(async (_path: string, _body: unknown, s?: AbortSignal) => {
      signal = s;
      async function* hang() {
        yield { type: 'token' as const, data: 'partial ' };
        await new Promise((_, reject) => s?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError'))));
      }
      return { conversationId: 'conv-a', stream: hang() };
    });
    const props = { onConvCreated: vi.fn(), selectedSourceIds: new Set<string>(), onOpenSources: vi.fn(), selectedSourceCount: 0 };
    const { rerender } = render(<ChatPanel conversationId="conv-a" {...props} />);

    fireEvent.change(screen.getByPlaceholderText(/Ask anything/i), { target: { value: 'hello' } });
    fireEvent.click(screen.getByTitle(/Send/i));
    await waitFor(() => expect(signal).toBeDefined());
    expect(signal!.aborted).toBe(false);

    rerender(<ChatPanel conversationId="conv-b" {...props} />);

    await waitFor(() => expect(signal!.aborted).toBe(true));
    await waitFor(() => expect(screen.getByPlaceholderText(/Ask anything/i)).not.toBeDisabled());
    expect(screen.queryByText(/Error:/)).toBeNull();
    expect(screen.queryByText(/partial/)).toBeNull();
  });
});
