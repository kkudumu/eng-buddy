import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fetchCards, performCardAction, fetchInboxView } from '../client'

const mockFetch = vi.fn()
global.fetch = mockFetch

beforeEach(() => {
  mockFetch.mockReset()
})

describe('fetchCards', () => {
  it('fetches cards with no filter', async () => {
    const mockResponse = { cards: [], counts: { pending: 0, held: 0, approved: 0, completed: 0, failed: 0 } }
    mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mockResponse) })

    const result = await fetchCards()
    expect(mockFetch).toHaveBeenCalledWith('/api/cards?status=all')
    expect(result).toEqual(mockResponse)
  })

  it('fetches cards filtered by source', async () => {
    const mockResponse = { cards: [], counts: { pending: 0, held: 0, approved: 0, completed: 0, failed: 0 } }
    mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mockResponse) })

    const result = await fetchCards('gmail')
    expect(mockFetch).toHaveBeenCalledWith('/api/cards?source=gmail')
    expect(result).toEqual(mockResponse)
  })

  it('throws on non-ok response', async () => {
    mockFetch.mockResolvedValueOnce({ ok: false, status: 500, statusText: 'Internal Server Error' })

    await expect(fetchCards()).rejects.toThrow('500')
  })
})

describe('performCardAction', () => {
  it('posts action to correct endpoint', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ status: 'ok' }) })

    await performCardAction(42, 'send-slack', { message: 'hello' })
    expect(mockFetch).toHaveBeenCalledWith('/api/cards/42/send-slack', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: 'hello' }),
    })
  })
})

describe('fetchInboxView', () => {
  it('fetches inbox view with source and days', async () => {
    const mockResponse = { needs_action: [], no_action: [] }
    mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mockResponse) })

    const result = await fetchInboxView('gmail', 3)
    expect(mockFetch).toHaveBeenCalledWith('/api/inbox-view?source=gmail&days=3')
    expect(result).toEqual(mockResponse)
  })
})
