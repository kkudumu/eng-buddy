import { describe, it, expect, beforeEach } from 'vitest'
import { useUIStore } from '../ui'

beforeEach(() => {
  useUIStore.setState({
    activeSource: 'all',
    activeCardId: null,
    expandedActions: new Set(),
  })
})

describe('useUIStore', () => {
  it('has correct initial state', () => {
    const state = useUIStore.getState()
    expect(state.activeSource).toBe('all')
    expect(state.activeCardId).toBeNull()
    expect(state.expandedActions.size).toBe(0)
  })

  it('sets active source', () => {
    useUIStore.getState().setActiveSource('gmail')
    expect(useUIStore.getState().activeSource).toBe('gmail')
  })

  it('sets active card', () => {
    useUIStore.getState().setActiveCard(42)
    expect(useUIStore.getState().activeCardId).toBe(42)
  })

  it('toggles expanded actions', () => {
    useUIStore.getState().toggleExpandedActions(42)
    expect(useUIStore.getState().expandedActions.has(42)).toBe(true)

    useUIStore.getState().toggleExpandedActions(42)
    expect(useUIStore.getState().expandedActions.has(42)).toBe(false)
  })
})
