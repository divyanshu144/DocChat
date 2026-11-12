import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const auth = vi.hoisted(() => ({ hasToken: vi.fn(() => true) }));

vi.mock('../src/api', () => ({
  apiFetch: vi.fn(async () => ({ ok: true, json: async () => ({ sources: [], conversations: [], folders: [] }) })),
  apiJson: vi.fn(async () => []),
  ssePost: vi.fn(),
  hasToken: auth.hasToken,
  clearTokens: vi.fn(),
}));
vi.mock('../src/components/Sidebar', () => ({
  default: (p: { onLogout: () => void }) => <button onClick={p.onLogout}>logout</button>,
}));
vi.mock('../src/components/AuthScreen', () => ({
  default: (p: { onAuth: (email: string) => void }) => <button onClick={() => p.onAuth('b@example.com')}>login-b</button>,
}));
vi.mock('../src/components/ChatPanel', () => ({
  default: (p: { selectedSourceCount: number; conversationId: string | null }) =>
    <div>count:{p.selectedSourceCount} conv:{p.conversationId ?? 'none'}</div>,
}));
vi.mock('../src/components/SourcesDrawer', () => ({
  default: (p: { onSelectionChange: (ids: Set<string>) => void }) => {
    return <button onClick={() => p.onSelectionChange(new Set(['src-1']))}>select</button>;
  },
}));

import App from '../src/App';

describe('App session state', () => {
  afterEach(cleanup);

  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 200 })));
  });

  it('clears the selected sources on logout so the next user is not filtered by foreign ids', async () => {
    localStorage.setItem('docchat_email', 'a@example.com');
    render(<App />);
    fireEvent.click(screen.getByText('select'));
    await waitFor(() => expect(screen.getByText(/count:1/)).toBeTruthy());

    fireEvent.click(screen.getByText('logout'));
    // Logged out: the auth screen shows. Log in again (as someone else) and check nothing carried over.
    fireEvent.click(await screen.findByText('login-b'));
    await waitFor(() => expect(screen.getByText(/count:0/)).toBeTruthy());
  });

  it("does not hand a different account the previous account's open conversation", async () => {
    localStorage.setItem('docchat_email', 'a@example.com');
    localStorage.setItem('docchat_conv_id', 'conv-of-a');
    auth.hasToken.mockReturnValue(false);  // expired session: the auth screen shows, the stored conversation remains
    try {
      render(<App />);
      fireEvent.click(await screen.findByText('login-b'));
      await waitFor(() => expect(screen.getByText(/conv:none/)).toBeTruthy());
      expect(localStorage.getItem('docchat_conv_id')).toBeNull();
    } finally {
      auth.hasToken.mockReturnValue(true);
    }
  });
});
