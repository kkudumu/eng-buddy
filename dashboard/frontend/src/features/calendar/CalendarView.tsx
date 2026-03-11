import { useQuery } from '@tanstack/react-query'
import { fetchCards, openSession } from '../../api/client'
import { useToastStore } from '../../stores/toast'
import styles from './CalendarView.module.css'

function getEventGroup(timestamp: string): string {
  const eventDate = new Date(timestamp)
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const tomorrow = new Date(today.getTime() + 86400000)
  const weekEnd = new Date(today.getTime() + 7 * 86400000)

  if (eventDate < tomorrow) return "TODAY'S AGENDA"
  if (eventDate < weekEnd) return 'UPCOMING THIS WEEK'
  return 'NEXT WEEK'
}

export function CalendarView() {
  const { data, isLoading } = useQuery({
    queryKey: ['cards', 'calendar'],
    queryFn: () => fetchCards('calendar'),
  })
  const addToast = useToastStore((s) => s.addToast)

  const cards = data?.cards ?? []
  const groups: Record<string, typeof cards> = { "TODAY'S AGENDA": [], 'UPCOMING THIS WEEK': [], 'NEXT WEEK': [] }

  for (const card of cards) {
    const group = getEventGroup(card.timestamp)
    ;(groups[group] ?? groups['NEXT WEEK']).push(card)
  }

  const handlePrepNotes = async (cardId: number) => {
    try {
      await openSession('cards', cardId)
      addToast('Prep session opened', 'success')
    } catch {
      addToast('Failed to open prep session', 'error')
    }
  }

  if (isLoading) return <div className={styles.loading}>Loading calendar...</div>

  return (
    <div className={styles.container}>
      <h2 className={styles.heading}>Calendar</h2>
      {Object.entries(groups).map(([group, items]) => (
        items.length > 0 && (
          <div key={group} className={styles.section}>
            <h3 className={styles.sectionTitle}>{group}</h3>
            {items.map((card) => (
              <div key={card.id} className={styles.event}>
                <div className={styles.time}>
                  {new Date(card.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </div>
                <div className={styles.details}>
                  <div className={styles.title}>{card.summary}</div>
                  {card.context_notes && <div className={styles.summary}>{card.context_notes}</div>}
                </div>
                <div className={styles.eventActions}>
                  <button onClick={() => handlePrepNotes(card.id)}>Prep Notes</button>
                </div>
              </div>
            ))}
          </div>
        )
      ))}
      {cards.length === 0 && <div className={styles.empty}>No upcoming events</div>}
    </div>
  )
}
