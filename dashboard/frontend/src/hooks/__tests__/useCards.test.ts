import { describe, it, expect, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createElement } from 'react'
import { useCards } from '../useCards'
import * as client from '../../api/client'

vi.mock('../../api/client')

function createWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children)
}

describe('useCards', () => {
  it('fetches cards for the given source', async () => {
    const mockData = {
      cards: [{ id: 1, source: 'gmail', summary: 'test', status: 'pending' }],
      counts: { pending: 1, held: 0, approved: 0, completed: 0, failed: 0 },
    }
    vi.mocked(client.fetchCards).mockResolvedValueOnce(mockData as any)

    const { result } = renderHook(() => useCards('gmail'), { wrapper: createWrapper() })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual(mockData)
    expect(client.fetchCards).toHaveBeenCalledWith('gmail')
  })

  it('uses "all" as default source', async () => {
    const mockData = { cards: [], counts: { pending: 0, held: 0, approved: 0, completed: 0, failed: 0 } }
    vi.mocked(client.fetchCards).mockResolvedValueOnce(mockData as any)

    const { result } = renderHook(() => useCards('all'), { wrapper: createWrapper() })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(client.fetchCards).toHaveBeenCalledWith('all')
  })
})
