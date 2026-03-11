import { create } from 'zustand'
import type { CardSource, SettingsResponse } from '../api/types'

export type ThemeName = 'neon-dreams' | 'midnight-ops' | 'soft-kitty'
export type ModeName = 'dark' | 'light'

interface UIState {
  activeSource: CardSource
  activeCardId: number | null
  expandedActions: Set<number>
  expandedPlanCards: Set<number>
  editingStep: { cardId: number; stepIndex: number } | null
  theme: ThemeName
  mode: ModeName
  setActiveSource: (source: CardSource) => void
  setActiveCard: (id: number | null) => void
  toggleExpandedActions: (id: number) => void
  togglePlanExpanded: (cardId: number) => void
  setEditingStep: (ref: { cardId: number; stepIndex: number } | null) => void
  setTheme: (theme: ThemeName) => void
  toggleMode: () => void
  hydrateSettings: (settings: SettingsResponse) => void
}

function applyThemeToDOM(theme: string, mode: string) {
  document.documentElement.dataset.theme = theme
  document.documentElement.dataset.mode = mode
}

export const useUIStore = create<UIState>()((set) => ({
  activeSource: 'all',
  activeCardId: null,
  expandedActions: new Set(),
  expandedPlanCards: new Set(),
  editingStep: null,
  theme: 'neon-dreams',
  mode: 'dark',

  setActiveSource: (source) => set({ activeSource: source }),

  setActiveCard: (id) => set({ activeCardId: id }),

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

  hydrateSettings: (settings) => {
    const theme = (settings.theme || 'neon-dreams') as ThemeName
    const mode = (settings.mode || 'dark') as ModeName
    applyThemeToDOM(theme, mode)
    set({ theme, mode })
  },
}))
