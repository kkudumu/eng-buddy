import { describe, it, expect, beforeEach } from 'vitest'
import { useDebugStore } from '../debug'

beforeEach(() => useDebugStore.getState().clear())

describe('useDebugStore', () => {
  it('adds a debug entry', () => {
    useDebugStore.getState().addEntry('info', 'GET /api/cards', { status: 200, duration: 45 })
    const entries = useDebugStore.getState().entries
    expect(entries).toHaveLength(1)
    expect(entries[0].level).toBe('info')
    expect(entries[0].message).toBe('GET /api/cards')
  })

  it('limits to 150 entries', () => {
    for (let i = 0; i < 160; i++) {
      useDebugStore.getState().addEntry('info', `entry ${i}`)
    }
    expect(useDebugStore.getState().entries).toHaveLength(150)
  })

  it('toggles drawer open state', () => {
    expect(useDebugStore.getState().isOpen).toBe(false)
    useDebugStore.getState().toggle()
    expect(useDebugStore.getState().isOpen).toBe(true)
  })
})
