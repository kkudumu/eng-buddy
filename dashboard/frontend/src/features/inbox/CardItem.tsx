import type { Card } from '../../api/types'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { useUIStore } from '../../stores/ui'
import { PlanView } from '../plan/PlanView'
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
  const expandedPlanCards = useUIStore((s) => s.expandedPlanCards)
  const togglePlanExpanded = useUIStore((s) => s.togglePlanExpanded)

  const isPlanExpanded = expandedPlanCards.has(card.id)

  return (
    <div className={`${styles.card} ${sourceClass}`} style={style}>
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
      <div className={styles.actions}>
        <Button
          label={isPlanExpanded ? 'Hide Plan' : 'View Plan'}
          onClick={() => togglePlanExpanded(card.id)}
          variant="ghost"
        />
      </div>
      {isPlanExpanded && <PlanView cardId={card.id} />}
    </div>
  )
}
