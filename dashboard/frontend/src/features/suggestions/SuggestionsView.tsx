import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchSuggestions, performCardAction } from '../../api/client'
import { useToastStore } from '../../stores/toast'
import styles from './SuggestionsView.module.css'

export function SuggestionsView() {
  const queryClient = useQueryClient()
  const addToast = useToastStore((s) => s.addToast)
  const [showHeld, setShowHeld] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['suggestions'],
    queryFn: () => fetchSuggestions(),
  })

  const cards = data?.cards ?? []
  const active = cards.filter((c) => c.status === 'pending')
  const held = cards.filter((c) => c.status === 'held')

  const handleAction = async (cardId: number, action: string) => {
    try {
      await performCardAction(cardId, action)
      queryClient.invalidateQueries({ queryKey: ['suggestions'] })
      addToast(`Suggestion #${cardId}: ${action}`, 'success')
    } catch {
      addToast(`Failed to ${action} suggestion #${cardId}`, 'error')
    }
  }

  const handleRefresh = () => {
    fetchSuggestions(true).then(() => queryClient.invalidateQueries({ queryKey: ['suggestions'] }))
  }

  if (isLoading) return <div className={styles.loading}>Loading suggestions...</div>

  return (
    <div className={styles.container}>
      <div className={styles.headerRow}>
        <h2 className={styles.heading}>Suggestions ({active.length})</h2>
        <button onClick={handleRefresh} className={styles.refresh}>Refresh</button>
      </div>
      {active.length === 0 && <div className={styles.empty}>No active suggestions</div>}
      {active.map((card) => (
        <div key={card.id} className={styles.card}>
          <div className={styles.title}>{card.summary}</div>
          {card.context_notes && <div className={styles.summary}>{card.context_notes}</div>}
          <div className={styles.actions}>
            <button onClick={() => handleAction(card.id, 'approve')} className={styles.approve}>Approve</button>
            <button onClick={() => handleAction(card.id, 'deny')} className={styles.deny}>Deny</button>
          </div>
        </div>
      ))}
      {held.length > 0 && (
        <div className={styles.heldSection}>
          <button onClick={() => setShowHeld(!showHeld)} className={styles.heldToggle}>
            {showHeld ? 'Hide' : 'Show'} Held ({held.length})
          </button>
          {showHeld && held.map((card) => (
            <div key={card.id} className={`${styles.card} ${styles.heldCard}`}>
              <div className={styles.title}>{card.summary}</div>
              {card.context_notes && <div className={styles.summary}>{card.context_notes}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
