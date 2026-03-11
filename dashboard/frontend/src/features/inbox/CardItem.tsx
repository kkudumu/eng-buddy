import type { Card } from '../../api/types'
import { Badge } from '../../components/Badge'
import { ActionTray } from './ActionTray'
import { performCardAction } from '../../api/client'
import { useUIStore } from '../../stores/ui'
import { useToastStore } from '../../stores/toast'
import styles from './CardItem.module.css'

interface CardItemProps {
  card: Card
  style?: React.CSSProperties
}

const sourceColors: Record<string, 'pink' | 'mint' | 'blue' | 'coral' | 'muted'> = {
  gmail: 'pink',
  slack: 'mint',
  jira: 'blue',
  freshservice: 'coral',
}

function formatTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

export function CardItem({ card, style }: CardItemProps) {
  const sourceClass = styles[card.source] ?? ''
  const expandedActions = useUIStore((s) => s.expandedActions)
  const toggleExpandedActions = useUIStore((s) => s.toggleExpandedActions)
  const addToast = useToastStore((s) => s.addToast)
  const isExpanded = expandedActions.has(card.id)

  const handleApprove = async () => {
    try {
      await performCardAction(card.id, 'approve')
      addToast(`Card #${card.id} approved`, 'success')
    } catch {
      addToast(`Failed to approve card #${card.id}`, 'error')
    }
  }

  return (
    <div
      className={`${styles.card} ${sourceClass}`}
      style={style}
      onClick={() => toggleExpandedActions(card.id)}
    >
      <div className={styles.header}>
        <Badge text={card.source} color={sourceColors[card.source] ?? 'muted'} />
        <span className={styles.summary}>{card.summary}</span>
        <span className={styles.meta}>{formatTime(card.timestamp)}</span>
      </div>
      {card.context_notes && (
        <div className={styles.meta}>{card.context_notes}</div>
      )}
      {card.draft_response && (
        <div className={styles.draft}>{card.draft_response}</div>
      )}
      {isExpanded && (
        <div onClick={(e) => e.stopPropagation()}>
          <ActionTray card={card} onApprove={handleApprove} />
        </div>
      )}
    </div>
  )
}
