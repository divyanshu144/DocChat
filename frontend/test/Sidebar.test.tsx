import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  apiJson: vi.fn(),
  apiFetch: vi.fn(),
}));

vi.mock('../src/api', () => ({
  apiJson: mocks.apiJson,
  apiFetch: mocks.apiFetch,
}));

import Sidebar from '../src/components/Sidebar';

describe('Sidebar', () => {
  it('moves a conversation to a folder from the context menu', async () => {
    mocks.apiJson.mockImplementation(async (path: string, options?: RequestInit) => {
      if (path === '/folders') return [{ id: 'folder-1', name: 'Research', created_at: '2026-07-30T00:00:00Z' }];
      if (path === '/conversations') return [{
        id: 'conv-1',
        title: 'Paper notes',
        folder_id: null,
        created_at: '2026-07-30T00:00:00Z',
        updated_at: '2026-07-30T00:00:00Z',
      }];
      if (path === '/conversations/conv-1' && options?.method === 'PATCH') {
        return { id: 'conv-1', title: 'Paper notes', folder_id: 'folder-1' };
      }
      return null;
    });

    render(
      <Sidebar
        activeConvId={null}
        onSelectConv={vi.fn()}
        onNewChat={vi.fn()}
        onLogout={vi.fn()}
        onConvDeleted={vi.fn()}
        email="user@example.com"
        health="ok"
        refreshTrigger={0}
      />,
    );

    await screen.findByText('Paper notes');
    fireEvent.click(screen.getByText('⋯'));
    fireEvent.click(screen.getByRole('button', { name: 'Research' }));

    await waitFor(() => {
      expect(mocks.apiJson).toHaveBeenCalledWith('/conversations/conv-1', {
        method: 'PATCH',
        body: JSON.stringify({ folder_id: 'folder-1' }),
      });
    });
  });
});
