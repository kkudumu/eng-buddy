import type { Card } from '../../api/types'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { useUIStore } from '../../stores/ui'
import { useCardDecision } from '../../hooks/useCardDecision'
import { useGeneratePlan } from '../../hooks/usePlan'
import { useToastStore } from '../../stores/toast'
import { PlanView } from '../plan/PlanView'
import { ActionTray } from './ActionTray'
import { GmailActions } from './GmailActions'
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
  const expandedActions = useUIStore((s) => s.expandedActions)
  const toggleExpandedActions = useUIStore((s) => s.toggleExpandedActions)
  const decision = useCardDecision()
  const generatePlan = useGeneratePlan(card.id)
  const addToast = useToastStore((s) => s.addToast)

  const isPlanExpanded = expandedPlanCards.has(card.id)
  const isActionsExpanded = expandedActions.has(card.id)

  const handleApprove = () => {
    decision.mutate({ cardId: card.id, action: 'approve', decision: 'approved', followUp: { endpoint: 'status', body: { status: 'approved' } } })
  }

  const handlePlanClick = () => {
    if (isPlanExpanded) {
      togglePlanExpanded(card.id)
      return
    }

    generatePlan.mutate(undefined, {
      onSuccess: () => {
        togglePlanExpanded(card.id)
      },
      onError: () => {
        addToast(`Failed to generate plan for card #${card.id}`, 'error')
      },
    })
  }

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
          label={isPlanExpanded ? 'Hide Plan' : (generatePlan.isPending ? 'Generating...' : 'Generate Plan')}
          onClick={handlePlanClick}
          variant="ghost"
          disabled={generatePlan.isPending}
        />
        <Button
          label={isActionsExpanded ? 'Hide Actions' : 'Actions'}
          onClick={() => toggleExpandedActions(card.id)}
          variant="ghost"
        />
      </div>
      {isActionsExpanded && (
        <>
          <ActionTray card={card} onApprove={handleApprove} />
          {card.source === 'gmail' && <GmailActions card={card} />}
        </>
      )}
      {isPlanExpanded && <PlanView cardId={card.id} />}
    </div>
  )
}
