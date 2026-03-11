import { useCallback, useMemo } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useSSE } from './hooks/useSSE'
import type { SSEEvent } from './hooks/useSSE'
import { useCards } from './hooks/useCards'
import { useUIStore } from './stores/ui'
import { Header } from './features/inbox/Header'
import { Sidebar } from './features/inbox/Sidebar'
import { CardList } from './features/inbox/CardList'
import { StatsBar } from './features/stats/StatsBar'
import styles from './App.module.css'

const particles = ['\u273f', '\u22c6', '\u2661', '\u2727', '\u273f', '\u22c6', '\u2661', '\u2727']

export default function App() {
  const queryClient = useQueryClient()
  const activeSource = useUIStore((s) => s.activeSource)
  const { data, isLoading } = useCards(activeSource)

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

  const sourceCounts = useMemo(() => {
    const cards = data?.cards ?? []
    const result: Record<string, number> = {}
    for (const card of cards) {
      result[card.source] = (result[card.source] ?? 0) + 1
    }
    return result
  }, [data?.cards])

  return (
    <div className={styles.layout}>
      {/* Background particles */}
      <div className={styles.particles}>
        {particles.map((p, i) => (
          <span
            key={i}
            className={styles.particle}
            style={{
              left: `${10 + i * 12}%`,
              top: `${20 + (i % 3) * 25}%`,
              animationDelay: `${i * 1.2}s`,
              animationDuration: `${6 + (i % 4) * 2}s`,
            }}
          >
            {p}
          </span>
        ))}
      </div>

      <Header pendingCount={counts.pending} isLoading={isLoading} />

      <StatsBar
        needsAction={counts.pending}
        autoResolved={counts.completed}
        draftAcceptRate={(counts.approved + counts.failed) > 0 ? Math.round((counts.approved / (counts.approved + counts.failed)) * 100) : 0}
        timeSavedMinutes={counts.completed * 5}
      />

      <div className={styles.body}>
        <Sidebar counts={counts} sourceCounts={sourceCounts} />
        <div className={styles.content}>
          <CardList />
        </div>
      </div>
    </div>
  )
}
