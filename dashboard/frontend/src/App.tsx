import { useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { useCards } from './hooks/useCards'
import { useUIStore } from './stores/ui'
import { StatsBar } from './features/stats/StatsBar'
import { CardList } from './features/inbox/CardList'
import type { CardSource } from './api/types'

export default function App() {
  const { source } = useParams<{ source?: string }>()
  const activeSource: CardSource = (source as CardSource) || 'all'
  const setActiveSource = useUIStore((s) => s.setActiveSource)

  useEffect(() => {
    setActiveSource(activeSource)
  }, [activeSource, setActiveSource])

  const { data } = useCards(activeSource)

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
