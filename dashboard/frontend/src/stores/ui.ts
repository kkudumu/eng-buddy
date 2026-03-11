import { create } from 'zustand'
import type { CardSource } from '../api/types'

interface UIState {
  activeSource: CardSource
  activeCardId: number | null
  expandedActions: Set<number>
  expandedPlanCards: Set<number>
  editingStep: { cardId: number; stepIndex: number } | null
  setActiveSource: (source: CardSource) => void
  setActiveCard: (id: number | null) => void
  toggleExpandedActions: (id: number) => void
  togglePlanExpanded: (cardId: number) => void
  setEditingStep: (ref: { cardId: number; stepIndex: number } | null) => void
}

export const useUIStore = create<UIState>((set) => ({
  activeSource: 'all',
  activeCardId: null,
  expandedActions: new Set(),
  expandedPlanCards: new Set(),
  editingStep: null,

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
}))
