import { create } from 'zustand'
import type { CardSource, SettingsResponse } from '../api/types'

export type ThemeName = 'neon-dreams' | 'midnight-ops' | 'soft-kitty'
export type ModeName = 'dark' | 'light'
export type TerminalName = 'Terminal' | 'Warp' | 'iTerm' | 'Alacritty' | 'kitty'

interface UIState {
  activeSource: CardSource
  expandedActions: Set<number>
  expandedPlanCards: Set<number>
  editingStep: { cardId: number; stepIndex: number } | null
  theme: ThemeName
  mode: ModeName
  terminal: TerminalName
  macosNotifications: boolean
  setActiveSource: (source: CardSource) => void
  toggleExpandedActions: (id: number) => void
  togglePlanExpanded: (cardId: number) => void
  setEditingStep: (ref: { cardId: number; stepIndex: number } | null) => void
  setTheme: (theme: ThemeName) => void
  toggleMode: () => void
  setTerminal: (terminal: TerminalName) => void
  setMacosNotifications: (enabled: boolean) => void
  hydrateSettings: (settings: SettingsResponse) => void
}

function applyThemeToDOM(theme: string, mode: string) {
  document.documentElement.dataset.theme = theme
  document.documentElement.dataset.mode = mode
}

export const useUIStore = create<UIState>()((set) => ({
  activeSource: 'all',
  expandedActions: new Set(),
  expandedPlanCards: new Set(),
  editingStep: null,
  theme: 'neon-dreams',
  mode: 'dark',
  terminal: 'Terminal',
  macosNotifications: false,

  setActiveSource: (source) => set({ activeSource: source }),

  toggleExpandedActions: (id) =>
    set((state) => {
      const next = new Set(state.expandedActions)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return { expandedActions: next }
    }),

  togglePlanExpanded: (cardId) =>
    set((state) => {
      const next = new Set(state.expandedPlanCards)
      if (next.has(cardId)) next.delete(cardId)
      else next.add(cardId)
      return { expandedPlanCards: next }
    }),

  setEditingStep: (ref) => set({ editingStep: ref }),

  setTheme: (theme) => {
    applyThemeToDOM(theme, useUIStore.getState().mode)
    set({ theme })
  },

  toggleMode: () =>
    set((state) => {
      const mode = state.mode === 'dark' ? 'light' : 'dark'
      applyThemeToDOM(state.theme, mode)
      return { mode }
    }),

  setTerminal: (terminal) => set({ terminal }),

  setMacosNotifications: (enabled) => set({ macosNotifications: enabled }),

  hydrateSettings: (settings) => {
    const theme = (settings.theme || 'neon-dreams') as ThemeName
    const mode = (settings.mode || 'dark') as ModeName
    const terminal = (settings.terminal || 'Terminal') as TerminalName
    const macosNotifications = settings.macos_notifications ?? false
    applyThemeToDOM(theme, mode)
    set({ theme, mode, terminal, macosNotifications })
  },
}))
