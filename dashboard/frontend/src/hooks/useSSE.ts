import { useEffect, useRef } from 'react'

export type SSEEvent =
  | { type: 'cache-invalidate'; source: string }
  | { type: 'card'; data: unknown }
  | { type: 'plan_step_update'; cardId: number; stepIndex: number; status: string }
  | { type: 'plan_complete'; cardId: number }

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

    es.addEventListener('plan_step_update', (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data)
        onEventRef.current({
          type: 'plan_step_update',
          cardId: data.card_id,
          stepIndex: data.step_index,
          status: data.status,
        })
      } catch { /* ignore malformed */ }
    })

    es.addEventListener('plan_complete', (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data)
        onEventRef.current({ type: 'plan_complete', cardId: data.card_id })
      } catch { /* ignore malformed */ }
    })

    return () => es.close()
  }, [])
}
