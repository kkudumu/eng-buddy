import { create } from 'zustand'

export type ToastLevel = 'success' | 'error' | 'info'

export interface Toast {
  id: string
  message: string
  level: ToastLevel
}

interface ToastState {
  toasts: Toast[]
  addToast: (message: string, level: ToastLevel) => void
  removeToast: (id: string) => void
  clear: () => void
}

let nextId = 0

export const useToastStore = create<ToastState>((set) => ({
  toasts: [],
  addToast: (message, level) => {
    const id = `toast-${++nextId}`
    set((s) => ({ toasts: [...s.toasts, { id, message, level }] }))
    setTimeout(() => {
      set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }))
    }, 4000)
  },
  removeToast: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
  clear: () => set({ toasts: [] }),
}))
