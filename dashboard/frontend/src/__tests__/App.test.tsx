import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { createElement } from 'react'
import App from '../App'
import * as client from '../api/client'

vi.mock('../api/client')

function renderApp() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    createElement(
      QueryClientProvider,
      { client: qc },
      <MemoryRouter initialEntries={['/app/inbox']}>
        <Routes>
          <Route path="/app/inbox" element={<App />} />
          <Route path="/app/inbox/:source" element={<App />} />
        </Routes>
      </MemoryRouter>,
    ),
  )
}

describe('App (inbox route)', () => {
  it('renders stats bar', async () => {
    vi.mocked(client.fetchCards).mockResolvedValueOnce({
      cards: [],
      counts: { pending: 0, held: 0, approved: 0, completed: 0, failed: 0 },
    } as any)

    renderApp()

    expect(screen.getByText('Needs Action')).toBeInTheDocument()
  })

  it('renders card list area', async () => {
    vi.mocked(client.fetchCards).mockResolvedValueOnce({
      cards: [],
      counts: { pending: 0, held: 0, approved: 0, completed: 0, failed: 0 },
    } as any)

    renderApp()

    // The card list will show loading or empty state
    expect(document.querySelector('[data-testid="card-list-loading"]') || screen.queryByText('No cards right now. All clear!')).toBeTruthy()
  })
})
