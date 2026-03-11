import { create } from 'zustand'
import type { CardSource } from '../api/types'

export type ThemeName = 'neon-dreams' | 'midnight-ops' | 'soft-kitty'
export type ModeName = 'dark' | 'light'
export type TerminalName = 'Terminal' | 'Warp' | 'iTerm' | 'Alacritty' | 'kitty'

interface UIState {
  activeSource: CardSource
  activeCardId: number | null
  expandedActions: Set<number>
  theme: ThemeName
  mode: ModeName
  terminal: TerminalName
  macosNotifications: boolean
  setActiveSource: (source: CardSource) => void
  setActiveCard: (id: number | null) => void
  toggleExpandedActions: (id: number) => void
  setTheme: (theme: ThemeName) => void
  setMode: (mode: ModeName) => void
  toggleMode: () => void
  setTerminal: (terminal: TerminalName) => void
  setMacosNotifications: (enabled: boolean) => void
  hydrateSettings: (settings: { theme?: string; mode?: string; terminal?: string; macos_notifications?: boolean }) => void
}

function applyThemeToDOM(theme: ThemeName, mode: ModeName) {
  document.documentElement.setAttribute('data-theme', theme)
  document.documentElement.setAttribute('data-mode', mode)
  localStorage.setItem('eb-theme', theme)
  localStorage.setItem('eb-mode', mode)
}

export const useUIStore = create<UIState>((set, get) => ({
  activeSource: 'all',
  activeCardId: null,
  expandedActions: new Set(),
  theme: (localStorage.getItem('eb-theme') as ThemeName) || 'neon-dreams',
  mode: (localStorage.getItem('eb-mode') as ModeName) || 'dark',
  terminal: 'Terminal',
  macosNotifications: false,

  setActiveSource: (source) => set({ activeSource: source }),
  setActiveCard: (id) => set({ activeCardId: id }),
  toggleExpandedActions: (id) =>
    set((state) => {
      const next = new Set(state.expandedActions)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return { expandedActions: next }
    }),
  setTheme: (theme) => {
    set({ theme })
    applyThemeToDOM(theme, get().mode)
  },
  setMode: (mode) => {
    set({ mode })
    applyThemeToDOM(get().theme, mode)
  },
  toggleMode: () => {
    const next = get().mode === 'dark' ? 'light' : 'dark'
    set({ mode: next })
    applyThemeToDOM(get().theme, next)
  },
  setTerminal: (terminal) => set({ terminal }),
  setMacosNotifications: (enabled) => set({ macosNotifications: enabled }),
  hydrateSettings: (s) => {
    const theme = (['neon-dreams', 'midnight-ops', 'soft-kitty'].includes(s.theme ?? '') ? s.theme : get().theme) as ThemeName
    const mode = (['dark', 'light'].includes(s.mode ?? '') ? s.mode : get().mode) as ModeName
    const terminal = (['Terminal', 'Warp', 'iTerm', 'Alacritty', 'kitty'].includes(s.terminal ?? '') ? s.terminal : get().terminal) as TerminalName
    set({ theme, mode, terminal, macosNotifications: s.macos_notifications ?? false })
    applyThemeToDOM(theme, mode)
  },
}))
