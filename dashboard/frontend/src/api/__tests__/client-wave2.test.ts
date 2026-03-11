import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fetchSettings, updateSettings, postDecision, fetchPollers, syncPoller, postRestart } from '../client'

const mockFetch = vi.fn()
global.fetch = mockFetch

beforeEach(() => mockFetch.mockReset())

describe('Wave 2 API client', () => {
  it('fetchSettings calls GET /api/settings', async () => {
    const mock = { terminal: 'Warp', theme: 'neon-dreams', mode: 'dark', macos_notifications: false }
    mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mock) })
    const result = await fetchSettings()
    expect(mockFetch).toHaveBeenCalledWith('/api/settings')
    expect(result).toEqual(mock)
  })

  it('updateSettings POSTs to /api/settings', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({}) })
    await updateSettings({ theme: 'soft-kitty' })
    expect(mockFetch).toHaveBeenCalledWith('/api/settings', expect.objectContaining({ method: 'POST' }))
  })

  it('postDecision POSTs to correct entity endpoint', async () => {
    const mock = { card_id: 1, action: 'hold', decision: 'rejected', decision_event_id: 42, action_step_id: 7 }
    mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mock) })
    const result = await postDecision('cards', 1, 'hold', 'rejected', 'not ready')
    expect(mockFetch).toHaveBeenCalledWith('/api/cards/1/decision', expect.objectContaining({ method: 'POST' }))
    expect(result.decision_event_id).toBe(42)
  })

  it('fetchPollers calls GET /api/pollers/status', async () => {
    const mock = { pollers: [], generated_at: '2026-01-01T00:00:00Z' }
    mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mock) })
    await fetchPollers()
    expect(mockFetch).toHaveBeenCalledWith('/api/pollers/status')
  })

  it('syncPoller POSTs to /api/pollers/{id}/sync', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ status: 'syncing' }) })
    await syncPoller('slack')
    expect(mockFetch).toHaveBeenCalledWith('/api/pollers/slack/sync', expect.objectContaining({ method: 'POST' }))
  })

  it('postRestart POSTs to /api/restart', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ status: 'restarting' }) })
    await postRestart()
    expect(mockFetch).toHaveBeenCalledWith('/api/restart', expect.objectContaining({ method: 'POST' }))
  })
})
