import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useToastStore } from '../toast'

beforeEach(() => useToastStore.getState().clear())

describe('useToastStore', () => {
  it('adds a toast with auto-generated id', () => {
    useToastStore.getState().addToast('Hello', 'success')
    const toasts = useToastStore.getState().toasts
    expect(toasts).toHaveLength(1)
    expect(toasts[0].message).toBe('Hello')
    expect(toasts[0].level).toBe('success')
    expect(toasts[0].id).toBeDefined()
  })

  it('removes a toast by id', () => {
    useToastStore.getState().addToast('A', 'info')
    const id = useToastStore.getState().toasts[0].id
    useToastStore.getState().removeToast(id)
    expect(useToastStore.getState().toasts).toHaveLength(0)
  })

  it('clears all toasts', () => {
    useToastStore.getState().addToast('A', 'info')
    useToastStore.getState().addToast('B', 'error')
    useToastStore.getState().clear()
    expect(useToastStore.getState().toasts).toHaveLength(0)
  })
})
