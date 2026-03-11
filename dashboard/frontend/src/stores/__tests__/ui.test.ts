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

describe('theme/mode state', () => {
  beforeEach(() => useUIStore.setState(useUIStore.getInitialState()))

  it('has default theme neon-dreams and mode dark', () => {
    const state = useUIStore.getState()
    expect(state.theme).toBe('neon-dreams')
    expect(state.mode).toBe('dark')
  })

  it('setTheme updates theme', () => {
    useUIStore.getState().setTheme('midnight-ops')
    expect(useUIStore.getState().theme).toBe('midnight-ops')
  })

  it('toggleMode flips dark to light', () => {
    useUIStore.getState().toggleMode()
    expect(useUIStore.getState().mode).toBe('light')
  })

  it('hydrateSettings sets all fields and DOM attrs', () => {
    // Mock document.documentElement.dataset
    const store = useUIStore.getState()
    store.hydrateSettings({ terminal: 'Warp', theme: 'soft-kitty', mode: 'light', macos_notifications: true })
    const state = useUIStore.getState()
    expect(state.theme).toBe('soft-kitty')
    expect(state.mode).toBe('light')
    expect(document.documentElement.dataset.theme).toBe('soft-kitty')
    expect(document.documentElement.dataset.mode).toBe('light')
  })
})
