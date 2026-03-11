import { useCallback } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useSSE } from './hooks/useSSE'
import type { SSEEvent } from './hooks/useSSE'
import { useCards } from './hooks/useCards'
import { useUIStore } from './stores/ui'
import { CardList } from './features/inbox/CardList'
import { StatsBar } from './features/stats/StatsBar'

export default function App() {
  const queryClient = useQueryClient()
  const activeSource = useUIStore((s) => s.activeSource)
  const { data } = useCards(activeSource)

  const handleSSE = useCallback(
    (event: SSEEvent) => {
      queryClient.invalidateQueries({ queryKey: ['cards'] })
      if (event.type === 'plan_step_update' || event.type === 'plan_complete') {
        queryClient.invalidateQueries({ queryKey: ['plan', event.cardId] })
      }
    },
    [queryClient],
  )

  useSSE(handleSSE)

  const counts = data?.counts ?? { pending: 0, held: 0, approved: 0, completed: 0, failed: 0 }

  return (
    <>
      <StatsBar
        needsAction={counts.pending}
        autoResolved={counts.completed}
        draftAcceptRate={(counts.approved + counts.failed) > 0 ? Math.round((counts.approved / (counts.approved + counts.failed)) * 100) : 0}
        timeSavedMinutes={counts.completed * 5}
      />
      <CardList />
    </>
  )
}
