import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

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
    });
    expect(onConvCreated).toHaveBeenCalledWith('conv-1');
  });
});
