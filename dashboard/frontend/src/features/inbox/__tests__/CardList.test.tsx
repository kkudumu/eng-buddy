import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createElement } from 'react'
import { CardList } from '../CardList'
import * as client from '../../../api/client'
import { useUIStore } from '../../../stores/ui'

vi.mock('../../../api/client')

function createWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children)
}

describe('CardList', () => {
  it('renders cards from API', async () => {
    useUIStore.setState({ activeSource: 'all' })
    vi.mocked(client.fetchCards).mockResolvedValueOnce({
      cards: [
        { id: 1, source: 'gmail', summary: 'Budget review', status: 'pending', classification: 'high', section: '', context_notes: '', timestamp: '2026-03-10T09:00:00Z', proposed_actions: [] },
        { id: 2, source: 'slack', summary: 'Deploy question', status: 'pending', classification: 'low', section: '', context_notes: '', timestamp: '2026-03-10T10:00:00Z', proposed_actions: [] },
      ],
      counts: { pending: 2, held: 0, approved: 0, completed: 0, failed: 0 },
    } as any)

    render(createElement(createWrapper(), null, createElement(CardList)))

    expect(await screen.findByText(/Budget review/)).toBeInTheDocument()
    expect(await screen.findByText(/Deploy question/)).toBeInTheDocument()
  })

  it('shows loading skeleton when fetching', () => {
    useUIStore.setState({ activeSource: 'all' })
    vi.mocked(client.fetchCards).mockReturnValueOnce(new Promise(() => {}))

    render(createElement(createWrapper(), null, createElement(CardList)))

    expect(screen.getByTestId('card-list-loading')).toBeInTheDocument()
  })
})
