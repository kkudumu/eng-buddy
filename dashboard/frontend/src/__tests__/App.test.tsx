import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createElement } from 'react'
import App from '../App'
import * as client from '../api/client'

vi.mock('../api/client')
vi.stubGlobal('EventSource', vi.fn(function () {
  return {
    addEventListener: vi.fn(),
    close: vi.fn(),
    onopen: null,
    onerror: null,
  }
}))

function createWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children)
}

describe('App', () => {
  it('renders header with eng-buddy title', async () => {
    vi.mocked(client.fetchCards).mockResolvedValueOnce({
      cards: [],
      counts: { pending: 0, held: 0, approved: 0, completed: 0, failed: 0 },
    } as any)

    render(createElement(createWrapper(), null, createElement(App)))

    expect(screen.getByText('ENG-BUDDY')).toBeInTheDocument()
  })

  it('renders sidebar', async () => {
    vi.mocked(client.fetchCards).mockResolvedValueOnce({
      cards: [],
      counts: { pending: 0, held: 0, approved: 0, completed: 0, failed: 0 },
    } as any)

    render(createElement(createWrapper(), null, createElement(App)))

    expect(screen.getByText('All')).toBeInTheDocument()
    expect(screen.getByText('Gmail')).toBeInTheDocument()
  })
})
