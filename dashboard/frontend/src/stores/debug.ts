import { create } from 'zustand'

export type DebugLevel = 'info' | 'warn' | 'error'

export interface DebugEntry {
  id: number
  level: DebugLevel
  message: string
  details?: Record<string, unknown>
  timestamp: string
  sentToClaude: boolean
}

interface DebugState {
  entries: DebugEntry[]
  isOpen: boolean
  addEntry: (level: DebugLevel, message: string, details?: Record<string, unknown>) => void
  markSent: (id: number) => void
  toggle: () => void
  clear: () => void
}

const MAX_ENTRIES = 150
let nextId = 0

export const useDebugStore = create<DebugState>((set) => ({
  entries: [],
  isOpen: false,
  addEntry: (level, message, details) => {
    const entry: DebugEntry = {
      id: ++nextId,
      level,
      message,
      details,
      timestamp: new Date().toISOString(),
      sentToClaude: false,
    }
    set((s) => ({
      entries: [entry, ...s.entries].slice(0, MAX_ENTRIES),
    }))
  },
  markSent: (id) =>
    set((s) => ({
      entries: s.entries.map((e) => (e.id === id ? { ...e, sentToClaude: true } : e)),
    })),
  toggle: () => set((s) => ({ isOpen: !s.isOpen })),
  clear: () => set({ entries: [] }),
}))
