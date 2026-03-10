import { create } from 'zustand'
import type { CardSource } from '../api/types'

interface UIState {
  activeSource: CardSource
  activeCardId: number | null
  expandedActions: Set<number>
  setActiveSource: (source: CardSource) => void
  setActiveCard: (id: number | null) => void
  toggleExpandedActions: (id: number) => void
}

export const useUIStore = create<UIState>((set) => ({
  activeSource: 'all',
  activeCardId: null,
  expandedActions: new Set(),

  setActiveSource: (source) => set({ activeSource: source }),

  setActiveCard: (id) => set({ activeCardId: id }),

  toggleExpandedActions: (id) =>
    set((state) => {
      const next = new Set(state.expandedActions)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return { expandedActions: next }
    }),
}))
