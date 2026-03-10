import { useEffect, useRef } from 'react'

export type SSEEvent =
  | { type: 'cache-invalidate'; source: string }
  | { type: 'card'; data: unknown }

export function useSSE(onEvent: (event: SSEEvent) => void) {
  const onEventRef = useRef(onEvent)
  onEventRef.current = onEvent

  useEffect(() => {
    const es = new EventSource('/api/events')

    es.addEventListener('cache-invalidate', (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data)
        onEventRef.current({ type: 'cache-invalidate', source: data.source })
      } catch { /* ignore malformed */ }
    })

    es.addEventListener('message', (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data)
        onEventRef.current({ type: 'card', data })
      } catch { /* ignore malformed */ }
    })

    return () => es.close()
  }, [])
}
