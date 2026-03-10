import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useSSE } from '../useSSE'

let mockEventSource: {
  addEventListener: ReturnType<typeof vi.fn>
  close: ReturnType<typeof vi.fn>
  onopen: (() => void) | null
  onerror: (() => void) | null
}

beforeEach(() => {
  mockEventSource = {
    addEventListener: vi.fn(),
    close: vi.fn(),
    onopen: null,
    onerror: null,
  }
  vi.stubGlobal('EventSource', vi.fn(function () { return mockEventSource }))
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('useSSE', () => {
  it('creates EventSource connection to /api/events', () => {
    const onEvent = vi.fn()
    renderHook(() => useSSE(onEvent))

    expect(EventSource).toHaveBeenCalledWith('/api/events')
  })

  it('listens for cache-invalidate events', () => {
    const onEvent = vi.fn()
    renderHook(() => useSSE(onEvent))

    expect(mockEventSource.addEventListener).toHaveBeenCalledWith(
      'cache-invalidate',
      expect.any(Function),
    )
  })

  it('listens for message events', () => {
    const onEvent = vi.fn()
    renderHook(() => useSSE(onEvent))

    expect(mockEventSource.addEventListener).toHaveBeenCalledWith(
      'message',
      expect.any(Function),
    )
  })

  it('closes connection on unmount', () => {
    const onEvent = vi.fn()
    const { unmount } = renderHook(() => useSSE(onEvent))

    unmount()
    expect(mockEventSource.close).toHaveBeenCalled()
  })
})
