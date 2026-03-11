import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fetchPlaybookDetail, updatePlaybookDraft, promotePlaybook, deletePlaybookDraft, fetchPlaybookHistory } from '../client'

const mockFetch = vi.fn()
global.fetch = mockFetch

beforeEach(() => mockFetch.mockReset())

describe('Wave 4 playbook client', () => {
  it('fetchPlaybookDetail calls GET /api/playbooks/:id', async () => {
    const mock = { id: 'abc', name: 'Test', steps: [] }
    mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mock) })
    const result = await fetchPlaybookDetail('abc')
    expect(mockFetch).toHaveBeenCalledWith('/api/playbooks/abc')
    expect(result.id).toBe('abc')
  })

  it('updatePlaybookDraft PATCHes /api/playbooks/drafts/:id', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ status: 'ok' }) })
    await updatePlaybookDraft('abc', { steps: [] })
    expect(mockFetch).toHaveBeenCalledWith('/api/playbooks/drafts/abc', expect.objectContaining({ method: 'PATCH' }))
  })

  it('promotePlaybook POSTs /api/playbooks/:id/promote', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ status: 'ok' }) })
    await promotePlaybook('abc')
    expect(mockFetch).toHaveBeenCalledWith('/api/playbooks/abc/promote', expect.objectContaining({ method: 'POST' }))
  })

  it('deletePlaybookDraft DELETEs /api/playbooks/drafts/:id', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ status: 'ok' }) })
    await deletePlaybookDraft('abc')
    expect(mockFetch).toHaveBeenCalledWith('/api/playbooks/drafts/abc', expect.objectContaining({ method: 'DELETE' }))
  })

  it('fetchPlaybookHistory calls GET /api/playbooks/:id/history', async () => {
    const mock = { runs: [] }
    mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mock) })
    const result = await fetchPlaybookHistory('abc')
    expect(mockFetch).toHaveBeenCalledWith('/api/playbooks/abc/history')
    expect(result.runs).toEqual([])
  })
})
