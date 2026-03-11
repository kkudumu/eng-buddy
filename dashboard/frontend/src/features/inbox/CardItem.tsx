import { useState, useCallback } from 'react'
import type { Card } from '../../api/types'
import { Badge } from '../../components/Badge'
import { ActionTray } from './ActionTray'
import { GmailActions } from './GmailActions'
import { Terminal } from '../terminal/Terminal'
import { postDecision, performCardAction } from '../../api/client'
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
  const [running, setRunning] = useState(false)
  const [decisionEventId, setDecisionEventId] = useState<number | null>(null)

  const handleApprove = async () => {
    try {
      const result = await postDecision('cards', card.id, 'approve', 'approved')
      setDecisionEventId(result.decision_event_id)
      setRunning(true)
      await performCardAction(card.id, 'approve', { decision_event_id: result.decision_event_id })
    } catch {
      addToast(`Failed to approve card #${card.id}`, 'error')
    }
  }

  const handleTerminalClose = useCallback(() => {
    setRunning(false)
    setDecisionEventId(null)
    addToast(`Card #${card.id} execution complete`, 'info')
  }, [card.id, addToast])

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
      {isExpanded && !running && (
        <div onClick={(e) => e.stopPropagation()}>
          <ActionTray card={card} onApprove={handleApprove} />
          {card.source === 'gmail' && <GmailActions card={card} />}
        </div>
      )}
      {running && decisionEventId != null && (
        <div onClick={(e) => e.stopPropagation()}>
          <Terminal cardId={card.id} decisionEventId={decisionEventId} onClose={handleTerminalClose} />
        </div>
      )}
    </div>
  )
}
