import { describe, it, expect, beforeEach } from 'vitest'
import { useUIStore } from '../ui'

beforeEach(() => {
  localStorage.clear()
  useUIStore.setState({
    activeSource: 'all',
    activeCardId: null,
    expandedActions: new Set(),
    theme: 'neon-dreams',
    mode: 'dark',
    terminal: 'Terminal',
    macosNotifications: false,
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

  it('sets theme and applies to DOM', () => {
    useUIStore.getState().setTheme('midnight-ops')
    expect(useUIStore.getState().theme).toBe('midnight-ops')
    expect(document.documentElement.getAttribute('data-theme')).toBe('midnight-ops')
    expect(localStorage.getItem('eb-theme')).toBe('midnight-ops')
  })

  it('toggles mode between dark and light', () => {
    useUIStore.getState().toggleMode()
    expect(useUIStore.getState().mode).toBe('light')
    expect(document.documentElement.getAttribute('data-mode')).toBe('light')

    useUIStore.getState().toggleMode()
    expect(useUIStore.getState().mode).toBe('dark')
  })

  it('hydrates settings from server response', () => {
    useUIStore.getState().hydrateSettings({
      theme: 'soft-kitty',
      mode: 'light',
      terminal: 'Warp',
      macos_notifications: true,
    })
    const state = useUIStore.getState()
    expect(state.theme).toBe('soft-kitty')
    expect(state.mode).toBe('light')
    expect(state.terminal).toBe('Warp')
    expect(state.macosNotifications).toBe(true)
  })

  it('ignores invalid theme/mode values during hydration', () => {
    useUIStore.getState().hydrateSettings({
      theme: 'invalid-theme',
      mode: 'invalid-mode',
    })
    const state = useUIStore.getState()
    expect(state.theme).toBe('neon-dreams')
    expect(state.mode).toBe('dark')
  })
})
